import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Camera, RotateCcw, Send } from 'lucide-react';

const JPEG_QUALITY = 0.85;
const MAX_WIDTH = 640;

export default function VisionAskPanel({ shell: shellProp, sessionId }) {
  // PairShell renders children via <Outlet context={shellContext}/>,
  // so panels must fall back to useOutletContext() when no shell is
  // passed as a prop. Without this fallback the panel thought it
  // wasn't paired even though PairShell had the WS alive.
  const outletShell = useOutletContext();
  const shell = shellProp || outletShell || {};
  const [cameraError, setCameraError] = useState(null);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [capturedImage, setCapturedImage] = useState(null);
  const [question, setQuestion] = useState('');
  const [responses, setResponses] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);

  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const canvasRef = useRef(null);

  const startCamera = useCallback(async () => {
    setCameraError(null);
    setPermissionDenied(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
        setCameraReady(true);
      }
    } catch (err) {
      const name = err?.name || '';
      if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
        setPermissionDenied(true);
        setCameraError('Camera permission denied.');
      } else {
        setCameraError(err?.message || 'Failed to access camera.');
      }
    }
  }, []);

  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) track.stop();
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraReady(false);
  }, []);

  useEffect(() => {
    startCamera();
    return () => stopCamera();
  }, [startCamera, stopCamera]);

  const captureFrame = useCallback(() => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = canvasRef.current || document.createElement('canvas');
    const scale = Math.min(1, MAX_WIDTH / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY);
    const b64 = dataUrl.split(',')[1] || '';
    setCapturedImage({ dataUrl, b64, width: canvas.width, height: canvas.height });
  }, []);

  const retake = useCallback(() => {
    setCapturedImage(null);
    setQuestion('');
  }, []);

  const pendingQidRef = useRef(null);

  // Subscribe to chat_response frames so "Analyzing…" can be replaced
  // with the brain's actual answer. The shell API is sendFrame /
  // subscribeFrame (NOT .send — that was Subagent D's miss). Without
  // this subscription the response bubble stayed loading forever.
  useEffect(() => {
    if (!shell?.subscribeFrame) return undefined;
    return shell.subscribeFrame((frame) => {
      if (frame?.type !== 'chat_response') return;
      const text = frame?.payload?.text || frame?.payload?.message
        || frame?.payload?.content || '';
      if (!text) return;
      setResponses((prev) => {
        // Route the first text response into the oldest still-loading
        // entry (FIFO). In practice vision submits are one-at-a-time.
        let matched = false;
        const next = prev.map((r) => {
          if (matched) return r;
          if (r.loading && !r.answer) {
            matched = true;
            return { ...r, answer: text, loading: false };
          }
          return r;
        });
        return matched ? next : prev;
      });
    });
  }, [shell]);

  const handleSubmit = useCallback(async (e) => {
    e?.preventDefault?.();
    if (!capturedImage || !question.trim()) return;
    if (typeof shell?.sendFrame !== 'function') {
      setCameraError('Phone is not connected to the brain — pair first.');
      return;
    }
    setSubmitting(true);

    // The brain's frame handler stashes JPEG bytes into
    // state.vision_buffer keyed by node_id; the chat_request that
    // arrives next pulls the latest frame for that node into the
    // LLM prompt as vision input. Order matters: frame FIRST, then
    // chat_request. Both are HUP envelopes shaped as (type, payload).
    shell.sendFrame('frame', {
      data_b64: capturedImage.b64,
      width: capturedImage.width,
      height: capturedImage.height,
      mime: 'image/jpeg',
    });
    shell.sendFrame('chat_request', {
      session_id: sessionId || `phone-${shell?.deviceId || 'session'}`,
      text: question.trim(),
      reply_mode: 'stream',
      // Brain's ChatRequestPayload.channel is a strict Literal that
      // accepts "chat" or "vision_ask" (NOT "vision" — that's a tab
      // name, not a protocol channel). Using the wrong literal trips
      // pydantic validation on the brain side and the envelope gets
      // dropped, leaving "Analyzing…" stuck forever.
      channel: 'vision_ask',
      reply_to: null,
    });

    const qid = `vq_${Date.now()}`;
    pendingQidRef.current = qid;
    setResponses((prev) => [...prev, {
      id: qid,
      question: question.trim(),
      thumbnail: capturedImage.dataUrl,
      answer: null,
      loading: true,
    }]);
    setQuestion('');
    setSubmitting(false);
  }, [capturedImage, question, shell, sessionId]);

  return (
    <div className="phone-vision-panel" data-testid="phone-vision-panel">
      <div className="phone-vision-preview" data-testid="camera-preview">
        {!capturedImage && !permissionDenied && (
          <video ref={videoRef} className="phone-vision-video" playsInline muted autoPlay data-testid="camera-video" />
        )}
        {permissionDenied && (
          <div className="phone-vision-error" data-testid="permission-denied">
            <p>{cameraError || 'Camera permission denied.'}</p>
            <button type="button" onClick={() => startCamera()} className="phone-vision-grant-btn" data-testid="grant-permission-btn">
              Grant camera permission
            </button>
          </div>
        )}
        {cameraError && !permissionDenied && (
          <div className="phone-vision-error" data-testid="camera-error"><p>{cameraError}</p></div>
        )}
        {capturedImage && (
          <div className="phone-vision-captured" data-testid="captured-preview">
            <img src={capturedImage.dataUrl} alt="Captured frame" className="phone-vision-thumbnail" data-testid="captured-thumbnail" />
          </div>
        )}
      </div>

      {!capturedImage && cameraReady && (
        <button type="button" onClick={captureFrame} className="phone-vision-capture-btn" aria-label="Capture" data-testid="capture-button">
          <Camera size={24} /><span>Capture</span>
        </button>
      )}

      {capturedImage && (
        <div className="phone-vision-ask-form" data-testid="ask-form">
          <form onSubmit={handleSubmit}>
            <input type="text" value={question} onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about this image..." className="phone-vision-question-input" data-testid="question-input" />
            <button type="submit" disabled={!question.trim() || submitting} className="phone-vision-send-btn"
              aria-label="Send question" data-testid="send-question-btn"><Send size={16} /></button>
          </form>
          <button type="button" onClick={retake} className="phone-vision-retake-btn" data-testid="retake-button">
            <RotateCcw size={16} /><span>Retake</span>
          </button>
        </div>
      )}

      {responses.length > 0 && (
        <div className="phone-vision-responses" data-testid="vision-responses">
          {responses.map((r) => (
            <div key={r.id} className="phone-vision-response" data-testid="vision-response-item">
              <div className="phone-vision-response-question">
                <img src={r.thumbnail} alt="Asked about" className="phone-vision-inline-thumb" data-testid="response-thumbnail" />
                <span>{r.question}</span>
              </div>
              {r.answer && <div className="phone-vision-response-answer" data-testid="response-answer">{r.answer}</div>}
              {r.loading && !r.answer && <div className="phone-vision-response-loading" data-testid="response-loading">Analyzing...</div>}
            </div>
          ))}
        </div>
      )}
      <canvas ref={canvasRef} style={{ display: 'none' }} data-testid="hidden-canvas" />
    </div>
  );
}
