import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

const appEl = document.getElementById('app');

function showStarting() {
  appEl.innerHTML = `
    <div class="wrap">
      <div class="spinner"></div>
      <p class="title">Starting THEORA Brain…</p>
      <p class="hint">Waiting for the server at http://localhost:9090</p>
    </div>
  `;
}

function showBrain(url) {
  appEl.innerHTML = `<iframe src="${url}" title="THEORA" class="frame" allow="clipboard-read; clipboard-write"></iframe>`;
}

function showError(msg) {
  appEl.innerHTML = `
    <div class="wrap">
      <p class="title">${msg}</p>
      <p class="hint">Set <code>ASOS_CORE_DIR</code> if the brain lives outside the default layout.</p>
      <button class="btn" type="button" id="retry">Retry</button>
    </div>
  `;
  document.getElementById('retry').onclick = () => window.location.reload();
}

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
