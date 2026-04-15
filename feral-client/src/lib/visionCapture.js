const CAPTURE_WIDTH = 640;
const CAPTURE_HEIGHT = 480;
const JPEG_QUALITY = 0.6;
const DEFAULT_FPS = 1;

export class VisionCapture {
  constructor(ws, fps = DEFAULT_FPS) {
    this._ws = ws;
    this._fps = fps;
    this._active = false;
    this._stream = null;
    this._video = null;
    this._canvas = null;
    this._ctx = null;
    this._timer = null;
  }

  get active() {
    return this._active;
  }

  get stream() {
    return this._stream;
  }

  async start() {
    this._stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: CAPTURE_WIDTH }, height: { ideal: CAPTURE_HEIGHT }, facingMode: 'environment' },
    });

    this._video = document.createElement('video');
    this._video.srcObject = this._stream;
    this._video.playsInline = true;
    await this._video.play();

    this._canvas = document.createElement('canvas');
    this._canvas.width = CAPTURE_WIDTH;
    this._canvas.height = CAPTURE_HEIGHT;
    this._ctx = this._canvas.getContext('2d');

    this._active = true;
    this._timer = setInterval(() => this._captureFrame(), 1000 / this._fps);
  }

  stop() {
    this._active = false;
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    if (this._stream) {
      this._stream.getTracks().forEach(t => t.stop());
      this._stream = null;
    }
    if (this._video) {
      this._video.pause();
      this._video.srcObject = null;
      this._video = null;
    }
  }

  _captureFrame() {
    if (!this._active || !this._video || !this._ctx || !this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    this._ctx.drawImage(this._video, 0, 0, CAPTURE_WIDTH, CAPTURE_HEIGHT);
    const dataUrl = this._canvas.toDataURL('image/jpeg', JPEG_QUALITY);
    const b64 = dataUrl.split(',')[1];
    if (!b64) return;
    this._ws.send(JSON.stringify({
      hop: 'client',
      type: 'vision_frame',
      payload: {
        data_b64: b64,
        encoding: 'jpeg',
        width: CAPTURE_WIDTH,
        height: CAPTURE_HEIGHT,
        timestamp: Date.now() / 1000,
      },
    }));
  }
}
