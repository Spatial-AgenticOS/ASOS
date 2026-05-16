/**
 * Shared `AudioContext` factory with user-gesture unlocking.
 *
 * Chrome and the other Web Audio implementations create every fresh
 * `AudioContext` in the `suspended` state. The context can only move
 * to `running` from inside a user-gesture stack (click / keydown /
 * touchstart). When `VoiceFullscreen` created its own AudioContext
 * inside an async playback queue, that gesture stack was already
 * gone — `resume()` silently failed and every PCM `start()` scheduled
 * audio that never played. Symptom: brain logs show `audio_response`
 * frames going out, browser stays silent.
 *
 * Fix (v2026.5.28): one shared, app-wide AudioContext that's resumed
 * on the very first user gesture anywhere in the app, then reused
 * for every playback site (voice overlay, future ambient audio cues,
 * etc.). `installAudioUnlock()` is called once from the bootstrap
 * path; consumers call `getSharedAudioContext()` to get a context
 * that is already `running` by the time they need it.
 *
 * Truthful failure: if Web Audio is not available (server-rendered
 * tree, ancient browser), the helpers return `null` and callers
 * fall through to their existing branchless silent path. We do not
 * pretend the context exists.
 */

let _sharedCtx = null;
let _unlockInstalled = false;

function _createCtx() {
  if (typeof window === 'undefined') return null;
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) return null;
  try {
    return new AudioCtx();
  } catch (_err) {
    return null;
  }
}

export function getSharedAudioContext() {
  if (_sharedCtx && _sharedCtx.state !== 'closed') return _sharedCtx;
  _sharedCtx = _createCtx();
  return _sharedCtx;
}

/**
 * Attempt to move the shared AudioContext to `running`. Safe to call
 * from any gesture handler. Returns a Promise that resolves to the
 * context (or `null` when Web Audio is unavailable).
 */
export async function unlockSharedAudioContext() {
  const ctx = getSharedAudioContext();
  if (!ctx) return null;
  if (ctx.state === 'suspended') {
    try {
      await ctx.resume();
    } catch (_err) {
      // iOS Safari rejects resume outside a fresh gesture. The next
      // gesture will retry via the installAudioUnlock listener.
    }
  }
  return ctx;
}

/**
 * Install a one-shot global listener that resumes the shared
 * AudioContext on the next user gesture anywhere in the document.
 * Subsequent gestures are no-ops. Safe to call repeatedly — only
 * the first call wires the listeners.
 */
export function installAudioUnlock() {
  if (_unlockInstalled) return;
  if (typeof document === 'undefined' || typeof window === 'undefined') return;
  _unlockInstalled = true;

  const handler = async () => {
    await unlockSharedAudioContext();
    // Detach so we don't keep firing on every click for the rest of
    // the session. If unlock failed (gesture was a touchend rather
    // than touchstart, etc.) we leave the handler attached so the
    // next gesture has another chance.
    if (_sharedCtx && _sharedCtx.state === 'running') {
      document.removeEventListener('click', handler, true);
      document.removeEventListener('touchstart', handler, true);
      document.removeEventListener('keydown', handler, true);
    }
  };
  document.addEventListener('click', handler, true);
  document.addEventListener('touchstart', handler, true);
  document.addEventListener('keydown', handler, true);
}

// Test-only — never used in production.
export function __resetAudioContextForTests() {
  if (_sharedCtx && _sharedCtx.state !== 'closed') {
    try {
      _sharedCtx.close();
    } catch (_err) {
      // ignore
    }
  }
  _sharedCtx = null;
  _unlockInstalled = false;
}
