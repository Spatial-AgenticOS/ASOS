import React, { useCallback, useEffect, useRef, useState } from 'react';
import { History, Save, GitBranch, Plus, Trash2, ChevronRight, X } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import Orb from '../ui/Orb';
import EmptyState from '../ui/EmptyState';
import { useFeralSocket } from '../hooks/useFeralSocket';
import { useConnectionStatus } from '../hooks/useConnectionStatus';
import { apiJson, apiFetch } from '../lib/api';

function newId() {
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

export default function Chat() {
  const socket = useFeralSocket();
  const { state } = useConnectionStatus();
  const [messages, setMessages] = useState([
    { id: 'hello', role: 'assistant', text: 'FERAL v2 is listening. What do you need?' },
  ]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [toolChip, setToolChip] = useState(null);
  const [paneOpen, setPaneOpen] = useState(null); // 'threads' | 'snapshots' | null

  const bottomRef = useRef(null);
  const streamBufferRef = useRef('');
  const greetingSeenRef = useRef(false);

  useEffect(() => {
    const commit = (text) => {
      const clean = text.trim();
      if (!clean) return;
      setMessages((prev) => [...prev, { id: newId(), role: 'assistant', text: clean }]);
    };

    const unsub = socket.subscribe((msg) => {
      const type = msg?.type;
      if (type === 'stream_delta') {
        const p = msg.payload || {};
        if (p.is_final) {
          const final = streamBufferRef.current;
          streamBufferRef.current = '';
          setStreamingText('');
          setThinking(false);
          setToolChip(null);
          commit(final);
          return;
        }
        const delta = p.delta || '';
        if (!delta) return;
        streamBufferRef.current += delta;
        setStreamingText(streamBufferRef.current);
        setThinking(false);
      } else if (type === 'text_response') {
        const text = msg.payload?.text || '';
        if (!text) return;
        if (text === 'FERAL Brain connected. How can I help?') {
          if (greetingSeenRef.current) return;
          greetingSeenRef.current = true;
        }
        setThinking(false);
        setToolChip(null);
        const streamed = streamBufferRef.current;
        if (streamed && streamed.length > text.length) {
          streamBufferRef.current = '';
          setStreamingText('');
          commit(streamed);
        } else {
          streamBufferRef.current = '';
          setStreamingText('');
          commit(text);
        }
      } else if (type === 'tool_start' || type === 'tool_call' || type === 'skill_start') {
        const p = msg.payload || {};
        const name = p.name || p.tool || p.skill_id || 'tool';
        setToolChip(String(name));
      } else if (type === 'tool_result' || type === 'skill_result') {
        setToolChip(null);
      } else if (type === 'transcript') {
        const p = msg.payload || {};
        if (p.is_partial) return;
        const role = p.role || (p.text?.startsWith('[user] ') ? 'user' : 'assistant');
        const text = role === 'user' && p.text?.startsWith('[user] ')
          ? p.text.slice(7) : (p.text || '');
        if (!text) return;
        setMessages((prev) => [...prev, { id: newId(), role, text, source: 'voice' }]);
      }
    });
    return unsub;
  }, [socket]);

  useEffect(() => {
    const el = bottomRef.current;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking, streamingText]);

  const submit = (e) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || state !== 'open') return;
    setMessages((prev) => [...prev, { id: newId(), role: 'user', text }]);
    setInput('');
    setThinking(true);
    streamBufferRef.current = '';
    setStreamingText('');
    socket.send({ hop: 'client', type: 'text_command', payload: { text, context: {} } });
  };

  return (
    <div className="v2-chat v2-chat--paned" data-testid="v2-marker">
      <Pane
        title="Conversation"
        actions={(
          <>
            <button type="button" className={`v2-btn v2-btn--ghost${paneOpen === 'threads' ? ' is-active' : ''}`} onClick={() => setPaneOpen((p) => p === 'threads' ? null : 'threads')} title="Threads">
              <History size={13} />
            </button>
            <button type="button" className={`v2-btn v2-btn--ghost${paneOpen === 'snapshots' ? ' is-active' : ''}`} onClick={() => setPaneOpen((p) => p === 'snapshots' ? null : 'snapshots')} title="Snapshots">
              <Save size={13} />
            </button>
          </>
        )}
      >
        <div className="v2-chat-log">
          {messages.map((m) => (
            <div key={m.id} className={`v2-chat-row v2-chat-row--${m.role}`}>
              <div className="v2-chat-role" aria-hidden="true">
                <Orb size={22} mode={m.role === 'user' ? 'observing' : 'idle'} />
              </div>
              <div className="v2-chat-body">{m.text}</div>
            </div>
          ))}
          {streamingText && (
            <div className="v2-chat-row v2-chat-row--assistant">
              <div className="v2-chat-role" aria-hidden="true"><Orb size={22} mode="speaking" /></div>
              <div className="v2-chat-body">
                {streamingText}
                <span className="v2-chat-cursor" aria-hidden="true" />
              </div>
            </div>
          )}
          {thinking && !streamingText && (
            <div className="v2-chat-row v2-chat-row--assistant">
              <div className="v2-chat-role" aria-hidden="true"><Orb size={22} mode="thinking" /></div>
              <div className="v2-chat-body v2-chat-body--thinking">
                {toolChip ? `using ${toolChip}…` : 'thinking…'}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </Pane>

      <Glass as="form" level={2} radius="pill" padding="sm" className="v2-chat-composer" onSubmit={submit}>
        <input
          className="v2-chat-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={state === 'open' ? 'Ask FERAL…' : 'Reconnecting…'}
          disabled={state !== 'open'}
        />
        <button type="submit" className="v2-chat-send" disabled={!input.trim() || state !== 'open'} aria-label="Send">Send</button>
      </Glass>

      {paneOpen === 'threads' && <ThreadsPane onClose={() => setPaneOpen(null)} onLoad={(msgs) => { setMessages(msgs); setPaneOpen(null); }} />}
      {paneOpen === 'snapshots' && <SnapshotsPane onClose={() => setPaneOpen(null)} messages={messages} onRestore={(msgs) => { setMessages(msgs); setPaneOpen(null); }} />}
    </div>
  );
}

function ThreadsPane({ onClose, onLoad }) {
  const [threads, setThreads] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const d = await apiJson('/api/conversations');
      setThreads(d.conversations || d.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const open = async (id) => {
    try {
      const d = await apiJson(`/api/conversations/${encodeURIComponent(id)}`);
      const msgs = (d.messages || []).map((m) => ({ id: m.id || newId(), role: m.role, text: m.content || m.text || '' }));
      onLoad(msgs);
    } catch { /* silent */ }
  };

  const startNew = async () => {
    try {
      const r = await apiFetch('/api/conversations/new', { method: 'POST' });
      if (r.ok) {
        onLoad([{ id: 'hello', role: 'assistant', text: 'New thread started. What do you need?' }]);
        refresh();
      }
    } catch { /* silent */ }
  };

  const del = async (id) => {
    await apiFetch(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' });
    refresh();
  };

  return (
    <div className="v2-chat-pane">
      <header className="v2-chat-pane-head">
        <h3>Threads</h3>
        <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose} aria-label="Close"><X size={13} /></button>
      </header>
      <div className="v2-forge-actions">
        <button type="button" className="v2-btn v2-btn--primary" onClick={startNew}><Plus size={12} /> New thread</button>
      </div>
      {loading && <EmptyState title="Loading…" />}
      {!loading && threads.length === 0 && <EmptyState title="No threads yet" />}
      <ul className="v2-mem-list">
        {threads.map((t) => (
          <li key={t.id}>
            <Glass level={0} radius="sm" padding="sm">
              <div className="v2-flow-card-head">
                <button type="button" className="v2-flow-card-title" onClick={() => open(t.id)}>
                  {t.title || t.id.slice(0, 16)}
                </button>
                <button type="button" className="v2-btn v2-btn--ghost" onClick={() => del(t.id)} aria-label="Delete"><Trash2 size={12} /></button>
              </div>
              {t.updated_at && <div className="v2-mem-meta">{new Date(t.updated_at * 1000).toLocaleString()}</div>}
            </Glass>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SnapshotsPane({ onClose, messages, onRestore }) {
  const [snapshots, setSnapshots] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const d = await apiJson('/api/session/snapshots');
      setSnapshots(d.snapshots || d.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const save = async () => {
    await apiFetch('/api/session/snapshot', {
      method: 'POST',
      body: JSON.stringify({ messages }),
    });
    refresh();
  };

  const restore = async (id) => {
    const r = await apiFetch('/api/session/restore', {
      method: 'POST',
      body: JSON.stringify({ snapshot_id: id }),
    });
    if (r.ok) {
      const body = await r.json();
      const msgs = (body.messages || []).map((m) => ({ id: m.id || newId(), role: m.role, text: m.content || m.text || '' }));
      onRestore(msgs);
    }
  };

  const branch = async (id) => {
    await apiFetch('/api/session/branch', {
      method: 'POST',
      body: JSON.stringify({ snapshot_id: id }),
    });
    refresh();
  };

  return (
    <div className="v2-chat-pane">
      <header className="v2-chat-pane-head">
        <h3>Snapshots</h3>
        <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose} aria-label="Close"><X size={13} /></button>
      </header>
      <div className="v2-forge-actions">
        <button type="button" className="v2-btn v2-btn--primary" onClick={save}><Save size={12} /> Snapshot now</button>
      </div>
      {loading && <EmptyState title="Loading…" />}
      {!loading && snapshots.length === 0 && <EmptyState title="No snapshots yet" />}
      <ul className="v2-mem-list">
        {snapshots.map((s) => (
          <li key={s.id}>
            <Glass level={0} radius="sm" padding="sm">
              <div className="v2-flow-card-head">
                <span className="v2-flow-card-title">{s.title || s.id.slice(0, 16)}</span>
              </div>
              {s.created_at && <div className="v2-mem-meta">{new Date(s.created_at * 1000).toLocaleString()}</div>}
              <div className="v2-forge-actions">
                <button type="button" className="v2-btn" onClick={() => restore(s.id)}>Restore</button>
                <button type="button" className="v2-btn" onClick={() => branch(s.id)}><GitBranch size={12} /> Branch</button>
              </div>
            </Glass>
          </li>
        ))}
      </ul>
    </div>
  );
}
