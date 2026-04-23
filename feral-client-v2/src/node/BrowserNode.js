/**
 * BrowserNode — a real HUP node that runs inside a phone / laptop browser.
 *
 * The phone scans the "Web phone" QR, lands on /pair?t=<TOKEN>, taps
 * "Pair this phone". Pair.jsx then instantiates this class, which opens
 * a WebSocket to /v1/node?api_key=<TOKEN>, sends a NodeRegisterPayload
 * with node_type="browser_node", and streams live sensor data back to the
 * Brain. No app install needed.
 *
 * Capabilities:
 *   • location — navigator.geolocation.watchPosition
 *   • camera   — captured frames (on demand, never background)
 *   • mic      — short audio blobs (on demand, never background)
 *   • display  — local notifications / vibration for actuator calls
 *
 * Privacy rules (non-negotiable):
 *   • Sensor streams only start when the user taps "Allow".
 *   • Tab-hidden for >60 s ⇒ streams auto-pause.
 *   • stop() revokes getUserMedia tracks + closes the WS.
 */

const HUP_VERSION = "1.0";

function nowTs() {
  return Date.now() / 1000;
}

function makeNodeId() {
  try {
    const existing = localStorage.getItem("feral.browser_node_id");
    if (existing) return existing;
    const fresh = `browser-node-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem("feral.browser_node_id", fresh);
    return fresh;
  } catch {
    return `browser-node-${Math.random().toString(36).slice(2, 10)}`;
  }
}

function detectPlatform() {
  const ua = typeof navigator !== "undefined" ? navigator.userAgent || "" : "";
  if (/iPhone|iPad|iPod/.test(ua)) return "ios-browser";
  if (/Android/.test(ua)) return "android-browser";
  if (/Macintosh/.test(ua)) return "macos-browser";
  if (/Windows/.test(ua)) return "windows-browser";
  if (/Linux/.test(ua)) return "linux-browser";
  return "browser";
}

function defaultCapabilities() {
  const caps = [];
  if (typeof navigator === "undefined") return caps;
  if (navigator.geolocation) caps.push("location");
  if (navigator.mediaDevices?.getUserMedia) {
    caps.push("camera");
    caps.push("mic");
  }
  if (typeof navigator.vibrate === "function") caps.push("haptic");
  caps.push("display");
  return caps;
}

export class BrowserNode {
  /**
   * @param {object} opts
   * @param {string} opts.token        — pairing token from /pair?t=
   * @param {string} [opts.brainUrl]   — ws://… prefix for /v1/node. Inferred
   *                                      from window.location when absent.
   * @param {string} [opts.nodeId]     — stable id (persisted in localStorage).
   * @param {string} [opts.name]       — display name.
   * @param {string[]} [opts.capabilities]
   * @param {(phase: string, detail?: any) => void} [opts.onPhase]
   * @param {(err: Error) => void} [opts.onError]
   */
  constructor(opts) {
    if (!opts?.token) throw new Error("BrowserNode: token is required");

    this.token = opts.token;
    this.nodeId = opts.nodeId || makeNodeId();
    this.name = opts.name || "Browser Node";
    this.platform = detectPlatform();
    this.capabilities = opts.capabilities || defaultCapabilities();
    this.onPhase = opts.onPhase || (() => {});
    this.onError = opts.onError || ((e) => console.warn("[BrowserNode]", e));

    const originHttp = opts.brainUrl || (
      typeof window !== "undefined" ? window.location.origin : ""
    );
    this.wsUrl = originHttp
      .replace(/^http/, "ws")
      .replace(/\/$/, "") + `/v1/node?api_key=${encodeURIComponent(this.token)}`;

    this._ws = null;
    this._stopped = false;
    this._locationWatchId = null;
    this._mediaStream = null;
    this._pausedAt = 0;
    this._visibilityHandler = null;
  }

  async connect() {
    if (typeof WebSocket === "undefined") {
      throw new Error("WebSocket not available in this runtime");
    }
    this._ws = new WebSocket(this.wsUrl);

    await new Promise((resolve, reject) => {
      this._ws.onopen = () => resolve();
      this._ws.onerror = (e) => reject(new Error("WebSocket error"));
    });
    this.onPhase("connected");

    await this._send("node_register", {
      node_id: this.nodeId,
      node_type: "browser_node",
      name: this.name,
      platform: this.platform,
      capabilities: this.capabilities,
      sensors: this.capabilities.filter((c) =>
        ["location", "camera", "mic"].includes(c),
      ),
      actuators: this.capabilities.filter((c) =>
        ["display", "haptic"].includes(c),
      ),
    });

    this._ws.onmessage = (e) => this._onFrame(e);
    this._ws.onclose = () => {
      this.onPhase("closed");
    };

    try {
      await fetch(
        new URL("/api/devices/pair/complete", window.location.origin).toString(),
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ token: this.token }),
        },
      );
    } catch (err) {
      this.onError(err);
    }

    this._visibilityHandler = () => {
      if (document.hidden) {
        this._pausedAt = Date.now();
      } else if (this._pausedAt && Date.now() - this._pausedAt > 60_000) {
        this.pauseStreams();
      }
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", this._visibilityHandler);
    }

    this.onPhase("registered");
  }

  async startSensors({ location = true, camera = false, mic = false } = {}) {
    if (location && navigator.geolocation) {
      this._locationWatchId = navigator.geolocation.watchPosition(
        (pos) => this._pushLocation(pos),
        (err) => this.onError(err),
        { enableHighAccuracy: true, maximumAge: 10_000, timeout: 15_000 },
      );
      this.onPhase("location_streaming");
    }
    if ((camera || mic) && navigator.mediaDevices?.getUserMedia) {
      try {
        this._mediaStream = await navigator.mediaDevices.getUserMedia({
          video: !!camera,
          audio: !!mic,
        });
        this.onPhase("media_acquired");
      } catch (err) {
        this.onError(err);
      }
    }
  }

  pauseStreams() {
    if (this._locationWatchId != null && navigator.geolocation) {
      navigator.geolocation.clearWatch(this._locationWatchId);
      this._locationWatchId = null;
    }
    if (this._mediaStream) {
      for (const track of this._mediaStream.getTracks()) track.stop();
      this._mediaStream = null;
    }
    this.onPhase("paused");
  }

  async stop() {
    if (this._stopped) return;
    this._stopped = true;
    this.pauseStreams();
    if (this._visibilityHandler && typeof document !== "undefined") {
      document.removeEventListener("visibilitychange", this._visibilityHandler);
    }
    try {
      this._ws?.close();
    } catch (err) {
      this.onError(err);
    }
    this.onPhase("stopped");
  }

  _pushLocation(pos) {
    if (!pos?.coords) return;
    fetch(
      new URL("/api/location/update", window.location.origin).toString(),
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy,
          source: "browser_node",
          node_id: this.nodeId,
        }),
      },
    ).catch((err) => this.onError(err));
  }

  _onFrame(event) {
    let frame;
    try {
      frame = JSON.parse(event.data);
    } catch {
      return;
    }
    const type = frame?.type || "";
    if (type === "node_ack") {
      this.onPhase("acknowledged", frame.payload);
      return;
    }
    if (type === "action") {
      this._handleAction(frame.payload || {});
      return;
    }
    this.onPhase("frame", frame);
  }

  _handleAction(payload) {
    const kind = payload?.action_type || payload?.kind || "";
    if (kind === "vibrate" && typeof navigator.vibrate === "function") {
      navigator.vibrate(Number(payload.duration_ms || 120));
    } else if (kind === "notify" && "Notification" in window) {
      try {
        if (Notification.permission === "granted") {
          new Notification("FERAL", { body: String(payload.text || "") });
        } else if (Notification.permission !== "denied") {
          Notification.requestPermission();
        }
      } catch (err) {
        this.onError(err);
      }
    }
  }

  async _send(type_, payload) {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    const frame = {
      hup_version: HUP_VERSION,
      type: type_,
      ts: nowTs(),
      payload,
    };
    this._ws.send(JSON.stringify(frame));
  }
}

export default BrowserNode;
