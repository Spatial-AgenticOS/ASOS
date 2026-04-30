import { useCallback, useEffect, useRef, useState } from 'react';

const ERROR_MESSAGES = {
  'no-speech': 'No speech detected. Please try again.',
  'aborted': 'Speech recognition was aborted.',
  'audio-capture': 'No microphone detected. Check your audio input.',
  'network': 'Network error during speech recognition.',
  'not-allowed': 'Microphone permission denied. Allow access in browser settings.',
  'service-not-allowed': 'Speech recognition service not allowed.',
  'bad-grammar': 'Grammar error in speech recognition.',
  'language-not-supported': 'Language not supported for speech recognition.',
};

function getSpeechRecognition() {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

/**
 * iOS Web Speech API wrapper. Uses webkitSpeechRecognition (Safari/Chrome)
 * with graceful fallback when unsupported.
 */
export function useWebSpeech({
  continuous = false,
  interimResults = true,
  lang = 'en-US',
} = {}) {
  const SpeechRecognition = getSpeechRecognition();
  const supported = !!SpeechRecognition;

  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [error, setError] = useState(null);
  const recognitionRef = useRef(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch { /* noop */ }
        recognitionRef.current = null;
      }
    };
  }, []);

  const start = useCallback(() => {
    if (!SpeechRecognition) return;
    if (recognitionRef.current) return;

    setError(null);
    const recognition = new SpeechRecognition();
    recognition.continuous = continuous;
    recognition.interimResults = interimResults;
    recognition.lang = lang;
    recognitionRef.current = recognition;

    recognition.onstart = () => {
      if (mountedRef.current) setListening(true);
    };

    recognition.onresult = (event) => {
      if (!mountedRef.current) return;
      let final = '';
      let interim = '';
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          final += result[0].transcript;
        } else {
          interim += result[0].transcript;
        }
      }
      if (final) setTranscript(final);
      setInterimTranscript(interim);
    };

    recognition.onerror = (event) => {
      if (!mountedRef.current) return;
      const code = event.error || 'unknown';
      setError({
        code,
        message: ERROR_MESSAGES[code] || `Speech recognition error: ${code}`,
      });
      if (code === 'not-allowed' || code === 'service-not-allowed') {
        recognitionRef.current = null;
        setListening(false);
      }
    };

    recognition.onend = () => {
      if (!mountedRef.current) return;
      recognitionRef.current = null;
      setListening(false);
    };

    try {
      recognition.start();
    } catch (e) {
      recognitionRef.current = null;
      setError({ code: 'start-failed', message: e.message || 'Failed to start speech recognition' });
    }
  }, [SpeechRecognition, continuous, interimResults, lang]);

  const stop = useCallback(() => {
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* noop */ }
    }
  }, []);

  const reset = useCallback(() => {
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch { /* noop */ }
      recognitionRef.current = null;
    }
    setListening(false);
    setTranscript('');
    setInterimTranscript('');
    setError(null);
  }, []);

  return {
    supported,
    listening,
    transcript,
    interimTranscript,
    start,
    stop,
    reset,
    error,
  };
}

export default useWebSpeech;
