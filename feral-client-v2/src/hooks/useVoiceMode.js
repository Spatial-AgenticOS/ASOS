import { useCallback, useEffect, useRef, useState } from 'react';
import { RealtimeVoiceEngine } from '../lib/voiceRealtime';
import { apiJson } from '../lib/api';
import { useFeralSocket } from './useFeralSocket';

/**
 * useVoiceMode — single source of truth for v2's voice state.
 *
 * Shape:
 *   state: 'off' | 'starting' | 'active' | 'reconnecting' | 'degraded' | 'ended'
 *   provider: 'openai' | 'gemini' | 'local-whisper' | null
 *   transcript: string (latest user utterance snippet)
 *
 * The Menubar's voice button toggles start/stop. VoiceOverlay reads the
 * state to drive the transition + Orb takeover.
 */
const STORAGE_KEY = 'feral_v2_voice_provider';

export function useVoiceMode() {
  const socket = useFeralSocket();
  const engineRef = useRef(null);
  const [state, setState] = useState('off');
  const [provider, setProvider] = useState(null);
  const [transcript, setTranscript] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const config = await apiJson('/api/config');
        const cfgProvider =
          config?.features?.voice_provider ||
          config?.voice_provider ||
          (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY)) ||
          'openai';
        setProvider(cfgProvider);
      } catch {
        setProvider('openai');
      }
    })();
  }, []);

  const start = useCallback(async () => {
    if (state !== 'off' && state !== 'ended') return;
    if (!socket.ws || socket.ws.readyState !== 1) {
      setState('degraded');
      return;
    }
    setState('starting');
    setTranscript('');
    try {
      const engine = new RealtimeVoiceEngine(socket.ws, {
        onStateChange: (s) => setState(s === 'active' ? 'active' : s),
        onTranscript: (text) => setTranscript(text || ''),
        onError: () => {},
      });
      engineRef.current = engine;
      await engine.start(provider || 'openai');
      setState('active');
    } catch (err) {
      setState('ended');
      engineRef.current = null;
      // eslint-disable-next-line no-console
      console.error('Voice start failed:', err);
    }
  }, [socket, state, provider]);

  const stop = useCallback(() => {
    if (engineRef.current) {
      try { engineRef.current.stop(); } catch {}
      engineRef.current = null;
    }
    setState('ended');
    setTimeout(() => setState('off'), 220);
  }, []);

  const toggle = useCallback(() => {
    if (state === 'off' || state === 'ended') return start();
    return stop();
  }, [state, start, stop]);

  return {
    state,
    provider,
    setProvider,
    transcript,
    active: state === 'active' || state === 'starting' || state === 'reconnecting',
    start,
    stop,
    toggle,
  };
}
