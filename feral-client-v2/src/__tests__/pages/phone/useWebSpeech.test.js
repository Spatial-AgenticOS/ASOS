import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWebSpeech } from '../../../hooks/useWebSpeech';

function createMockRecognition() {
  return {
    continuous: false,
    interimResults: true,
    lang: 'en-US',
    onstart: null,
    onresult: null,
    onerror: null,
    onend: null,
    start: vi.fn(),
    stop: vi.fn(),
    abort: vi.fn(),
  };
}

let mockInstance = null;

class MockSpeechRecognition {
  constructor() {
    mockInstance = createMockRecognition();
    Object.assign(this, mockInstance);
    return mockInstance;
  }
}

describe('useWebSpeech', () => {
  beforeEach(() => {
    mockInstance = null;
    window.webkitSpeechRecognition = MockSpeechRecognition;
  });

  afterEach(() => {
    delete window.webkitSpeechRecognition;
    delete window.SpeechRecognition;
    mockInstance = null;
  });

  it('reports supported=true when webkitSpeechRecognition exists', () => {
    const { result } = renderHook(() => useWebSpeech());
    expect(result.current.supported).toBe(true);
  });

  it('reports supported=false when no SpeechRecognition API exists', () => {
    delete window.webkitSpeechRecognition;
    delete window.SpeechRecognition;
    const { result } = renderHook(() => useWebSpeech());
    expect(result.current.supported).toBe(false);
  });

  it('starts listening and sets listening=true on start()', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    expect(mockInstance.start).toHaveBeenCalled();
    act(() => { mockInstance.onstart(); });
    expect(result.current.listening).toBe(true);
  });

  it('stops listening when stop() is called', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    act(() => { mockInstance.onstart(); });
    act(() => { result.current.stop(); });
    expect(mockInstance.stop).toHaveBeenCalled();
  });

  it('updates transcript on final result', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    act(() => { mockInstance.onstart(); });
    act(() => {
      mockInstance.onresult({
        results: [{ 0: { transcript: 'hello world' }, isFinal: true, length: 1 }],
        length: 1,
      });
    });
    expect(result.current.transcript).toBe('hello world');
  });

  it('updates interimTranscript on non-final result', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    act(() => { mockInstance.onstart(); });
    act(() => {
      mockInstance.onresult({
        results: [{ 0: { transcript: 'hel' }, isFinal: false, length: 1 }],
        length: 1,
      });
    });
    expect(result.current.interimTranscript).toBe('hel');
  });

  it('sets error on not-allowed error code', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    act(() => { mockInstance.onstart(); });
    act(() => { mockInstance.onerror({ error: 'not-allowed' }); });
    expect(result.current.error).toBeTruthy();
    expect(result.current.error.code).toBe('not-allowed');
    expect(result.current.error.message).toContain('permission denied');
  });

  it('sets error on no-speech error code', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    act(() => { mockInstance.onstart(); });
    act(() => { mockInstance.onerror({ error: 'no-speech' }); });
    expect(result.current.error.code).toBe('no-speech');
    expect(result.current.error.message).toContain('No speech detected');
  });

  it('sets error on network error code', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    act(() => { mockInstance.onstart(); });
    act(() => { mockInstance.onerror({ error: 'network' }); });
    expect(result.current.error.code).toBe('network');
    expect(result.current.error.message).toContain('Network error');
  });

  it('sets error on audio-capture error code', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    act(() => { mockInstance.onstart(); });
    act(() => { mockInstance.onerror({ error: 'audio-capture' }); });
    expect(result.current.error.code).toBe('audio-capture');
    expect(result.current.error.message).toContain('microphone');
  });

  it('reset() clears all state', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    act(() => { mockInstance.onstart(); });
    act(() => {
      mockInstance.onresult({
        results: [{ 0: { transcript: 'test' }, isFinal: true, length: 1 }],
        length: 1,
      });
    });
    expect(result.current.transcript).toBe('test');
    act(() => { result.current.reset(); });
    expect(result.current.listening).toBe(false);
    expect(result.current.transcript).toBe('');
    expect(result.current.interimTranscript).toBe('');
    expect(result.current.error).toBe(null);
  });

  it('sets listening=false when recognition ends naturally', () => {
    const { result } = renderHook(() => useWebSpeech());
    act(() => { result.current.start(); });
    act(() => { mockInstance.onstart(); });
    expect(result.current.listening).toBe(true);
    act(() => { mockInstance.onend(); });
    expect(result.current.listening).toBe(false);
  });

  it('passes custom lang, continuous, and interimResults to recognition', () => {
    const { result } = renderHook(() =>
      useWebSpeech({ continuous: true, interimResults: false, lang: 'fr-FR' })
    );
    act(() => { result.current.start(); });
    expect(mockInstance.continuous).toBe(true);
    expect(mockInstance.interimResults).toBe(false);
    expect(mockInstance.lang).toBe('fr-FR');
  });
});
