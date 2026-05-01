/**
 * VoicePanel — the "Voice" tab content on the phone.
 *
 * Shows a prominent "Start voice" button that opens VoiceFullscreen,
 * plus a scrollable session transcript history below.
 *
 * Post-PR #61 live test fix: the earlier version called
 * `shell.send(type, payload)` which doesn't exist on the PairShell
 * context (the real API is `shell.sendFrame(type, payload)`). That's
 * why the live test showed the voice tab with a cut-off black box and
 * no audio — the voice_session_start envelope never left the phone,
 * and the microphone was never started. This rewrite uses sendFrame
 * AND explicitly calls shell.node.startMic() so audio actually flows.
 */
import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { VoiceFullscreen } from './VoiceFullscreen';

// Same module-level cache pattern as ChatPanel — preserves voice
// transcript history when the user switches tabs and returns to
// Voice (React Router unmounts the panel otherwise).
const _voiceHistory = new Map(); // deviceId → history[]

function extractBrainLine(frame) {
  const p = frame?.payload || {};
  if (typeof p.transcript === 'string' && p.transcript.trim()) return p.transcript.trim();
  if (typeof p.text === 'string' && p.text.trim()) return p.text.trim();
  if (typeof p.content === 'string' && p.content.trim()) return p.content.trim();
  return '';
}

export default function VoicePanel({ shell: shellProp }) {
  const outletShell = useOutletContext();
  const shell = shellProp || outletShell || {};
  const [fullscreenOpen, setFullscreenOpen] = useState(false);
  const cacheKey = shell?.deviceId || 'anonymous';
  const [history, setHistoryRaw] = useState(() => _voiceHistory.get(cacheKey) || []);
  const setHistory = useCallback((updater) => {
    setHistoryRaw((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      _voiceHistory.set(cacheKey, next);
      return next;
    });
  }, [cacheKey]);

  // Collect transcript lines from chat_response / voice transcripts
  // so the tab shows a persistent session log even when fullscreen
  // is closed.
  useEffect(() => {
    if (typeof shell?.subscribeFrame !== 'function') return undefined;
    return shell.subscribeFrame((frame) => {
      if (frame?.type !== 'chat_response' && frame?.type !== 'transcript') return;
      const text = extractBrainLine(frame);
      if (!text) return;
      setHistory((prev) => [
        { id: `h_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`, role: 'assistant', text },
        ...prev,
      ].slice(0, 40));
    });
  }, [shell]);

  const handleOpen = useCallback(async () => {
    // 1. Send voice_session_start envelope via the CORRECT shell API
    //    (sendFrame, not send). Brain allocates a voice session id and
    //    routes audio frames through voice_router.open_session(mode).
    if (typeof shell?.sendFrame === 'function') {
      const mode = shell?.voice_config?.mode || 'openai_realtime';
      const sessionId = `voice-${shell?.deviceId || 'session'}`;
      shell.sendFrame('voice_session_start', {
        session_id: sessionId,
        stream_id: sessionId,
        voice_mode: mode,
        sample_rate: 24000,
        channels: 1,
        language_hint: 'en-US',
        interrupt_policy: 'barge_in',
      });
    }

    // 2. Actually start the microphone so PCM16 chunks stream out
    //    over the WS. Without this the brain sits waiting for audio
    //    and the orb stays in 'idle' forever.
    try {
      if (shell?.node?.startMic) await shell.node.startMic();
    } catch (err) {
      console.warn('[VoicePanel] startMic failed', err);
    }

    setFullscreenOpen(true);
  }, [shell]);

  const handleClose = useCallback(async () => {
    // Stop the mic so the iOS recording indicator goes away + tear
    // down the voice session cleanly.
    try {
      if (shell?.node?.stopMic) await shell.node.stopMic();
    } catch {
      // Ignore — the session is ending anyway.
    }
    if (typeof shell?.sendFrame === 'function') {
      shell.sendFrame('voice_interrupt', {
        stream_id: `voice-${shell?.deviceId || 'session'}`,
        reason: 'user_close',
      });
    }
    setFullscreenOpen(false);
  }, [shell]);

  return (
    <div className="phone-voice-panel" data-testid="voice-panel">
      <button
        type="button"
        className="phone-voice-cta"
        data-testid="start-voice-button"
        onClick={handleOpen}
      >
        Start voice
      </button>

      <div className="phone-voice-history" data-testid="voice-history">
        {history.length === 0 ? (
          <div className="phone-voice-history-empty">No voice turns yet.</div>
        ) : (
          history.map((entry) => (
            <div key={entry.id} style={{ padding: '6px 8px', fontSize: 14 }}>
              <span style={{ opacity: 0.5, marginRight: 8 }}>
                {entry.role === 'user' ? 'You:' : 'Brain:'}
              </span>
              {entry.text}
            </div>
          ))
        )}
      </div>

      {fullscreenOpen && (
        <VoiceFullscreen
          open={fullscreenOpen}
          onClose={handleClose}
          initialMode="listening"
          shell={shell}
        />
      )}
    </div>
  );
}
