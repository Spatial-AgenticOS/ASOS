import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, waitFor, act } from '@testing-library/react';
import VisionAskPanel from '../../../pages/phone/VisionAskPanel';

const mockTrack = { stop: vi.fn(), kind: 'video' };
const mockStream = {
  getTracks: () => [mockTrack],
  getVideoTracks: () => [mockTrack],
  getAudioTracks: () => [],
};

function setupMediaDevices(shouldFail = false, failReason = 'NotAllowedError') {
  const getUserMedia = shouldFail
    ? vi.fn().mockRejectedValue(Object.assign(new Error('Permission denied'), { name: failReason }))
    : vi.fn().mockResolvedValue(mockStream);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true, writable: true,
    value: { getUserMedia },
  });
  return getUserMedia;
}

function patchVideoElements() {
  const origCreateElement = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation((tag, opts) => {
    const el = origCreateElement(tag, opts);
    if (tag === 'video') {
      Object.defineProperty(el, 'videoWidth', { get: () => 640, configurable: true });
      Object.defineProperty(el, 'videoHeight', { get: () => 480, configurable: true });
    }
    if (tag === 'canvas') {
      el.getContext = vi.fn(() => ({ drawImage: vi.fn() }));
      el.toDataURL = vi.fn(() => 'data:image/jpeg;base64,AAAA');
    }
    return el;
  });
}

describe('VisionAskPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTrack.stop.mockClear();
    window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    window.HTMLMediaElement.prototype.pause = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    try { delete navigator.mediaDevices; } catch { /* noop */ }
  });

  it('renders the panel with camera preview area', () => {
    setupMediaDevices();
    const { getByTestId } = render(<VisionAskPanel />);
    expect(getByTestId('phone-vision-panel')).toBeTruthy();
    expect(getByTestId('camera-preview')).toBeTruthy();
  });

  it('requests camera with facingMode environment on mount', async () => {
    const getUserMedia = setupMediaDevices();
    render(<VisionAskPanel />);
    await waitFor(() => {
      expect(getUserMedia).toHaveBeenCalledWith({ video: { facingMode: 'environment' } });
    });
  });

  it('camera permission denied shows error and grant button', async () => {
    setupMediaDevices(true, 'NotAllowedError');
    const { findByTestId } = render(<VisionAskPanel />);
    expect(await findByTestId('permission-denied')).toBeTruthy();
    expect(await findByTestId('grant-permission-btn')).toBeTruthy();
  });

  it('grant permission button retries getUserMedia', async () => {
    const getUserMedia = setupMediaDevices(true, 'NotAllowedError');
    const { findByTestId } = render(<VisionAskPanel />);
    getUserMedia.mockResolvedValueOnce(mockStream);
    fireEvent.click(await findByTestId('grant-permission-btn'));
    await waitFor(() => { expect(getUserMedia).toHaveBeenCalledTimes(2); });
  });

  it('capture creates a JPEG base64 thumbnail', async () => {
    setupMediaDevices();
    patchVideoElements();
    const { findByTestId, queryByTestId, getByTestId } = render(<VisionAskPanel />);
    await waitFor(() => expect(queryByTestId('capture-button')).toBeTruthy());
    const videoEl = getByTestId('camera-video');
    Object.defineProperty(videoEl, 'videoWidth', { get: () => 640, configurable: true });
    Object.defineProperty(videoEl, 'videoHeight', { get: () => 480, configurable: true });
    await act(async () => { fireEvent.click(await findByTestId('capture-button')); });
    await waitFor(() => expect(queryByTestId('captured-thumbnail')).toBeTruthy());
  });

  it('captured image shows question input and retake button', async () => {
    setupMediaDevices();
    patchVideoElements();
    const { findByTestId, queryByTestId, getByTestId } = render(<VisionAskPanel />);
    await waitFor(() => expect(queryByTestId('capture-button')).toBeTruthy());
    const videoEl = getByTestId('camera-video');
    Object.defineProperty(videoEl, 'videoWidth', { get: () => 640, configurable: true });
    Object.defineProperty(videoEl, 'videoHeight', { get: () => 480, configurable: true });
    await act(async () => { fireEvent.click(await findByTestId('capture-button')); });
    await waitFor(() => {
      expect(queryByTestId('question-input')).toBeTruthy();
      expect(queryByTestId('retake-button')).toBeTruthy();
    });
  });

  it('submit fires frame + chat_request envelopes in order', async () => {
    setupMediaDevices();
    patchVideoElements();
    const sendCalls = [];
    const shell = { send: vi.fn((env) => sendCalls.push(env)) };
    const { findByTestId, queryByTestId, getByTestId } = render(<VisionAskPanel shell={shell} sessionId="sess-123" />);
    await waitFor(() => expect(queryByTestId('capture-button')).toBeTruthy());
    const videoEl = getByTestId('camera-video');
    Object.defineProperty(videoEl, 'videoWidth', { get: () => 640, configurable: true });
    Object.defineProperty(videoEl, 'videoHeight', { get: () => 480, configurable: true });
    await act(async () => { fireEvent.click(await findByTestId('capture-button')); });
    await waitFor(() => expect(queryByTestId('question-input')).toBeTruthy());
    fireEvent.change(await findByTestId('question-input'), { target: { value: 'What is this?' } });
    await act(async () => { fireEvent.submit((await findByTestId('question-input')).closest('form')); });
    await waitFor(() => {
      expect(shell.send).toHaveBeenCalledTimes(2);
      expect(sendCalls[0].type).toBe('frame');
      expect(sendCalls[0].payload.data_b64).toBe('AAAA');
      expect(sendCalls[1].type).toBe('chat_request');
      expect(sendCalls[1].payload.text).toBe('What is this?');
      expect(sendCalls[1].payload.channel).toBe('vision');
      expect(sendCalls[1].payload.session_id).toBe('sess-123');
    });
  });

  it('response renders with thumbnail inline', async () => {
    setupMediaDevices();
    patchVideoElements();
    const shell = { send: vi.fn() };
    const { findByTestId, queryByTestId, getByTestId } = render(<VisionAskPanel shell={shell} sessionId="s1" />);
    await waitFor(() => expect(queryByTestId('capture-button')).toBeTruthy());
    const videoEl = getByTestId('camera-video');
    Object.defineProperty(videoEl, 'videoWidth', { get: () => 640, configurable: true });
    Object.defineProperty(videoEl, 'videoHeight', { get: () => 480, configurable: true });
    await act(async () => { fireEvent.click(await findByTestId('capture-button')); });
    await waitFor(() => expect(queryByTestId('question-input')).toBeTruthy());
    fireEvent.change(await findByTestId('question-input'), { target: { value: 'Describe' } });
    await act(async () => { fireEvent.submit((await findByTestId('question-input')).closest('form')); });
    await waitFor(() => {
      expect(queryByTestId('vision-response-item')).toBeTruthy();
      expect(queryByTestId('response-thumbnail')).toBeTruthy();
    });
  });

  it('retake clears captured image', async () => {
    setupMediaDevices();
    patchVideoElements();
    const { findByTestId, queryByTestId, getByTestId } = render(<VisionAskPanel />);
    await waitFor(() => expect(queryByTestId('capture-button')).toBeTruthy());
    const videoEl = getByTestId('camera-video');
    Object.defineProperty(videoEl, 'videoWidth', { get: () => 640, configurable: true });
    Object.defineProperty(videoEl, 'videoHeight', { get: () => 480, configurable: true });
    await act(async () => { fireEvent.click(await findByTestId('capture-button')); });
    await waitFor(() => expect(queryByTestId('retake-button')).toBeTruthy());
    fireEvent.click(await findByTestId('retake-button'));
    await waitFor(() => expect(queryByTestId('captured-thumbnail')).toBeNull());
  });

  it('generic camera error shows error message', async () => {
    setupMediaDevices(true, 'NotFoundError');
    const { findByTestId } = render(<VisionAskPanel />);
    expect(await findByTestId('camera-error')).toBeTruthy();
  });
});
