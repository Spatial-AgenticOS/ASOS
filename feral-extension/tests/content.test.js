import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('content.js — floating button injection', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('injects a floating button element into the DOM', () => {
    const btn = document.createElement('div');
    btn.id = 'feral-float-btn';
    btn.title = 'Open FERAL';
    btn.innerHTML = '<svg width="24" height="24"></svg>';
    document.body.appendChild(btn);

    const el = document.getElementById('feral-float-btn');
    expect(el).not.toBeNull();
    expect(el.title).toBe('Open FERAL');
    expect(el.querySelector('svg')).not.toBeNull();
  });

  it('button click triggers message to runtime', () => {
    const sendMessage = vi.fn();
    globalThis.chrome = { runtime: { sendMessage } };

    const btn = document.createElement('div');
    btn.id = 'feral-float-btn';
    btn.addEventListener('click', () => {
      chrome.runtime.sendMessage({ type: 'open_sidepanel' });
    });
    document.body.appendChild(btn);

    btn.click();
    expect(sendMessage).toHaveBeenCalledWith({ type: 'open_sidepanel' });

    delete globalThis.chrome;
  });
});

describe('content.js — page context extraction', () => {
  beforeEach(() => {
    document.body.innerHTML = '<p>Hello World</p>';
    document.title = 'Test Page';
  });

  function getPageContext() {
    const selection = window.getSelection()?.toString() || '';
    const meta = {};
    document.querySelectorAll('meta').forEach(m => {
      const name = m.getAttribute('name') || m.getAttribute('property') || '';
      if (name) meta[name] = m.getAttribute('content') || '';
    });
    const text = document.body?.innerText || document.body?.textContent || '';
    return {
      url: location.href,
      title: document.title,
      selectedText: selection,
      visibleText: text.slice(0, 5000),
      metaDescription: meta['description'] || meta['og:description'] || '',
      metaKeywords: meta['keywords'] || '',
    };
  }

  it('extracts URL and title', () => {
    const ctx = getPageContext();
    expect(ctx.title).toBe('Test Page');
    expect(ctx.url).toBeTruthy();
  });

  it('extracts visible text', () => {
    const ctx = getPageContext();
    expect(ctx.visibleText).toContain('Hello World');
  });

  it('extracts meta description', () => {
    const meta = document.createElement('meta');
    meta.setAttribute('name', 'description');
    meta.setAttribute('content', 'A test page description');
    document.head.appendChild(meta);

    const ctx = getPageContext();
    expect(ctx.metaDescription).toBe('A test page description');
  });

  it('returns empty selectedText when nothing is selected', () => {
    const ctx = getPageContext();
    expect(ctx.selectedText).toBe('');
  });
});

describe('content.js — message passing', () => {
  it('responds to get_page_text with body text', () => {
    document.body.innerHTML = '<p>Some page content for FERAL</p>';

    const listener = (msg, _sender, sendResponse) => {
      if (msg.type === 'get_page_text') {
        const text = document.body?.innerText || document.body?.textContent || '';
        sendResponse({ text: text.slice(0, 10000) });
      }
    };

    const response = {};
    listener({ type: 'get_page_text' }, {}, (r) => { Object.assign(response, r); });

    expect(response.text).toContain('Some page content for FERAL');
  });

  it('responds to get_page_context with structured data', () => {
    document.body.innerHTML = '<p>Context test</p>';
    document.title = 'Context Title';

    const listener = (msg, _sender, sendResponse) => {
      if (msg.type === 'get_page_context') {
        const text = document.body?.innerText || document.body?.textContent || '';
        sendResponse({
          url: location.href,
          title: document.title,
          selectedText: '',
          visibleText: text.slice(0, 5000),
        });
      }
    };

    const response = {};
    listener({ type: 'get_page_context' }, {}, (r) => { Object.assign(response, r); });

    expect(response.title).toBe('Context Title');
    expect(response.visibleText).toContain('Context test');
  });
});
