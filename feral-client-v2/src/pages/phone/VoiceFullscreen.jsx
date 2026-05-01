/**
 * VoiceFullscreen — full-screen voice agent modal for the phone UX.
 *
 * API contract (for Subagent D / ChatPanel long-press-mic):
 * @param {object} props
 * @param {boolean} props.open       — whether the fullscreen modal is visible
 * @param {() => void} props.onClose — called when the user dismisses the modal
 * @param {'idle'|'listening'} [props.initialMode='idle'] — starting state
 * @param {{ send: (type: string, payload: object) => void,
 *           onFrame: (cb: (frame: object) => void) => (() => void),
 *           node?: object,
 *           voice_config?: { mode?: string } }} [props.shell]
 *   — shell context providing WS send, frame subscription, and node reference.
 *     If omitted, the component renders in a disconnected/demo state.
 *
 * Usage:
 *   import { VoiceFullscreen } from '../phone/VoiceFullscreen';
 *   <VoiceFullscreen open={isOpen} onClose={() => setOpen(false)} initialMode="listening" shell={shell} />
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import VoiceOrb from './VoiceOrb';

const VOICE_STATES = ['idle', 'listening', 'processing', 'speaking', 'error'];

function triggerHaptic(pattern) {
  if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
    navigator.vibrate(pattern);
  }
}

function providerLabel(mode) {
  if (!mode) return '';
  if (mode === 'openai_realtime') return 'OpenAI Realtime';
  if (mode === 'gemini_live') return 'Gemini Live';
  if (mode.startsWith('chained')) return 'Chained (Deepgram)';
  return mode;
}

export function VoiceFullscreen({ open, onClose, initialMode = 'idle', shell }) {
  const [voiceState, setVoiceState] = useState(initialMode);
  const [transcript, setTranscript] = useState('');
  const [partialTranscript, setPartialTranscript] = useState('');
  const [brainText, setBrainText] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [isMuted, setIsMuted] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [history, setHistory] = useState([]);

  const containerRef = useRef(null);
  const prevStateRef = useRef(voiceState);
  const analyserRef = useRef(null);
  const animLevelRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    setVoiceState(initialMode);
    setTranscript('');
    setPartialTranscript('');
    setBrainText('');
    setErrorMessage('');
    setIsMuted(false);
    setAudioLevel(0);
  }, [open, initialMode]);

  useEffect(() => {
    const prev = prevStateRef.current;
    prevStateRef.current = voiceState;
    if (prev === voiceState) return;

    if (prev === 'listening' && voiceState === 'processing') {
      triggerHaptic(50);
    } else if (voiceState === 'error') {
      triggerHaptic([30, 30, 30]);
    }
  }, [voiceState]);

  useEffect(() => {
    if (!open) return;
    // PairShell exposes subscribeFrame (not onFrame — Subagent C's
    // JSDoc guessed wrong). Same silent-noop bug as the sendEnvelope
    // fix above. Prefer subscribeFrame; fall through to onFrame only
    // for test harnesses that inject it.
    const subscribe = shell?.subscribeFrame || shell?.onFrame;
    if (typeof subscribe !== 'function') return;

    const unsub = subscribe((frame) => {
      const type = frame?.type || '';
      const payload = frame?.payload || {};

      if (type === 'voice_state') {
        const s = payload.state;
        if (VOICE_STATES.includes(s)) {
          setVoiceState(s);
          if (s === 'error') {
            setErrorMessage(payload.message || 'An error occurred');
          }
        }
      } else if (type === 'transcript') {
        if (payload.is_final) {
          setTranscript(payload.text || '');
          setPartialTranscript('');
          setHistory((h) => [...h, { role: 'user', text: payload.text || '' }]);
        } else {
          setPartialTranscript(payload.text || '');
        }
      } else if (type === 'chat_response') {
        setBrainText(payload.text || '');
        setHistory((h) => [...h, { role: 'assistant', text: payload.text || '' }]);
      } else if (type === 'tts_chunk') {
        if (voiceState !== 'speaking') setVoiceState('speaking');
      } else if (type === 'voice_vad') {
        if (payload.speaking && voiceState !== 'listening') {
          setVoiceState('listening');
        }
      } else if (type === 'voice_error') {
        setVoiceState('error');
        setErrorMessage(payload.message || 'Voice session failed');
      }
    });

    return unsub;
  }, [open, shell, voiceState]);

  useEffect(() => {
    if (!open) return;

    // Critical iOS Safari fix: do NOT open a second getUserMedia here.
    // BrowserNode already owns the mic via VoicePanel.handleOpen's
    // startMic() call. Safari allows multiple getUserMedia streams
    // from the same origin, BUT the cleanup path `track.stop()` on
    // THIS stream's shared track can kill BrowserNode's track too
    // (depending on iOS version) — which silently breaks audio
    // streaming the moment VoiceFullscreen remounts.
    //
    // Instead, reuse BrowserNode's existing MediaStream if available
    // (stored at shell.node._mediaStream after startMic runs). If the
    // stream isn't ready yet (race), skip the analyser gracefully —
    // the orb still renders from voice_vad frames the brain emits.
    let ctx = null;

    const sharedStream = shell?.node?._mediaStream;
    if (!sharedStream) {
      // No BrowserNode stream yet — orb will update from voice_vad
      // frames instead. Don't open our own getUserMedia.
      return undefined;
    }

    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {});
      }
      const source = ctx.createMediaStreamSource(sharedStream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;

      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        if (!analyserRef.current) return;
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        const avg = sum / dataArray.length / 255;
        setAudioLevel(avg);
        animLevelRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      // Analyser is best-effort for the orb visual — voice data
      // still flows through BrowserNode's mic → WS pipeline.
    }

    return () => {
      analyserRef.current = null;
      if (animLevelRef.current) cancelAnimationFrame(animLevelRef.current);
      // Do NOT stop sharedStream tracks — they belong to BrowserNode.
      if (ctx) ctx.close().catch(() => {});
    };
  }, [open, shell]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        handleClose();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  });

  useEffect(() => {
    if (open && containerRef.current) {
      containerRef.current.focus();
    }
  }, [open]);

  const sendEnvelope = useCallback(
    (type, payload = {}) => {
      // PairShell exposes sendFrame(type, payload). The original
      // Subagent C implementation referenced shell.send which doesn't
      // exist on the context, so interrupts + envelopes silently
      // no-opped in the live test. Prefer sendFrame; fall through
      // to shell.send only for off-shell test harnesses that mock it.
      if (typeof shell?.sendFrame === 'function') {
        shell.sendFrame(type, payload);
        return;
      }
      if (typeof shell?.send === 'function') shell.send(type, payload);
    },
    [shell],
  );

  const handleInterrupt = useCallback(() => {
    if (voiceState === 'speaking') {
      sendEnvelope('voice_interrupt', {});
      triggerHaptic(30);
    }
  }, [voiceState, sendEnvelope]);

  const handleMuteToggle = useCallback(() => {
    setIsMuted((m) => {
      const next = !m;
      sendEnvelope('voice_mute', { muted: next });
      return next;
    });
  }, [sendEnvelope]);

  const handleClose = useCallback(() => {
    sendEnvelope('voice_interrupt', {});
    if (onClose) onClose();
  }, [sendEnvelope, onClose]);

  const handleRetry = useCallback(() => {
    setVoiceState('idle');
    setErrorMessage('');
    sendEnvelope('voice_session_start', {});
  }, [sendEnvelope]);

  const handleKeyboard = useCallback(() => {
    if (onClose) onClose();
  }, [onClose]);

  if (!open) return null;

  const voiceMode = shell?.voice_config?.mode || '';

  // Portal to document.body so position:fixed actually covers the
  // viewport. Without this the modal is trapped inside the pair
  // shell's Glass pane — which has backdrop-filter, creating a
  // containing block that captures fixed-position descendants. That's
  // why the live test showed the voice UI "cut off" as a black
  // rectangle inside the tab area instead of a fullscreen takeover.
  if (typeof document === 'undefined') return null;

  return createPortal((
    <div
      ref={containerRef}
      role="dialog"
      aria-label="Voice agent"
      aria-modal="true"
      tabIndex={-1}
      data-testid="voice-fullscreen"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: '#0a0a0f',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'space-between',
        color: '#fff',
        fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif',
        overflow: 'hidden',
      }}
    >
      {/* Provider badge */}
      {voiceMode && (
        <div
          data-testid="provider-badge"
          style={{
            position: 'absolute',
            top: 16,
            left: 16,
            fontSize: 12,
            opacity: 0.6,
            background: 'rgba(255,255,255,0.08)',
            padding: '4px 10px',
            borderRadius: 12,
          }}
        >
          {providerLabel(voiceMode)}
        </div>
      )}

      {/* Transcript area */}
      <div
        style={{
          flex: '0 0 auto',
          width: '100%',
          padding: '60px 24px 16px',
          textAlign: 'center',
          minHeight: 80,
        }}
      >
        {partialTranscript && (
          <p data-testid="partial-transcript" style={{ opacity: 0.7, fontSize: 16, margin: 0 }}>
            {partialTranscript}
          </p>
        )}
        {transcript && (
          <p data-testid="final-transcript" style={{ fontSize: 18, margin: '8px 0 0' }}>
            {transcript}
          </p>
        )}
        {voiceState === 'processing' && (
          <p style={{ opacity: 0.5, fontSize: 14, margin: '8px 0 0' }}>
            Brain is thinking…
          </p>
        )}
      </div>

      {/* Orb (tap to interrupt) */}
      <div
        data-testid="orb-container"
        onClick={handleInterrupt}
        style={{
          flex: '1 1 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '100%',
          cursor: voiceState === 'speaking' ? 'pointer' : 'default',
          opacity: isMuted ? 0.4 : 1,
          transition: 'opacity 0.3s',
        }}
      >
        <div style={{ width: '60vmin', height: '60vmin', maxWidth: 360, maxHeight: 360 }}>
          <VoiceOrb state={voiceState} audioLevel={audioLevel} />
        </div>
      </div>

      {/* Brain response text */}
      {brainText && voiceState === 'speaking' && (
        <div
          data-testid="brain-text"
          style={{
            padding: '0 24px 8px',
            fontSize: 15,
            opacity: 0.8,
            textAlign: 'center',
            maxHeight: 120,
            overflow: 'auto',
          }}
        >
          {brainText}
        </div>
      )}

      {/* Error surface */}
      {voiceState === 'error' && (
        <div data-testid="error-surface" style={{ textAlign: 'center', padding: '0 24px 16px' }}>
          <p style={{ color: '#ef4444', fontSize: 15, margin: '0 0 12px' }}>
            {errorMessage || 'An error occurred'}
          </p>
          <button
            data-testid="retry-button"
            onClick={handleRetry}
            style={{
              background: 'rgba(255,255,255,0.12)',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              padding: '10px 28px',
              fontSize: 15,
              cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Idle hint */}
      {voiceState === 'idle' && (
        <p style={{ opacity: 0.4, fontSize: 14, margin: 0, paddingBottom: 8 }}>Tap to speak</p>
      )}

      {/* Bottom controls */}
      <div
        style={{
          flex: '0 0 auto',
          display: 'flex',
          gap: 32,
          padding: '16px 0 40px',
          justifyContent: 'center',
          alignItems: 'center',
        }}
      >
        <button
          data-testid="mute-button"
          onClick={handleMuteToggle}
          aria-label={isMuted ? 'Unmute microphone' : 'Mute microphone'}
          aria-pressed={isMuted}
          style={{
            background: isMuted ? 'rgba(239,68,68,0.3)' : 'rgba(255,255,255,0.1)',
            color: '#fff',
            border: 'none',
            borderRadius: '50%',
            width: 52,
            height: 52,
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {isMuted ? '🔇' : '🎤'}
        </button>

        <button
          data-testid="keyboard-button"
          onClick={handleKeyboard}
          aria-label="Switch to keyboard"
          style={{
            background: 'rgba(255,255,255,0.1)',
            color: '#fff',
            border: 'none',
            borderRadius: '50%',
            width: 52,
            height: 52,
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          ⌨
        </button>

        <button
          data-testid="close-button"
          onClick={handleClose}
          aria-label="Close voice session"
          style={{
            background: 'rgba(239,68,68,0.25)',
            color: '#fff',
            border: 'none',
            borderRadius: '50%',
            width: 52,
            height: 52,
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          ✕
        </button>
      </div>
    </div>
  ), document.body);
}

export default VoiceFullscreen;
