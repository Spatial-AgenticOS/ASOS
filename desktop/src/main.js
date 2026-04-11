import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

const appEl = document.getElementById('app');

// ---------------------------------------------------------------------------
// SVG assets (inline so no external file is needed)
// ---------------------------------------------------------------------------

const BRAIN_SVG = `
<svg viewBox="0 0 88 88" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Neural brain icon with sparkle accents -->
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="88" y2="88" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#6366f1" stop-opacity=".15"/>
      <stop offset="100%" stop-color="#a78bfa" stop-opacity=".08"/>
    </linearGradient>
    <linearGradient id="stroke" x1="20" y1="18" x2="68" y2="72" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#818cf8"/>
      <stop offset="100%" stop-color="#a78bfa"/>
    </linearGradient>
    <linearGradient id="sparkle" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#c4b5fd"/>
      <stop offset="100%" stop-color="#6366f1"/>
    </linearGradient>
  </defs>
  <circle cx="44" cy="44" r="40" fill="url(#bg)"/>
  <!-- Left hemisphere -->
  <path d="M44 24c-8 0-14 3-17 8s-4 11-2 17c1.5 4.5 5 8.5 10 11.5 3 1.8 6 3 9 3.5"
        stroke="url(#stroke)" stroke-width="2.2" stroke-linecap="round" fill="none"/>
  <!-- Right hemisphere -->
  <path d="M44 24c8 0 14 3 17 8s4 11 2 17c-1.5 4.5-5 8.5-10 11.5-3 1.8-6 3-9 3.5"
        stroke="url(#stroke)" stroke-width="2.2" stroke-linecap="round" fill="none"/>
  <!-- Central fissure -->
  <line x1="44" y1="24" x2="44" y2="64" stroke="url(#stroke)" stroke-width="1.5" stroke-dasharray="3 3" opacity=".5"/>
  <!-- Neural connections -->
  <circle cx="36" cy="36" r="2" fill="#818cf8" opacity=".8"/>
  <circle cx="52" cy="36" r="2" fill="#818cf8" opacity=".8"/>
  <circle cx="44" cy="44" r="2.5" fill="#a78bfa"/>
  <circle cx="36" cy="52" r="2" fill="#818cf8" opacity=".8"/>
  <circle cx="52" cy="52" r="2" fill="#818cf8" opacity=".8"/>
  <line x1="36" y1="36" x2="44" y2="44" stroke="#818cf8" stroke-width="1" opacity=".4"/>
  <line x1="52" y1="36" x2="44" y2="44" stroke="#818cf8" stroke-width="1" opacity=".4"/>
  <line x1="36" y1="52" x2="44" y2="44" stroke="#818cf8" stroke-width="1" opacity=".4"/>
  <line x1="52" y1="52" x2="44" y2="44" stroke="#818cf8" stroke-width="1" opacity=".4"/>
  <!-- Sparkle top-right -->
  <g transform="translate(64,18)" opacity=".9">
    <path d="M4 0L5 3.5 8 4 5 5 4 8 3 5 0 4 3 3.5Z" fill="url(#sparkle)"/>
  </g>
  <!-- Sparkle bottom-left -->
  <g transform="translate(14,62)" opacity=".6">
    <path d="M3 0L3.8 2.5 6 3 3.8 3.5 3 6 2.2 3.5 0 3 2.2 2.5Z" fill="url(#sparkle)"/>
  </g>
</svg>`;

const ERROR_SVG = `
<svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <line x1="12" y1="8" x2="12" y2="12"/>
  <line x1="12" y1="16" x2="12.01" y2="16"/>
</svg>`;

// ---------------------------------------------------------------------------
// UI states
// ---------------------------------------------------------------------------

function showStarting() {
  appEl.innerHTML = `
    <div class="splash">
      <div class="splash-logo">
        <div class="glow-ring"></div>
        <div class="glow-ring"></div>
        <div class="glow-ring"></div>
        ${BRAIN_SVG}
      </div>
      <div class="splash-title">THEORA</div>
      <div class="splash-subtitle">Local-First Agentic OS</div>
      <div class="splash-dots"><span></span><span></span><span></span></div>
      <div class="splash-status">Initializing brain on localhost:9090 …</div>
    </div>
  `;
}

function showBrain(url) {
  appEl.innerHTML = `<iframe src="${url}" title="THEORA" class="frame" allow="clipboard-read; clipboard-write"></iframe>`;
}

function showError(msg) {
  appEl.innerHTML = `
    <div class="error-wrap">
      ${ERROR_SVG}
      <div class="error-title">${msg}</div>
      <div class="error-hint">
        Make sure the ASOS brain server is reachable.<br/>
        Set <code>ASOS_CORE_DIR</code> if the brain lives outside the default layout.
      </div>
      <button class="btn" type="button" id="retry">Retry</button>
    </div>
  `;
  document.getElementById('retry').onclick = () => window.location.reload();
}

// ---------------------------------------------------------------------------
// Health polling
// ---------------------------------------------------------------------------

function isHealthyStatus(status) {
  return typeof status === 'string' && /^HTTP 2\d\d\b/.test(status);
}

async function waitForBrain() {
  const tick = async () => {
    try {
      const status = await invoke('check_brain_health');
      if (isHealthyStatus(status)) {
        const url = await invoke('get_brain_url');
        showBrain(url);
        return true;
      }
    } catch {
      /* still starting */
    }
    return false;
  };

  if (await tick()) return;

  const id = window.setInterval(async () => {
    if (await tick()) window.clearInterval(id);
  }, 2000);
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  showStarting();
  try {
    await invoke('start_brain');
  } catch (e) {
    showError(`Could not start brain: ${e}`);
    return;
  }
  await waitForBrain();
}

void (async () => {
  await listen('voice-activation', () => {
    window.dispatchEvent(new CustomEvent('theora-voice-activation'));
    console.log('[THEORA] Voice shortcut (Cmd/Ctrl+Shift+T)');
  });
  await boot();
})();
