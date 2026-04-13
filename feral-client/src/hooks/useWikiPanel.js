import { useState, useEffect } from 'react';
import { API_BASE } from '../config';

export function useWikiPanel() {
  const [wikiOpen, setWikiOpen] = useState(false);
  const [wikiPages, setWikiPages] = useState([]);
  const [wikiQuery, setWikiQuery] = useState('');
  const [wikiLoading, setWikiLoading] = useState(false);
  const [wikiSelected, setWikiSelected] = useState(null);
  const [wikiIngestOpen, setWikiIngestOpen] = useState(false);
  const [wikiIngestType, setWikiIngestType] = useState('repo');
  const [wikiIngestPath, setWikiIngestPath] = useState('');
  const [wikiIngestContent, setWikiIngestContent] = useState('');
  const [wikiIngestBusy, setWikiIngestBusy] = useState(false);
  const [wikiIngestResult, setWikiIngestResult] = useState('');

  async function fetchWikiPages(q = '') {
    setWikiLoading(true);
    try {
      const query = q ? `?q=${encodeURIComponent(q)}&limit=40` : '?limit=40';
      const res = await fetch(`${API_BASE}/api/wiki/pages${query}`);
      const data = await res.json();
      const pages = data.pages || [];
      setWikiPages(pages);
      if (pages.length > 0) {
        const detail = await fetch(`${API_BASE}/api/wiki/pages/${encodeURIComponent(pages[0].id)}`).then(r => r.json());
        if (!detail.error) setWikiSelected(prev => prev || detail);
      }
    } catch (e) {
      console.error('Wiki fetch failed:', e);
    } finally {
      setWikiLoading(false);
    }
  }

  async function openWikiPage(pageId) {
    try {
      const detail = await fetch(`${API_BASE}/api/wiki/pages/${encodeURIComponent(pageId)}`).then(r => r.json());
      if (!detail.error) setWikiSelected(detail);
    } catch (e) {
      console.error('Wiki page fetch failed:', e);
    }
  }

  async function compileWiki() {
    setWikiLoading(true);
    try {
      await fetch(`${API_BASE}/api/wiki/compile`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      await fetchWikiPages(wikiQuery);
    } catch (e) {
      console.error('Wiki compile failed:', e);
    } finally {
      setWikiLoading(false);
    }
  }

  const ingestWiki = async () => {
    setWikiIngestBusy(true);
    setWikiIngestResult('');
    try {
      let endpoint = '/api/wiki/ingest/repo';
      let payload = { path: wikiIngestPath, compile_after: true };
      if (wikiIngestType === 'pdf') {
        endpoint = '/api/wiki/ingest/pdf';
        payload = { path: wikiIngestPath, compile_after: true };
      } else if (wikiIngestType === 'text') {
        endpoint = '/api/wiki/ingest/text';
        payload = { content: wikiIngestContent, source_label: 'wiki_overlay', compile_after: true };
      }
      const out = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(r => r.json());
      if (out.error) {
        setWikiIngestResult(`Ingest failed: ${out.error}`);
      } else {
        const saved = out.notes_saved ?? out.note?.id ?? 0;
        setWikiIngestResult(`Ingest complete. Notes saved: ${saved}`);
        await fetchWikiPages(wikiQuery);
      }
    } catch (e) {
      setWikiIngestResult(`Ingest failed: ${e.message}`);
    } finally {
      setWikiIngestBusy(false);
    }
  };

  useEffect(() => {
    if (wikiOpen) fetchWikiPages(wikiQuery);
  }, [wikiOpen, wikiQuery]);

  return {
    wikiOpen, setWikiOpen,
    wikiPages,
    wikiQuery, setWikiQuery,
    wikiLoading,
    wikiSelected,
    wikiIngestOpen, setWikiIngestOpen,
    wikiIngestType, setWikiIngestType,
    wikiIngestPath, setWikiIngestPath,
    wikiIngestContent, setWikiIngestContent,
    wikiIngestBusy,
    wikiIngestResult,
    fetchWikiPages,
    openWikiPage,
    compileWiki,
    ingestWiki,
  };
}
