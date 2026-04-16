const statusDot = document.getElementById('status-dot');
const statusLabel = document.getElementById('status-label');
const reconnectBtn = document.getElementById('reconnect-btn');
const brainUrlInput = document.getElementById('brain-url');
const openSidebar = document.getElementById('open-sidebar');
const openOptions = document.getElementById('open-options');
const optionsLink = document.getElementById('options-link');

function updateStatus() {
  chrome.runtime.sendMessage({ type: 'get_connection_status' }, (res) => {
    if (chrome.runtime.lastError) return;
    const connected = res?.connected || false;
    statusDot.classList.toggle('connected', connected);
    statusLabel.textContent = connected ? 'Connected to Brain' : 'Disconnected';
  });
}

chrome.storage.local.get(['brainUrl'], (result) => {
  brainUrlInput.value = result.brainUrl || 'ws://localhost:9090/v1/session';
});

brainUrlInput.addEventListener('change', () => {
  const url = brainUrlInput.value.trim();
  if (url) {
    chrome.runtime.sendMessage({ type: 'set_brain_url', url });
  }
});

reconnectBtn.addEventListener('click', () => {
  const url = brainUrlInput.value.trim();
  if (url) {
    chrome.runtime.sendMessage({ type: 'set_brain_url', url });
  }
  statusLabel.textContent = 'Reconnecting...';
  setTimeout(updateStatus, 2000);
});

openSidebar.addEventListener('click', () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]) {
      chrome.sidePanel.open({ tabId: tabs[0].id });
    }
  });
  window.close();
});

openOptions.addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
  window.close();
});

optionsLink.addEventListener('click', (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
  window.close();
});

updateStatus();
