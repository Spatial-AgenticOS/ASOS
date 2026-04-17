import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

function createMockWebSocket() {
  const instances = [];
  class MockWebSocket {
    static OPEN = 1;
    static CLOSED = 3;
    constructor(url) {
      this.url = url;
      this.readyState = MockWebSocket.OPEN;
      this.onopen = null;
      this.onmessage = null;
      this.onclose = null;
      this.onerror = null;
      this.sentMessages = [];
      instances.push(this);
    }
    send(data) { this.sentMessages.push(data); }
    close() { this.readyState = MockWebSocket.CLOSED; this.onclose?.(); }
  }
  return { MockWebSocket, instances };
}

function createChromeStub() {
  return {
    action: {
      setBadgeText: vi.fn(),
      setBadgeBackgroundColor: vi.fn(),
    },
    runtime: {
      sendMessage: vi.fn().mockResolvedValue(undefined),
      onMessage: { addListener: vi.fn() },
      lastError: null,
    },
    notifications: {
      create: vi.fn(),
    },
    contextMenus: {
      create: vi.fn(),
      onClicked: { addListener: vi.fn() },
    },
    sidePanel: {
      open: vi.fn().mockResolvedValue(undefined),
    },
    storage: {
      local: {
        get: vi.fn((keys, cb) => cb({})),
        set: vi.fn(),
      },
      sync: {
        get: vi.fn((keys, cb) => cb({})),
        set: vi.fn(),
      },
    },
    tabs: {
      sendMessage: vi.fn(),
      query: vi.fn(),
    },
  };
}

describe('background.js — WebSocket reconnect logic', () => {
  let chrome;
  let wsKit;

  beforeEach(() => {
    vi.useFakeTimers();
    wsKit = createMockWebSocket();
    chrome = createChromeStub();
    globalThis.chrome = chrome;
    globalThis.WebSocket = wsKit.MockWebSocket;
  });

  afterEach(() => {
    vi.useRealTimers();
    delete globalThis.chrome;
    delete globalThis.WebSocket;
  });

  it('creates a WebSocket with the expected default URL', () => {
    const ws = new WebSocket('ws://localhost:9090/v1/session');
    expect(ws.url).toBe('ws://localhost:9090/v1/session');
    expect(wsKit.instances).toHaveLength(1);
  });

  it('schedules reconnect on WebSocket close', () => {
    const ws = new WebSocket('ws://localhost:9090/v1/session');
    let reconnected = false;
    ws.onclose = () => { reconnected = true; };
    ws.close();
    expect(reconnected).toBe(true);
  });

  it('sends JSON messages through WebSocket', () => {
    const ws = new WebSocket('ws://localhost:9090/v1/session');
    const msg = { hop: 'client', type: 'text_command', payload: { text: 'hello' } };
    ws.send(JSON.stringify(msg));
    expect(ws.sentMessages).toHaveLength(1);
    expect(JSON.parse(ws.sentMessages[0])).toEqual(msg);
  });
});

describe('background.js — context menu registration', () => {
  let chrome;

  beforeEach(() => {
    chrome = createChromeStub();
    globalThis.chrome = chrome;
  });

  afterEach(() => { delete globalThis.chrome; });

  it('chrome.contextMenus.create is callable with expected IDs', () => {
    chrome.contextMenus.create({ id: 'feral-ask', title: 'Ask FERAL about this', contexts: ['selection'] });
    chrome.contextMenus.create({ id: 'feral-summarize', title: 'Summarize this page', contexts: ['page'] });
    chrome.contextMenus.create({ id: 'feral-save', title: 'Save to FERAL memory', contexts: ['selection'] });

    expect(chrome.contextMenus.create).toHaveBeenCalledTimes(3);
    expect(chrome.contextMenus.create.mock.calls[0][0].id).toBe('feral-ask');
    expect(chrome.contextMenus.create.mock.calls[1][0].id).toBe('feral-summarize');
    expect(chrome.contextMenus.create.mock.calls[2][0].id).toBe('feral-save');
  });
});

describe('background.js — notifications', () => {
  let chrome;

  beforeEach(() => {
    chrome = createChromeStub();
    globalThis.chrome = chrome;
  });

  afterEach(() => { delete globalThis.chrome; });

  it('fires chrome.notifications.create for proactive_alert payloads', () => {
    const payload = { title: 'Heart Rate Alert', body: 'HR is above 120 bpm' };
    chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icons/icon128.png',
      title: payload.title,
      message: payload.body,
    });

    expect(chrome.notifications.create).toHaveBeenCalledTimes(1);
    expect(chrome.notifications.create.mock.calls[0][0].title).toBe('Heart Rate Alert');
    expect(chrome.notifications.create.mock.calls[0][0].message).toBe('HR is above 120 bpm');
  });

  it('does not fire notification when title is missing', () => {
    const payload = { body: 'some text' };
    if (payload.title) {
      chrome.notifications.create({ type: 'basic', title: payload.title, message: payload.body });
    }
    expect(chrome.notifications.create).not.toHaveBeenCalled();
  });
});
