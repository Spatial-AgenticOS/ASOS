let ws = null;
let wsUrl = 'ws://localhost:9090/v1/session';
let reconnectTimer = null;
let messageCallbacks = new Map();

function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('[FERAL] Connected to Brain');
      chrome.action.setBadgeText({ text: '' });
      chrome.action.setBadgeBackgroundColor({ color: '#10b981' });
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        chrome.runtime.sendMessage({ type: 'brain_message', data: msg }).catch(() => {});

        if (msg.type === 'proactive_alert' || msg.type === 'brain_event') {
          const payload = msg.payload || {};
          if (payload.title) {
            chrome.notifications.create({
              type: 'basic',
              iconUrl: 'icons/icon128.png',
              title: payload.title || 'FERAL',
              message: payload.body || payload.text || '',
            });
          }
        }
      } catch {}
    };

    ws.onclose = () => {
      console.log('[FERAL] Disconnected');
      chrome.action.setBadgeText({ text: '!' });
      chrome.action.setBadgeBackgroundColor({ color: '#ef4444' });
      ws = null;
      reconnectTimer = setTimeout(connect, 3000);
    };

    ws.onerror = () => { ws?.close(); };
  } catch (e) {
    reconnectTimer = setTimeout(connect, 5000);
  }
}

function sendToFeral(text, context = {}) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    connect();
    return false;
  }
  ws.send(JSON.stringify({
    hop: 'client',
    type: 'text_command',
    payload: { text, context },
  }));
  return true;
}

chrome.contextMenus.create({
  id: 'feral-ask',
  title: 'Ask FERAL about this',
  contexts: ['selection'],
});

chrome.contextMenus.create({
  id: 'feral-summarize',
  title: 'Summarize this page',
  contexts: ['page'],
});

chrome.contextMenus.create({
  id: 'feral-save',
  title: 'Save to FERAL memory',
  contexts: ['selection'],
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const pageContext = { url: tab?.url, title: tab?.title };

  if (info.menuItemId === 'feral-ask') {
    sendToFeral(`About this text from ${tab?.title}: "${info.selectionText}"`, pageContext);
    chrome.sidePanel.open({ tabId: tab.id });
  } else if (info.menuItemId === 'feral-summarize') {
    chrome.tabs.sendMessage(tab.id, { type: 'get_page_text' }, (response) => {
      const text = response?.text || '';
      sendToFeral(`Summarize this page (${tab?.title}): ${text.slice(0, 8000)}`, pageContext);
      chrome.sidePanel.open({ tabId: tab.id });
    });
  } else if (info.menuItemId === 'feral-save') {
    sendToFeral(`Save this to memory: "${info.selectionText}"`, { ...pageContext, action: 'save_to_memory' });
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'send_to_feral') {
    const ok = sendToFeral(msg.text, msg.context || {});
    sendResponse({ sent: ok });
  } else if (msg.type === 'get_connection_status') {
    sendResponse({ connected: ws && ws.readyState === WebSocket.OPEN });
  } else if (msg.type === 'set_brain_url') {
    wsUrl = msg.url;
    chrome.storage.local.set({ brainUrl: msg.url });
    if (ws) ws.close();
    connect();
    sendResponse({ ok: true });
  } else if (msg.type === 'open_sidepanel') {
    chrome.sidePanel.open({ tabId: sender.tab?.id }).catch(() => {});
    sendResponse({ ok: true });
  }
  return true;
});

chrome.storage.local.get(['brainUrl'], (result) => {
  if (result.brainUrl) wsUrl = result.brainUrl;
  connect();
});
