function getPageContext() {
  const selection = window.getSelection()?.toString() || '';
  const meta = {};
  document.querySelectorAll('meta').forEach(m => {
    const name = m.getAttribute('name') || m.getAttribute('property') || '';
    if (name) meta[name] = m.getAttribute('content') || '';
  });

  return {
    url: location.href,
    title: document.title,
    selectedText: selection,
    visibleText: document.body?.innerText?.slice(0, 5000) || '',
    metaDescription: meta['description'] || meta['og:description'] || '',
    metaKeywords: meta['keywords'] || '',
  };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'get_page_text') {
    sendResponse({ text: document.body?.innerText?.slice(0, 10000) || '' });
  } else if (msg.type === 'get_page_context') {
    sendResponse(getPageContext());
  }
  return true;
});

const btn = document.createElement('div');
btn.id = 'feral-float-btn';
btn.innerHTML = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 12h8M12 8v8"/></svg>`;
btn.title = 'Open FERAL';
document.body?.appendChild(btn);

btn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'open_sidepanel' });
});
