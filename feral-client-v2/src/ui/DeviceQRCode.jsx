import React, { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';

/**
 * DeviceQRCode — renders the PNG returned by GET /api/devices/pair/qr.
 * Falls back to a copy-the-URL view if the endpoint returns JSON or an
 * error (some Brain builds expose a text pairing link instead of a PNG).
 *
 * When a `value` prop is supplied, the component skips the Brain roundtrip
 * and simply renders a text-link view of that string (the phone-camera-share
 * flow uses this path so the modal can show a ready-to-open URL without
 * re-pairing).
 */
export default function DeviceQRCode({ size = 220, value = null, mode = 'web', onTokenIssued = null }) {
  const [imgUrl, setImgUrl] = useState(null);
  const [textLink, setTextLink] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (value) {
      setTextLink(value);
      return undefined;
    }
    let cancelled = false;
    let createdUrl = null;
    (async () => {
      try {
        const r = await apiFetch(`/api/devices/pair/qr?mode=${encodeURIComponent(mode)}`);
        if (!r.ok) throw new Error(`${r.status}`);
        const headerDeviceId = r.headers.get('X-Feral-Device-Id');
        if (headerDeviceId) onTokenIssued?.(headerDeviceId);
        const ct = r.headers.get('Content-Type') || '';
        if (ct.includes('image/')) {
          const blob = await r.blob();
          createdUrl = URL.createObjectURL(blob);
          if (!cancelled) setImgUrl(createdUrl);
        } else if (ct.includes('application/json')) {
          const data = await r.json();
          const bodyDeviceId = data?.pairing_info?.device_id || data?.device_id;
          if (bodyDeviceId) onTokenIssued?.(bodyDeviceId);
          if (!cancelled) {
            if (data?.qr_png_b64) {
              setImgUrl(`data:image/png;base64,${data.qr_png_b64}`);
            } else if (data?.pair_url || data?.url) {
              setTextLink(data.pair_url || data.url);
            } else {
              setTextLink(JSON.stringify(data));
            }
          }
        } else {
          const txt = await r.text();
          if (!cancelled) setTextLink(txt);
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [value, mode, onTokenIssued]);

  if (error) {
    return (
      <div className="v2-qr v2-qr--error" style={{ width: size, height: size }}>
        QR unavailable — {error}
      </div>
    );
  }
  if (imgUrl) {
    return (
      <img
        src={imgUrl}
        alt="Device pairing QR code"
        className="v2-qr"
        width={size}
        height={size}
      />
    );
  }
  if (textLink) {
    return (
      <div className="v2-qr v2-qr--text" style={{ maxWidth: size * 2 }}>
        <div className="v2-p v2-p--muted">Scan unavailable — open this link on your device:</div>
        <code className="v2-code-inline">{textLink}</code>
      </div>
    );
  }
  return <div className="v2-qr v2-qr--loading" style={{ width: size, height: size }}>…</div>;
}
