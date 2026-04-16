const messagesEl = document.getElementById('messages');
const emptyState = document.getElementById('empty-state');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const voiceBtn = document.getElementById('voice-btn');
const statusDot = document.getElementById('status-dot');
const typingIndicator = document.getElementById('typing');
const contextBar = document.getElementById('context-bar');
const ctxPageTitle = document.getElementById('ctx-page-title');
const ctxDetach = document.getElementById('ctx-detach');
const btnContext = document.getElementById('btn-context');
const btnClear = document.getElementById('btn-clear');

let includeContext = false;
let isRecording = false;
let recognition = null;
let messages = [];

function updateConnectionStatus() {
  chrome.runtime.sendMessage({ type: 'get_connection_status' }, (res) => {
    if (chrome.runtime.lastError) return;
    const connected = res?.connected || false;
    statusDot.classList.toggle('connected', connected);
    statusDot.title = connected ? 'Connected to Brain' : 'Disconnected';
  });
}

function renderMarkdown(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

function addMessage(role, text) {
  if (emptyState.parentNode) emptyState.remove();

  const div = document.createElement('div');
  div.className = `msg ${role}`;
  if (role === 'assistant') {
    div.innerHTML = renderMarkdown(text);
  } else {
    div.textContent = text;
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  messages.push({ role, text, ts: Date.now() });
}

function showTyping(show) {
  typingIndicator.classList.toggle('active', show);
  if (show) messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function getActiveTabContext() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs[0]) return resolve({});
      chrome.tabs.sendMessage(tabs[0].id, { type: 'get_page_context' }, (res) => {
        if (chrome.runtime.lastError) return resolve({ url: tabs[0].url, title: tabs[0].title });
        resolve(res || {});
      });
    });
  });
}

async function sendMessage(text) {
  if (!text.trim()) return;

  addMessage('user', text);
  chatInput.value = '';
  chatInput.style.height = 'auto';
  updateSendButton();

  let context = {};
  if (includeContext) {
    context = await getActiveTabContext();
  }

  showTyping(true);

  chrome.runtime.sendMessage(
    { type: 'send_to_feral', text, context },
    (res) => {
      if (!res?.sent) {
        showTyping(false);
        addMessage('system', 'Not connected to FERAL Brain. Retrying...');
      }
    }
  );
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'brain_message' && msg.data) {
    showTyping(false);
    const data = msg.data;

    if (data.type === 'stream_delta') {
      const text = data.payload?.text || '';
      if (text) {
        if (emptyState.parentNode) emptyState.remove();
        let streamEl = document.getElementById('streaming-msg');
        if (!streamEl) {
          streamEl = document.createElement('div');
          streamEl.id = 'streaming-msg';
          streamEl.className = 'msg assistant';
          messagesEl.appendChild(streamEl);
        }
        streamEl.dataset.raw = (streamEl.dataset.raw || '') + text;
        streamEl.innerHTML = renderMarkdown(streamEl.dataset.raw);
        messagesEl.scrollTop = messagesEl.scrollHeight;

        if (data.payload?.final) {
          const finalText = streamEl.dataset.raw;
          streamEl.removeAttribute('id');
          delete streamEl.dataset.raw;
          messages.push({ role: 'assistant', text: finalText, ts: Date.now() });
        }
      }
    } else if (data.type === 'text_response' || data.type === 'assistant_reply') {
      const text = data.payload?.text || data.payload?.content || JSON.stringify(data.payload);
      addMessage('assistant', text);
    } else if (data.type === 'error') {
      addMessage('system', `Error: ${data.payload?.message || 'Unknown error'}`);
    } else if (data.type === 'thinking' || data.type === 'processing') {
      showTyping(true);
    } else if (data.type === 'proactive_alert' || data.type === 'brain_event') {
      const p = data.payload || {};
      addMessage('assistant', p.text || p.body || p.title || 'New alert');
    }
  }
});

chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
  updateSendButton();
});

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage(chatInput.value);
  }
});

function updateSendButton() {
  sendBtn.classList.toggle('active', chatInput.value.trim().length > 0);
}

sendBtn.addEventListener('click', () => sendMessage(chatInput.value));

btnContext.addEventListener('click', async () => {
  includeContext = !includeContext;
  contextBar.classList.toggle('active', includeContext);
  btnContext.style.color = includeContext ? 'var(--accent-cyan)' : '';
  if (includeContext) {
    const ctx = await getActiveTabContext();
    ctxPageTitle.textContent = ctx.title || ctx.url || 'Page context attached';
  }
});

ctxDetach.addEventListener('click', () => {
  includeContext = false;
  contextBar.classList.remove('active');
  btnContext.style.color = '';
});

btnClear.addEventListener('click', () => {
  messages = [];
  messagesEl.innerHTML = '';
  messagesEl.appendChild(emptyState);
  showTyping(false);
});

document.querySelectorAll('.quick-action').forEach(btn => {
  btn.addEventListener('click', () => {
    sendMessage(btn.dataset.prompt);
  });
});

voiceBtn.addEventListener('click', () => {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    addMessage('system', 'Speech recognition not supported in this browser.');
    return;
  }

  if (isRecording && recognition) {
    recognition.stop();
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = 'en-US';

  recognition.onstart = () => {
    isRecording = true;
    voiceBtn.classList.add('recording');
  };

  recognition.onresult = (event) => {
    let transcript = '';
    for (let i = 0; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    chatInput.value = transcript;
    updateSendButton();
  };

  recognition.onend = () => {
    isRecording = false;
    voiceBtn.classList.remove('recording');
    if (chatInput.value.trim()) {
      sendMessage(chatInput.value);
    }
  };

  recognition.onerror = () => {
    isRecording = false;
    voiceBtn.classList.remove('recording');
  };

  recognition.start();
});

updateConnectionStatus();
setInterval(updateConnectionStatus, 5000);
chatInput.focus();
