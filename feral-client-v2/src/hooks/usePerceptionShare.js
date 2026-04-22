/**
 * usePerceptionShare — browser-based perception share.
 *
 * The user grants camera + mic permission from any browser (iPhone Safari,
 * Android Chrome, desktop) and FERAL treats them as a HUP v1.1 daemon.
 *
 * Architecture
 * ------------
 *   getUserMedia()
 *     → <video> offscreen element (bound to the MediaStream)
 *     → OffscreenCanvas for JPEG capture at fps (default 2)
 *     → AudioContext + AudioWorkletNode for 16kHz PCM16 downsample chunking
 *     → secondary WebSocket to /v1/node (brain's HUP endpoint)
 *         • node_register ({node_type: "browser_camera", capabilities: ["camera", "microphone", "browser_share"]})
 *         • video_frame {data_b64, encoding: "jpeg", ...}
 *         • audio_frame {data_b64, encoding: "pcm16", ...}
 *
 * Kept deliberately independent from the shared FeralSocket so:
 *   1. The chat connection stays clean (no accidental media pings).
 *   2. /api/devices/connected picks up the real daemon without new routes.
 *   3. Revocation just closes the second socket — no teardown race with chat.
 *
 * Privacy rules (hard-coded, not a setting)
 * -----------------------------------------
 *   • Streaming only starts when start() is explicitly called.
 *   • Visibility change (tab backgrounded > 60s) auto-pauses.
 *   • stop() tears the MediaStream down AND revokes the daemon.
 *   • The dock indicator mounted by <PerceptionShare/> is always visible
 *     while streaming; there is no hidden-share mode.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE, WS_BASE } from '../lib/config';

const DEFAULT_FPS = 2;
const DEFAULT_JPEG_QUALITY = 0.6;
const PCM_SAMPLE_RATE = 16000;
const MAX_JPEG_BYTES = 512 * 1024;
const HIDDEN_PAUSE_MS = 60 * 1000;

function bytesFromBase64(b64) {
  try {
    // Strip the base64 padding characters; the brain also enforces a
    // decoded-size cap so we match the same arithmetic.
    return Math.floor((b64.length * 3) / 4);
  } catch {
    return 0;
  }
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error('blob read failed'));
    reader.onload = () => {
      const result = String(reader.result || '');
      const idx = result.indexOf('base64,');
      resolve(idx >= 0 ? result.slice(idx + 7) : result);
    };
    reader.readAsDataURL(blob);
  });
}

function float32ToPcm16Base64(float32) {
  const pcm16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, float32[i]));
    pcm16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7FFF;
  }
  const bytes = new Uint8Array(pcm16.buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function pickNodeId() {
  // Stable-within-session id so the brain's device list doesn't flicker
  // as the user pauses/resumes sharing.
  try {
    const existing = window.sessionStorage.getItem('feral_browser_camera_node_id');
    if (existing) return existing;
  } catch { /* sessionStorage may be disabled */ }
  const suffix = Math.random().toString(36).slice(2, 8);
  const nodeId = `browser-camera-${suffix}`;
  try { window.sessionStorage.setItem('feral_browser_camera_node_id', nodeId); } catch { /* ignore */ }
  return nodeId;
}

export function usePerceptionShare({
  fps = DEFAULT_FPS,
  jpegQuality = DEFAULT_JPEG_QUALITY,
  audio = true,
  video = true,
} = {}) {
  const [status, setStatus] = useState('idle'); // idle | requesting | running | paused | error
  const [error, setError] = useState(null);
  const [stats, setStats] = useState({ framesSent: 0, audioChunksSent: 0, lastFrameAt: 0 });
  const [controls, setControls] = useState({ fps, audioMuted: !audio, videoMuted: !video });

  const streamRef = useRef(null);
  const videoElRef = useRef(null);
  const canvasRef = useRef(null);
  const socketRef = useRef(null);
  const audioCtxRef = useRef(null);
  const audioNodeRef = useRef(null);
  const frameLoopRef = useRef(null);
  const visibilityTimerRef = useRef(null);
  const nodeIdRef = useRef(pickNodeId());
  const chunkIdxRef = useRef(0);

  const sendRaw = useCallback((obj) => {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== 1) return false;
    try {
      ws.send(JSON.stringify(obj));
      return true;
    } catch {
      return false;
    }
  }, []);

  const buildEnvelope = useCallback((type, payload) => ({
    msg_id: (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
    session_id: '',
    timestamp_ms: Date.now(),
    hop: 'daemon',
    type,
    payload,
  }), []);

  const captureFrame = useCallback(async () => {
    if (!videoElRef.current || !canvasRef.current || controls.videoMuted) return;
    const video = videoElRef.current;
    const width = Math.min(video.videoWidth || 640, 1280);
    const height = Math.min(video.videoHeight || 480, 960);
    if (!width || !height) return;
    const canvas = canvasRef.current;
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, width, height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', jpegQuality));
    if (!blob) return;
    if (blob.size > MAX_JPEG_BYTES) return; // brain rejects oversized frames; skip instead of shouting
    const data_b64 = await blobToBase64(blob);
    if (bytesFromBase64(data_b64) > MAX_JPEG_BYTES) return;
    const ok = sendRaw(buildEnvelope('video_frame', {
      node_id: nodeIdRef.current,
      encoding: 'jpeg',
      resolution: [width, height],
      data_b64,
      timestamp: Date.now() / 1000,
      metadata: { source: 'browser_camera', quality: Math.round(jpegQuality * 100) },
    }));
    if (ok) {
      setStats((s) => ({ ...s, framesSent: s.framesSent + 1, lastFrameAt: Date.now() }));
    }
  }, [buildEnvelope, controls.videoMuted, jpegQuality, sendRaw]);

  const startFrameLoop = useCallback(() => {
    if (frameLoopRef.current) clearInterval(frameLoopRef.current);
    const intervalMs = Math.max(100, Math.round(1000 / Math.max(1, controls.fps)));
    frameLoopRef.current = setInterval(() => { captureFrame().catch(() => {}); }, intervalMs);
  }, [captureFrame, controls.fps]);

  const stopFrameLoop = useCallback(() => {
    if (frameLoopRef.current) {
      clearInterval(frameLoopRef.current);
      frameLoopRef.current = null;
    }
  }, []);

  const attachAudioWorklet = useCallback(async (stream) => {
    if (!audio || typeof AudioContext === 'undefined') return;
    try {
      const ctx = new AudioContext({ sampleRate: PCM_SAMPLE_RATE });
      audioCtxRef.current = ctx;
      // ScriptProcessor is deprecated but universally available. The modern
      // AudioWorklet path would require bundling a worklet file with the v2
      // client; ScriptProcessor keeps this hook self-contained.
      const source = ctx.createMediaStreamSource(stream);
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = (event) => {
        if (controls.audioMuted) return;
        const input = event.inputBuffer.getChannelData(0);
        const buf = new Float32Array(input);
        const data_b64 = float32ToPcm16Base64(buf);
        const ok = sendRaw(buildEnvelope('audio_frame', {
          node_id: nodeIdRef.current,
          encoding: 'pcm16',
          sample_rate: PCM_SAMPLE_RATE,
          channels: 1,
          duration_ms: Math.round((buf.length / PCM_SAMPLE_RATE) * 1000),
          data_b64,
        }));
        if (ok) {
          chunkIdxRef.current += 1;
          setStats((s) => ({ ...s, audioChunksSent: s.audioChunksSent + 1 }));
        }
      };
      source.connect(processor);
      processor.connect(ctx.destination);
      audioNodeRef.current = processor;
    } catch (e) {
      // Audio is best-effort. Video remains primary.
      // eslint-disable-next-line no-console
      console.warn('Perception audio attach failed:', e);
    }
  }, [audio, buildEnvelope, controls.audioMuted, sendRaw]);

  const detachAudioWorklet = useCallback(() => {
    try { audioNodeRef.current?.disconnect(); } catch { /* ignore */ }
    try { audioCtxRef.current?.close(); } catch { /* ignore */ }
    audioNodeRef.current = null;
    audioCtxRef.current = null;
  }, []);

  const openSocket = useCallback(async () => new Promise((resolve, reject) => {
    try {
      const ws = new WebSocket(`${WS_BASE}/v1/node`);
      socketRef.current = ws;
      ws.onopen = () => {
        ws.send(JSON.stringify(buildEnvelope('node_register', {
          node_id: nodeIdRef.current,
          node_type: 'browser_camera',
          os: navigator?.userAgent || 'browser',
          platform: 'browser',
          manufacturer: 'browser',
          model: 'browser_getUserMedia',
          capabilities: [
            ...(video ? ['camera', 'browser_camera'] : []),
            ...(audio ? ['microphone', 'audio_frame'] : []),
            'video_frame',
            'browser_share',
          ],
        })));
        resolve(ws);
      };
      ws.onerror = () => reject(new Error('perception socket error'));
      ws.onclose = () => {
        if (status !== 'idle') {
          setStatus('paused');
        }
      };
    } catch (err) {
      reject(err);
    }
  }), [audio, buildEnvelope, status, video]);

  const closeSocket = useCallback(() => {
    try { socketRef.current?.close(); } catch { /* ignore */ }
    socketRef.current = null;
  }, []);

  const attachVideo = useCallback(async (stream) => {
    let el = videoElRef.current;
    if (!el) {
      el = document.createElement('video');
      el.muted = true;
      el.playsInline = true;
      el.setAttribute('playsinline', 'true');
      el.style.position = 'fixed';
      el.style.width = '1px';
      el.style.height = '1px';
      el.style.left = '-9999px';
      el.style.top = '-9999px';
      document.body.appendChild(el);
      videoElRef.current = el;
    }
    if (!canvasRef.current) {
      canvasRef.current = document.createElement('canvas');
    }
    el.srcObject = stream;
    try { await el.play(); } catch { /* autoplay restrictions — video tracks will still fire frames */ }
  }, []);

  const detachVideo = useCallback(() => {
    const el = videoElRef.current;
    if (!el) return;
    try {
      const tracks = el.srcObject?.getTracks?.() || [];
      tracks.forEach((t) => t.stop());
    } catch { /* ignore */ }
    try { el.remove(); } catch { /* ignore */ }
    videoElRef.current = null;
    canvasRef.current = null;
  }, []);

  const stop = useCallback(() => {
    stopFrameLoop();
    detachAudioWorklet();
    detachVideo();
    try {
      streamRef.current?.getTracks?.().forEach((t) => t.stop());
    } catch { /* ignore */ }
    streamRef.current = null;
    closeSocket();
    setStatus('idle');
  }, [closeSocket, detachAudioWorklet, detachVideo, stopFrameLoop]);

  const start = useCallback(async () => {
    if (status === 'running' || status === 'requesting') return;
    setError(null);
    setStatus('requesting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video, audio });
      streamRef.current = stream;
      await attachVideo(stream);
      await openSocket();
      await attachAudioWorklet(stream);
      startFrameLoop();
      setStatus('running');
    } catch (e) {
      setError(e?.message || 'permission denied');
      setStatus('error');
      stop();
    }
  }, [attachAudioWorklet, attachVideo, audio, openSocket, startFrameLoop, status, stop, video]);

  const pause = useCallback(() => {
    stopFrameLoop();
    setStatus('paused');
  }, [stopFrameLoop]);

  const resume = useCallback(() => {
    if (!streamRef.current || !socketRef.current) {
      start();
      return;
    }
    startFrameLoop();
    setStatus('running');
  }, [start, startFrameLoop]);

  const setFps = useCallback((next) => {
    setControls((c) => ({ ...c, fps: Math.max(1, Math.min(10, Math.round(next))) }));
  }, []);

  const toggleAudio = useCallback(() => {
    setControls((c) => ({ ...c, audioMuted: !c.audioMuted }));
  }, []);

  const toggleVideo = useCallback(() => {
    setControls((c) => ({ ...c, videoMuted: !c.videoMuted }));
  }, []);

  useEffect(() => {
    if (status === 'running') startFrameLoop();
  }, [controls.fps, startFrameLoop, status]);

  // Auto-pause when the tab is hidden for > HIDDEN_PAUSE_MS.
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'hidden') {
        visibilityTimerRef.current = setTimeout(() => {
          if (status === 'running') pause();
        }, HIDDEN_PAUSE_MS);
      } else {
        if (visibilityTimerRef.current) {
          clearTimeout(visibilityTimerRef.current);
          visibilityTimerRef.current = null;
        }
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      document.removeEventListener('visibilitychange', onVis);
      if (visibilityTimerRef.current) clearTimeout(visibilityTimerRef.current);
    };
  }, [pause, status]);

  useEffect(() => () => stop(), [stop]);

  return useMemo(() => ({
    status,
    error,
    stats,
    controls,
    nodeId: nodeIdRef.current,
    start,
    stop,
    pause,
    resume,
    setFps,
    toggleAudio,
    toggleVideo,
    apiBase: API_BASE,
  }), [controls, error, pause, resume, setFps, start, stats, status, stop, toggleAudio, toggleVideo]);
}

export default usePerceptionShare;
