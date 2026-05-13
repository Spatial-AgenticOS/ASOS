import React, { useCallback, useEffect, useRef, useState } from 'react';
import { History, Save, GitBranch, Plus, Trash2, ChevronRight, X, Mic, MicOff, Paperclip, FileText } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import Orb from '../ui/Orb';
import EmptyState from '../ui/EmptyState';
import SduiRenderer, { applySduiPatches } from '../ui/SduiRenderer';
import { useFeralSocket, sendUiEvent } from '../hooks/useFeralSocket';
import { useConnectionStatus } from '../hooks/useConnectionStatus';
import { apiJson, apiFetch } from '../lib/api';
import { friendlyToolLabel } from '../lib/toolDisplay';
import { useChatThread } from '../shell/Shell';
import { useVoice } from '../shell/VoiceContext';

function newId() {
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

// Client-side defense-in-depth scrubber for assistant display text.
// Mirrors feral-core/agents/chat_sanitizer.py; if an older brain
// build forgets to strip control-token residue, the UI still
// presents clean prose. Kept narrow: only strips recognized residue,
// never invents content.
const TOOL_TAG = '(?:tool_calls|tool_call|function_call|function_calls|tool_use|tool_result|tools)';
const SENTINEL_RE = /<\|[^|>\s][^|>]*\|>/g;
const TOOL_BLOCK_RE = new RegExp(`<\\s*${TOOL_TAG}\\b[^>]*>[\\s\\S]*?<\\/\\s*${TOOL_TAG}\\s*>`, 'gi');
const ORPHAN_CLOSE_RE = new RegExp(`<\\/\\s*${TOOL_TAG}\\s*>`, 'gi');
const ORPHAN_OPEN_RE = new RegExp(`<\\s*${TOOL_TAG}\\b[^>]*\\/?>`, 'gi');
const INVOKE_RE = /\binvoke\s*\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]/gi;
const TRAILING_MARKER_RE = /(?:^|\s)(?:FUNCTION|FUNCTIONS|TOOL|TOOLS)\s*$/;

export function sanitizeAssistantText(input) {
  if (!input) return input;
  let out = String(input);
  out = out.replace(TOOL_BLOCK_RE, '');
  out = out.replace(INVOKE_RE, '');
  out = out.replace(ORPHAN_CLOSE_RE, '');
  out = out.replace(ORPHAN_OPEN_RE, '');
  out = out.replace(SENTINEL_RE, '');
  out = out.replace(TRAILING_MARKER_RE, '');
  return out;
}

export default function Chat() {
  const socket = useFeralSocket();
  const { state } = useConnectionStatus();
  const thread = useChatThread();
  const [localMessages, setLocalMessages] = useState([
    { id: 'hello', role: 'assistant', text: 'FERAL v2 is listening. What do you need?' },
  ]);
  const messages = thread?.messages || localMessages;
  const setMessages = thread?.setMessages || setLocalMessages;
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [toolChip, setToolChip] = useState(null);
  const [expandedTraces, setExpandedTraces] = useState({});
  const [paneOpen, setPaneOpen] = useState(null); // 'threads' | 'snapshots' | null
  const [pausedThoughts, setPausedThoughts] = useState([]);
  // PR 9 (gap-fill) — in-composer voice mic state. Sourced from the
  // shared VoiceContext so toggling the menubar mic and the chat mic
  // stay in sync.
  const voice = useVoice();
  // PR 10 (gap-fill) — pending attachments (uploaded but not yet sent).
  // Each item is the AttachmentRef shape from POST /api/uploads.
  const [pendingAttachments, setPendingAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  const bottomRef = useRef(null);
  const streamBufferRef = useRef('');
  const pendingTraceRef = useRef([]);
  const greetingSeenRef = useRef(false);
  const chatReady = thread?.ready ?? true;

  // On mount, pull paused thoughts from the consciousness store so the
  // user can re-thread any half-formed sentence the agent was in the
  // middle of before the last restart. These are real paused
  // ConsciousnessEntity rows — not a local state guess. Resume
  // routes through the brain which registers the thought with the
  // orchestrator so the LLM sees [RESUMED THOUGHT] X before the next
  // user message.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiJson('/api/consciousness/state?kind=thought');
        if (cancelled) return;
        const paused = (data?.entities || []).filter(
          (e) => e.status === 'paused' || e.status === 'waiting_user',
        );
        setPausedThoughts(paused);
      } catch {
        /* consciousness endpoint not available -> skip silently */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const resumeThought = async (thoughtId) => {
    try {
      await apiFetch('/api/consciousness/resume', {
        method: 'POST',
        body: JSON.stringify({ id: thoughtId }),
      });
      setPausedThoughts((prev) => prev.filter((t) => t.id !== thoughtId));
      // Surface the resumed text as an assistant row so the user sees
      // what's about to be re-threaded into the next LLM call.
      const t = pausedThoughts.find((p) => p.id === thoughtId);
      const text = t?.context_json?.text || t?.summary || '';
      if (text) {
        setMessages((prev) => [
          ...prev,
          { id: newId(), role: 'assistant', text: `[continuing from earlier] ${text}` },
        ]);
      }
    } catch { /* keep the thought in the list so user can retry */ }
  };

  const abandonThought = async (thoughtId) => {
    try {
      await apiFetch('/api/consciousness/abandon', {
        method: 'POST',
        body: JSON.stringify({ id: thoughtId }),
      });
    } catch { /* fall through */ }
    setPausedThoughts((prev) => prev.filter((t) => t.id !== thoughtId));
  };

  useEffect(() => {
    const traceKey = (payload) => payload?.call_id || payload?.tool || payload?.name || `tool-${Date.now()}`;

    const flushTrace = () => {
      const trace = pendingTraceRef.current;
      pendingTraceRef.current = [];
      return trace.length > 0 ? trace : undefined;
    };

    const commit = (text) => {
      const clean = text.trim();
      if (!clean) return;
      const id = newId();
      setMessages((prev) => [...prev, {
        id,
        role: 'assistant',
        text: clean,
        tools: flushTrace(),
      }]);
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
        const delta = sanitizeAssistantText(p.delta || '');
        if (!delta) return;
        streamBufferRef.current += delta;
        setStreamingText(streamBufferRef.current);
        setThinking(false);
      } else if (type === 'text_response') {
        const text = sanitizeAssistantText(msg.payload?.text || '');
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
        const key = traceKey(p);
        const label = friendlyToolLabel(p);
        pendingTraceRef.current = [
          ...pendingTraceRef.current.filter((t) => t.key !== key),
          {
            key,
            label,
            args_preview: p.args_preview || '',
            success: null,
            error: '',
            latency_ms: 0,
          },
        ];
        setToolChip(label);
      } else if (type === 'tool_result' || type === 'skill_result') {
        const p = msg.payload || {};
        const key = traceKey(p);
        const label = friendlyToolLabel(p);
        const idx = pendingTraceRef.current.findIndex((t) => t.key === key);
        const next = [...pendingTraceRef.current];
        const result = {
          key,
          label,
          args_preview: '',
          success: p.success !== false,
          error: p.error || '',
          latency_ms: Number(p.latency_ms || 0),
        };
        if (idx >= 0) {
          next[idx] = {
            ...next[idx],
            success: result.success,
            error: result.error,
            latency_ms: result.latency_ms,
          };
        } else {
          next.push(result);
        }
        pendingTraceRef.current = next;
        setToolChip(null);
      } else if (type === 'transcript') {
        const p = msg.payload || {};
        if (p.is_partial) return;
        const role = p.role || (p.text?.startsWith('[user] ') ? 'user' : 'assistant');
        const text = role === 'user' && p.text?.startsWith('[user] ')
          ? p.text.slice(7) : (p.text || '');
        if (!text) return;
        setMessages((prev) => [...prev, { id: newId(), role, text, source: 'voice' }]);
      } else if (type === 'sdui') {
        // Brain-emitted SDUI payload. Append as its own message so the
        // recursive renderer can mount the tree inline in the chat log.
        const p = msg.payload || {};
        const root = p.root || p;
        if (!root || typeof root !== 'object') return;
        setMessages((prev) => [
          ...prev,
          {
            id: newId(),
            role: 'assistant',
            type: 'sdui',
            sdui: root,
            screen_id: p.screen_id || null,
          },
        ]);
      } else if (type === 'sdui_patch') {
        // In-place mutation of an already-mounted SDUI message. Match
        // on the trailing screen_id so multiple surfaces don't clobber
        // each other.
        const p = msg.payload || {};
        const targetId = p.screen_id;
        if (!targetId) return;
        setMessages((prev) => prev.map((m) => (
          m.type === 'sdui' && m.screen_id === targetId
            ? { ...m, sdui: applySduiPatches(m.sdui, p.patches || []) }
            : m
        )));
      } else if (type === 'permission_request') {
        // Brain refused a computer_use file/shell call because the path
        // is outside the sandbox. Render an inline approval card so the
        // operator can grant the folder without leaving the chat.
        const p = msg.payload || {};
        if (!p.request_id) return;
        setMessages((prev) => {
          // Replace any existing card for this request_id (re-emits are
          // possible if the brain retries after a transient failure).
          const filtered = prev.filter(
            (m) => !(m.type === 'permission_request' && m.requestId === p.request_id),
          );
          return [
            ...filtered,
            {
              id: newId(),
              role: 'assistant',
              type: 'permission_request',
              requestId: p.request_id,
              path: p.path || '',
              operation: p.operation || 'access',
              reason: p.reason || '',
            },
          ];
        });
        setThinking(false);
      }
    });
    return unsub;
  }, [socket]);

  useEffect(() => {
    const el = bottomRef.current;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking, streamingText]);

  const submit = async (e) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || state !== 'open' || !chatReady) return;
    if (thread?.ensureConversation) {
      try {
        await thread.ensureConversation();
      } catch {
        // best effort; keep chatting even if thread ensure call fails
      }
    }
    const attachmentsToSend = pendingAttachments;
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: 'user', text, attachments: attachmentsToSend },
    ]);
    setInput('');
    setPendingAttachments([]);
    setThinking(true);
    streamBufferRef.current = '';
    pendingTraceRef.current = [];
    setStreamingText('');
    // PR 10: ship the AttachmentRef list verbatim. The brain
    // (api/server.py text_command handler) forwards `payload.attachments`
    // into the orchestrator context so the model can ground on them.
    socket.send({
      hop: 'client',
      type: 'text_command',
      payload: {
        text,
        context: {},
        ...(attachmentsToSend.length > 0 ? { attachments: attachmentsToSend } : {}),
      },
    });
  };

  // ── PR 10: upload helpers ─────────────────────────────────────
  const uploadFiles = useCallback(async (fileList) => {
    if (!fileList || fileList.length === 0) return;
    setUploading(true);
    setUploadError('');
    const accepted = [];
    for (const file of fileList) {
      try {
        const fd = new FormData();
        fd.append('file', file, file.name);
        const resp = await apiFetch('/api/uploads', { method: 'POST', body: fd });
        if (!resp.ok) {
          const errBody = await resp.json().catch(() => ({}));
          throw new Error(errBody.detail || `upload failed (${resp.status})`);
        }
        const rec = await resp.json();
        accepted.push({
          upload_id: rec.upload_id,
          filename: rec.filename,
          content_type: rec.content_type,
          size_bytes: rec.size_bytes,
          sha256: rec.sha256,
        });
      } catch (err) {
        setUploadError(String(err.message || err));
      }
    }
    if (accepted.length > 0) {
      setPendingAttachments((prev) => [...prev, ...accepted]);
    }
    setUploading(false);
  }, []);

  const onFilePick = useCallback((e) => {
    const fl = e?.target?.files;
    if (fl && fl.length > 0) uploadFiles(Array.from(fl));
    if (e?.target) e.target.value = '';
  }, [uploadFiles]);

  const onPaste = useCallback((e) => {
    const items = e?.clipboardData?.items || [];
    const files = [];
    for (const it of items) {
      if (it.kind === 'file') {
        const f = it.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      uploadFiles(files);
    }
  }, [uploadFiles]);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer?.files || []);
    if (files.length > 0) uploadFiles(files);
  }, [uploadFiles]);

  const removeAttachment = useCallback((uploadId) => {
    setPendingAttachments((prev) => prev.filter((a) => a.upload_id !== uploadId));
  }, []);

  // ── PR 9: voice toggle ────────────────────────────────────────
  const onMicClick = useCallback(() => {
    if (!voice || !voice.toggle) return;
    voice.toggle();
  }, [voice]);

  const toggleTrace = (messageId) => {
    setExpandedTraces((prev) => ({ ...prev, [messageId]: !prev[messageId] }));
  };

  const respondToPermission = useCallback((requestId, granted) => {
    if (!requestId) return;
    sendUiEvent(socket, {
      screen_id: 'chat',
      action_id: `${granted ? 'perm_grant_' : 'perm_deny_'}${requestId}`,
      event: 'tap',
    });
    // Replace the live card with a settled receipt so the user sees
    // the decision was registered. The brain emits its own follow-up
    // text, but the receipt is shown immediately so the UI never
    // looks unresponsive between click and reply.
    setMessages((prev) => prev.map((m) => (
      m.type === 'permission_request' && m.requestId === requestId
        ? { ...m, type: 'permission_request_settled', granted }
        : m
    )));
  }, [socket, setMessages]);

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
        {pausedThoughts.length > 0 && (
          <div className="v2-chat-rehydrate" role="status" aria-live="polite">
            {pausedThoughts.map((t) => {
              const text = t.context_json?.text || t.summary || '';
              return (
                <Glass key={t.id} level={0} radius="md" padding="sm" className="v2-chat-rehydrate-row">
                  <div className="v2-chat-rehydrate-body">
                    <strong>Continuing from earlier:</strong>
                    <div className="v2-p v2-p--muted" style={{ marginTop: 4 }}>
                      {text.slice(0, 200)}{text.length > 200 ? '…' : ''}
                    </div>
                  </div>
                  <div className="v2-chat-rehydrate-actions">
                    <button type="button" className="v2-btn v2-btn--primary" onClick={() => resumeThought(t.id)}>
                      Resume
                    </button>
                    <button type="button" className="v2-btn" onClick={() => abandonThought(t.id)}>
                      Abandon
                    </button>
                  </div>
                </Glass>
              );
            })}
          </div>
        )}
        <div className="v2-chat-log">
          {messages.map((m) => (
            <div key={m.id} className={`v2-chat-row v2-chat-row--${m.role}`}>
              <div className="v2-chat-role" aria-hidden="true">
                <Orb size={22} mode={m.role === 'user' ? 'observing' : 'idle'} />
              </div>
              <div className="v2-chat-body">
                {m.type === 'sdui' ? (
                  <SduiRenderer
                    tree={m.sdui}
                    onAction={(action_id, value) => sendUiEvent(socket, {
                      screen_id: m.screen_id || m.id,
                      action_id,
                      value,
                    })}
                  />
                ) : m.type === 'permission_request' ? (
                  <PermissionCard
                    path={m.path}
                    operation={m.operation}
                    reason={m.reason}
                    onAllow={() => respondToPermission(m.requestId, true)}
                    onDeny={() => respondToPermission(m.requestId, false)}
                  />
                ) : m.type === 'permission_request_settled' ? (
                  <div className="v2-chat-perm v2-chat-perm--settled">
                    {m.granted ? `Granted access to ${m.path || 'requested folder'}.`
                      : `Denied access to ${m.path || 'requested folder'}.`}
                  </div>
                ) : (
                  <>
                    {m.text}
                    {m.tools?.length > 0 && (
                      <ToolTrace
                        tools={m.tools}
                        expanded={!!expandedTraces[m.id]}
                        onToggle={() => toggleTrace(m.id)}
                      />
                    )}
                  </>
                )}
              </div>
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

      {pendingAttachments.length > 0 && (
        <div className="v2-chat-attachment-chips" role="list" aria-label="Pending attachments">
          {pendingAttachments.map((att) => (
            <span key={att.upload_id} className="v2-chat-attachment-chip" role="listitem">
              <FileText size={14} aria-hidden="true" />
              <span className="v2-chat-attachment-chip__name" title={att.filename}>
                {att.filename}
              </span>
              <button
                type="button"
                className="v2-chat-attachment-chip__remove"
                onClick={() => removeAttachment(att.upload_id)}
                aria-label={`Remove ${att.filename}`}
              >
                <X size={12} />
              </button>
            </span>
          ))}
          {uploading && <span className="v2-chat-attachment-chip v2-chat-attachment-chip--loading">uploading…</span>}
        </div>
      )}
      {uploadError && (
        <div className="v2-chat-upload-error" role="alert">{uploadError}</div>
      )}

      <Glass
        as="form"
        level={2}
        radius="pill"
        padding="sm"
        className={`v2-chat-composer${dragOver ? ' v2-chat-composer--dragover' : ''}`}
        onSubmit={submit}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <button
          type="button"
          className="v2-chat-attach"
          onClick={() => fileInputRef.current && fileInputRef.current.click()}
          aria-label="Attach file"
          disabled={state !== 'open' || !chatReady || uploading}
        >
          <Paperclip size={18} aria-hidden="true" />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={onFilePick}
          style={{ display: 'none' }}
          aria-hidden="true"
        />
        <input
          className="v2-chat-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPaste={onPaste}
          placeholder={!chatReady ? 'Loading conversation…' : state === 'open' ? 'Ask FERAL…' : 'Reconnecting…'}
          disabled={state !== 'open' || !chatReady}
        />
        <button
          type="button"
          className={`v2-chat-mic${voice?.active ? ' v2-chat-mic--active' : ''}`}
          onClick={onMicClick}
          aria-label={voice?.active ? 'Stop voice mode' : 'Start voice mode'}
          aria-pressed={!!voice?.active}
          disabled={state !== 'open' || !chatReady}
          title={voice?.active ? `Voice active (${voice.provider || 'realtime'})` : 'Hold a conversation by voice'}
        >
          {voice?.active ? <MicOff size={18} aria-hidden="true" /> : <Mic size={18} aria-hidden="true" />}
        </button>
        <button type="submit" className="v2-chat-send" disabled={!input.trim() || state !== 'open' || !chatReady} aria-label="Send">Send</button>
      </Glass>

      {paneOpen === 'threads' && (
        <ThreadsPane
          onClose={() => setPaneOpen(null)}
          onOpenConversation={async (conversationId) => {
            if (thread?.loadConversation) {
              const ok = await thread.loadConversation(conversationId);
              if (ok) setPaneOpen(null);
              return;
            }
            try {
              const d = await apiJson(`/api/conversations/${encodeURIComponent(conversationId)}`);
              const msgs = (d.messages || []).map((m) => ({ id: m.id || newId(), role: m.role, text: m.content || m.text || '' }));
              setMessages(msgs);
              setPaneOpen(null);
            } catch {
              /* silent */
            }
          }}
          onStartNewConversation={async () => {
            if (thread?.startNewConversation) {
              await thread.startNewConversation();
              setPaneOpen(null);
              return;
            }
            try {
              const r = await apiFetch('/api/conversations/new', { method: 'POST' });
              if (r.ok) {
                setMessages([{ id: 'hello', role: 'assistant', text: 'New thread started. What do you need?' }]);
                setPaneOpen(null);
              }
            } catch {
              /* silent */
            }
          }}
        />
      )}
      {paneOpen === 'snapshots' && <SnapshotsPane onClose={() => setPaneOpen(null)} messages={messages} onRestore={(msgs) => { setMessages(msgs); setPaneOpen(null); }} />}
    </div>
  );
}

function PermissionCard({ path, operation, reason, onAllow, onDeny }) {
  const verb = operation === 'write' ? 'write to' : operation === 'read' ? 'read from' : 'access';
  return (
    <Glass level={1} radius="md" padding="sm" className="v2-chat-perm">
      <div className="v2-chat-perm-head">
        <strong>FERAL needs permission to {verb}:</strong>
        <code className="v2-chat-perm-path">{path || '(unknown path)'}</code>
      </div>
      {reason && <div className="v2-chat-perm-reason">{reason}</div>}
      <div className="v2-chat-perm-actions">
        <button type="button" className="v2-btn v2-btn--primary" onClick={onAllow}>
          Allow
        </button>
        <button type="button" className="v2-btn" onClick={onDeny}>
          Deny
        </button>
      </div>
      <div className="v2-chat-perm-hint v2-p v2-p--muted">
        Allowing grants persistent {operation === 'write' ? 'read+write' : 'read'} access
        until you revoke it (Settings → Workspace grants, or
        <code style={{ marginLeft: 4 }}>feral grant revoke {path || '<path>'}</code>).
      </div>
    </Glass>
  );
}

function ToolTrace({ tools, expanded, onToggle }) {
  const failures = tools.filter((t) => t.success === false).length;
  return (
    <div className="v2-chat-trace">
      <button
        type="button"
        className="v2-chat-trace-toggle"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <ChevronRight size={13} className={expanded ? 'is-open' : ''} />
        <span>{failures ? `used ${tools.length} tools, ${failures} failed` : `used ${tools.length} ${tools.length === 1 ? 'tool' : 'tools'}`}</span>
      </button>
      {expanded && (
        <div className="v2-chat-trace-list">
          {tools.map((tool) => (
            <div key={tool.key} className="v2-chat-trace-row">
              <span className={`v2-chat-trace-dot${tool.success === false ? ' is-error' : ''}`} />
              <span className="v2-chat-trace-label">{tool.label}</span>
              {tool.latency_ms > 0 && (
                <span className="v2-chat-trace-meta">{Math.round(tool.latency_ms)}ms</span>
              )}
              {tool.error && <span className="v2-chat-trace-error">{tool.error}</span>}
              {tool.args_preview && <code className="v2-chat-trace-args">{tool.args_preview}</code>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ThreadsPane({ onClose, onOpenConversation, onStartNewConversation }) {
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
      if (onOpenConversation) await onOpenConversation(id);
    } finally {
      refresh();
    }
  };

  const startNew = async () => {
    try {
      if (onStartNewConversation) await onStartNewConversation();
    } finally {
      refresh();
    }
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
