/**
 * Realtime Voice Engine — PCM16 capture & playback for OpenAI Realtime API
 *
 * Captures microphone audio as raw PCM16 at 24kHz, sends base64 chunks over WebSocket.
 * Receives PCM16 audio back and plays it through an AudioContext.
 */

const TARGET_SAMPLE_RATE = 24000;

export class RealtimeVoiceEngine {
  constructor(ws) {
    this._ws = ws;
    this._audioCtx = null;
    this._stream = null;
    this._processor = null;
    this._source = null;
    this._playbackCtx = null;
    this._playbackQueue = [];
    this._isPlaying = false;
    this._active = false;
  }

  get active() { return this._active; }

  async start() {
    this._active = true;

    this._ws.send(JSON.stringify({
      hop: "client",
      type: "voice_config",
      payload: { mode: "realtime", supports_realtime: true }
    }));

    this._stream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: TARGET_SAMPLE_RATE, channelCount: 1, echoCancellation: true, noiseSuppression: true }
    });

    this._audioCtx = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
    this._source = this._audioCtx.createMediaStreamSource(this._stream);

    this._processor = this._audioCtx.createScriptProcessor(4096, 1, 1);
    this._processor.onaudioprocess = (e) => {
      if (!this._active) return;
      const float32 = e.inputBuffer.getChannelData(0);
      const pcm16 = this._float32ToPCM16(float32);
      const b64 = this._arrayBufferToBase64(pcm16.buffer);

      if (this._ws.readyState === WebSocket.OPEN) {
        this._ws.send(JSON.stringify({
          hop: "client",
          type: "audio_chunk",
          payload: {
            encoding: "pcm16",
            sample_rate: TARGET_SAMPLE_RATE,
            channels: 1,
            chunk_index: 0,
            is_final: false,
            data_b64: b64,
          }
        }));
      }
    };

    this._source.connect(this._processor);
    this._processor.connect(this._audioCtx.destination);

    this._playbackCtx = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
  }

  stop() {
    this._active = false;

    if (this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify({
        hop: "client",
        type: "voice_config",
        payload: { mode: "disabled" }
      }));
    }

    if (this._processor) {
      this._processor.disconnect();
      this._processor = null;
    }
    if (this._source) {
      this._source.disconnect();
      this._source = null;
    }
    if (this._stream) {
      this._stream.getTracks().forEach(t => t.stop());
      this._stream = null;
    }
    if (this._audioCtx) {
      this._audioCtx.close().catch(() => {});
      this._audioCtx = null;
    }
    if (this._playbackCtx) {
      this._playbackCtx.close().catch(() => {});
      this._playbackCtx = null;
    }
    this._playbackQueue = [];
    this._isPlaying = false;
  }

  handleAudioResponse(payload) {
    if (!payload.data_b64 || payload.is_final) return;

    try {
      const pcm16 = this._base64ToPCM16(payload.data_b64);
      const float32 = this._pcm16ToFloat32(pcm16);

      const buffer = this._playbackCtx.createBuffer(1, float32.length, TARGET_SAMPLE_RATE);
      buffer.getChannelData(0).set(float32);

      this._playbackQueue.push(buffer);
      if (!this._isPlaying) this._playNext();
    } catch (e) {
      console.error("Audio playback error:", e);
    }
  }

  _playNext() {
    if (this._playbackQueue.length === 0) {
      this._isPlaying = false;
      return;
    }
    this._isPlaying = true;
    const buffer = this._playbackQueue.shift();
    const source = this._playbackCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(this._playbackCtx.destination);
    source.onended = () => this._playNext();
    source.start();
  }

  _float32ToPCM16(float32) {
    const pcm16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return pcm16;
  }

  _pcm16ToFloat32(pcm16) {
    const float32 = new Float32Array(pcm16.length);
    for (let i = 0; i < pcm16.length; i++) {
      float32[i] = pcm16[i] / (pcm16[i] < 0 ? 0x8000 : 0x7FFF);
    }
    return float32;
  }

  _arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  _base64ToPCM16(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new Int16Array(bytes.buffer);
  }
}
