import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { SduiRenderer } from './components/SduiRenderer';
import { Activity, Mic, MicOff, Send, Brain, Wifi, WifiOff, Zap, Settings, AlertTriangle, Phone, Camera, CameraOff, BookOpen, RefreshCw, Search, ListChecks, GitBranch, RotateCcw, BookmarkPlus, MessageSquarePlus, History, Trash2, ChevronLeft, Sparkles, ChevronDown, ChevronUp } from 'lucide-react';
import { WS_URL, API_BASE } from './config';
import { RealtimeVoiceEngine } from './lib/voiceRealtime';
import { VisionCapture } from './lib/visionCapture';

function SkillProposalCard({ msg, onDecision, busy }) {
  const [expanded, setExpanded] = useState(false);
  const resolved = msg.proposalStatus !== 'pending' && msg.proposalStatus !== 'busy';
  const name = msg.manifest?.brand?.name || msg.manifest?.skill_id || 'Generated Skill';
  const epCount = msg.manifest?.endpoints?.length || 0;

  return (
    <div className="bg-asos-assistant border border-asos-border rounded-xl px-3 py-2">
      <div className="flex items-center gap-2">
        <Zap size={12} className="text-asos-accent flex-shrink-0" />
        <span className="text-[12px] font-semibold text-asos-text truncate flex-1">{name}</span>
        <span className="text-[10px] text-asos-text-muted font-mono flex-shrink-0">{epCount} ep</span>
        {!resolved && (
          <>
            <button
              onClick={() => onDecision(msg.proposal_id, msg.manifest?.skill_id, 'approve')}
              disabled={busy !== ''}
              className="px-2 py-0.5 text-[10px] font-medium rounded bg-emerald-500/15 border border-emerald-500/25 text-emerald-400 hover:bg-emerald-500/25 disabled:opacity-40 transition"
            >
              Approve
            </button>
            <button
              onClick={() => onDecision(msg.proposal_id, msg.manifest?.skill_id, 'reject')}
              disabled={busy !== ''}
              className="px-2 py-0.5 text-[10px] font-medium rounded bg-rose-500/15 border border-rose-500/25 text-rose-400 hover:bg-rose-500/25 disabled:opacity-40 transition"
            >
              Reject
            </button>
          </>
        )}
        {resolved && (
          <span className={`text-[10px] font-medium ${
            msg.proposalStatus === 'approved' ? 'text-emerald-400' : msg.proposalStatus === 'rejected' ? 'text-rose-400' : 'text-amber-400'
          }`}>
            {msg.proposalStatus === 'approved' ? 'Registered' : msg.proposalStatus === 'rejected' ? 'Rejected' : msg.proposalError || 'Error'}
          </span>
        )}
        <button onClick={() => setExpanded(v => !v)} className="p-0.5 text-asos-text-muted hover:text-asos-text transition">
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
      </div>
      {expanded && (
        <div className="mt-1.5 pt-1.5 border-t border-asos-border/50 space-y-1">
          {msg.reason && <div className="text-[11px] text-asos-text-muted">Reason: {msg.reason}</div>}
          <div className="text-[11px] text-asos-text-secondary">{msg.manifest?.description || 'No description'}</div>
          <div className="text-[10px] text-asos-text-muted font-mono">{msg.manifest?.skill_id || 'unknown'}</div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [inputText, setInputText] = useState('');
  const [hr, setHr] = useState(null);
  const [isRecording, setIsRecording] = useState(false);
  const [voiceMode, setVoiceMode] = useState('off');
  const [transcript, setTranscript] = useState('');
  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [llmStatus, setLlmStatus] = useState(null);
  const [cameraOn, setCameraOn] = useState(false);
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
  const [activeFlowCount, setActiveFlowCount] = useState(0);
  const [agentRuntime, setAgentRuntime] = useState({
    multi_agent_enabled: false,
    multi_agent_ready: false,
    active_subagents: 0,
    pending_confirmations: 0,
  });
  const [skillProposalBusy, setSkillProposalBusy] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [sessionSnapshots, setSessionSnapshots] = useState([]);
  const [sessionPanelOpen, setSessionPanelOpen] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionBusy, setSessionBusy] = useState('');
  const [sessionBranchName, setSessionBranchName] = useState('main');
  const [threadsOpen, setThreadsOpen] = useState(false);
  const [threads, setThreads] = useState([]);
  const [currentThreadId, setCurrentThreadId] = useState('');
  const [threadsDirty, setThreadsDirty] = useState(false);
  const [learnedNotice, setLearnedNotice] = useState(null);
  const [permissionRequest, setPermissionRequest] = useState(null);
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const voiceEngineRef = useRef(null);
  const visionRef = useRef(null);
  const chunkIndexRef = useRef(0);
  const streamBufferRef = useRef('');
  const greetingReceivedRef = useRef(false);
  const suppressDirtyRef = useRef(false);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/dashboard`);
        const data = await res.json();
        const heartRate = data?.health?.heart_rate;
        if (heartRate) setHr(heartRate);
      } catch { /* no health data available */ }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  useEffect(() => {
    connect();
    fetch(`${API_BASE}/api/llm/status`).then(r => r.json()).then(setLlmStatus).catch(() => {});
    restoreLastThread();
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  useEffect(() => {
    const fetchActiveFlows = async () => {
      try {
        const [running, waiting] = await Promise.all([
          fetch(`${API_BASE}/api/taskflows?status=running&limit=100`).then(r => r.json()),
          fetch(`${API_BASE}/api/taskflows?status=waiting&limit=100`).then(r => r.json()),
        ]);
        const count = (running.flows?.length || 0) + (waiting.flows?.length || 0);
        setActiveFlowCount(count);
      } catch {
        setActiveFlowCount(0);
      }
    };
    fetchActiveFlows();
    const iv = setInterval(fetchActiveFlows, 4000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const fetchRuntimeStatus = async () => {
      try {
        const data = await fetch(`${API_BASE}/api/system/info`).then(r => r.json());
        setAgentRuntime(data.orchestrator || {
          multi_agent_enabled: false,
          multi_agent_ready: false,
          active_subagents: 0,
          pending_confirmations: 0,
        });
      } catch {
        setAgentRuntime({
          multi_agent_enabled: false,
          multi_agent_ready: false,
          active_subagents: 0,
          pending_confirmations: 0,
        });
      }
    };
    fetchRuntimeStatus();
    const iv = setInterval(fetchRuntimeStatus, 4000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (wikiOpen) {
      fetchWikiPages(wikiQuery);
    }
  }, [wikiOpen, wikiQuery]);

  useEffect(() => {
    if (!learnedNotice) return undefined;
    const timer = setTimeout(() => setLearnedNotice(null), 7000);
    return () => clearTimeout(timer);
  }, [learnedNotice]);

  useEffect(() => {
    if (sessionPanelOpen && sessionId) {
      fetchSessionSnapshots();
    }
  }, [sessionPanelOpen, sessionId]);

  const connect = () => {
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      setIsConnected(true);
      greetingReceivedRef.current = false;
    };

    ws.onclose = () => {
      setIsConnected(false);
      setTimeout(connect, 3000);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.session_id) {
          setSessionId(msg.session_id);
        }

        if (msg.type === 'sdui') {
          setIsThinking(false);
          setMessages(prev => [...prev, { role: 'assistant', type: 'sdui', payload: msg.payload.root }]);
        } else if (msg.type === 'text_response') {
          setIsThinking(false);
          const text = msg.payload?.text || '';
          if (text === 'THEORA Brain connected. How can I help?') {
            if (!greetingReceivedRef.current) {
              greetingReceivedRef.current = true;
              setMessages(prev => [...prev, { role: 'assistant', type: 'text', content: text }]);
            }
            return;
          }
          setMessages(prev => [...prev, { role: 'assistant', type: 'text', content: text }]);
        } else if (msg.type === 'stream_delta') {
          setIsThinking(false);
          if (msg.payload.is_final) {
            const finalText = streamBufferRef.current;
            if (finalText) {
              setMessages(prev => [...prev, { role: 'assistant', type: 'text', content: finalText }]);
            }
            streamBufferRef.current = '';
            setStreamingText('');
            setIsStreaming(false);
          } else {
            streamBufferRef.current += msg.payload.delta;
            setStreamingText(streamBufferRef.current);
            setIsStreaming(true);
          }
        } else if (msg.type === 'transcript') {
          const role = msg.payload.role || (msg.payload.text?.startsWith('[user] ') ? 'user' : 'assistant');
          const normalizedText =
            role === 'user' && msg.payload.text?.startsWith('[user] ')
              ? msg.payload.text.slice(7)
              : msg.payload.text;
          setTranscript(normalizedText);
          if (!msg.payload.is_partial) {
            setMessages(prev => [...prev, { role, type: 'text', content: normalizedText, source: 'voice' }]);
            setTranscript('');
          }
        } else if (msg.type === 'tts_chunk') {
          playTTSChunk(msg.payload);
        } else if (msg.type === 'audio_response' || msg.type === 'audio_delta') {
          if (voiceEngineRef.current?.active) {
            voiceEngineRef.current.handleAudioResponse(msg.payload);
          }
        } else if (msg.type === 'speech_started') {
          if (voiceEngineRef.current?.active) {
            voiceEngineRef.current.handleSpeechStarted();
          }
        } else if (msg.type === 'voice_config_ack') {
          console.log("Voice config acknowledged:", msg.payload);
        } else if (msg.type === 'skill_proposal') {
          const manifest = msg.payload?.manifest || {};
          const proposalId = `${manifest.skill_id || 'generated'}:${Date.now()}`;
          setMessages(prev => [
            ...prev,
            {
              role: 'assistant',
              type: 'skill_proposal',
              proposal_id: proposalId,
              proposalStatus: 'pending',
              reason: msg.payload?.reason || '',
              manifest,
            },
          ]);
        } else if (msg.type === 'capability_learned') {
          const payload = msg.payload || {};
          setLearnedNotice({
            name: payload.name || payload.skill_id || 'New capability',
            mode: payload.mode || 'ready',
            message: payload.message || 'New capability learned.',
          });
        } else if (msg.type === 'permission_request') {
          const payload = msg.payload || {};
          setPermissionRequest({
            request_id: payload.request_id,
            path: payload.path,
            operation: payload.operation || 'read',
            reason: payload.reason || '',
          });
        }
      } catch (e) {
        console.error("Message error:", e);
      }
    };

    wsRef.current = ws;
  };

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
        if (!detail.error) {
          setWikiSelected((prev) => prev || detail);
        }
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

  const historyToMessages = (history = []) => {
    return (history || [])
      .filter((h) => h && ['user', 'assistant', 'system', 'tool'].includes(h.role))
      .map((h) => {
        const content = typeof h.content === 'string'
          ? h.content
          : JSON.stringify(h.content || {});
        return {
          role: h.role === 'tool' ? 'assistant' : h.role,
          type: 'text',
          content,
        };
      });
  };

  async function fetchSessionSnapshots() {
    if (!sessionId) return;
    setSessionLoading(true);
    try {
      const data = await fetch(
        `${API_BASE}/api/session/snapshots?session_id=${encodeURIComponent(sessionId)}&limit=50`,
      ).then(r => r.json());
      setSessionSnapshots(data.snapshots || []);
    } catch (e) {
      console.error('Snapshot list failed:', e);
    } finally {
      setSessionLoading(false);
    }
  }

  const createSnapshot = async () => {
    if (!sessionId) return;
    setSessionBusy('snapshot');
    try {
      await fetch(`${API_BASE}/api/session/snapshot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          label: `manual ${new Date().toLocaleString()}`,
          branch_name: sessionBranchName || 'main',
        }),
      });
      await fetchSessionSnapshots();
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: 'Session snapshot saved.' }]);
    } catch (e) {
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Snapshot failed: ${e.message}` }]);
    } finally {
      setSessionBusy('');
    }
  };

  const restoreSnapshot = async (snapshotId) => {
    if (!sessionId || !snapshotId) return;
    if (!window.confirm('Restore this snapshot into the current session?')) return;
    setSessionBusy(`restore:${snapshotId}`);
    try {
      const detail = await fetch(`${API_BASE}/api/session/snapshots/${encodeURIComponent(snapshotId)}`).then(r => r.json());
      const restored = await fetch(`${API_BASE}/api/session/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          snapshot_id: snapshotId,
          session_id: sessionId,
          as_new_session: false,
          label: `restore ${snapshotId}`,
        }),
      }).then(r => r.json());

      if (!restored.error && !detail.error) {
        setMessages([
          ...historyToMessages(detail.history || []),
          { role: 'system', type: 'text', content: `Restored snapshot ${snapshotId}` },
        ]);
        setSessionBranchName(detail.branch_name || 'main');
        await fetchSessionSnapshots();
      } else {
        setMessages(prev => [...prev, { role: 'system', type: 'text', content: restored.error || detail.error || 'Restore failed' }]);
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Restore failed: ${e.message}` }]);
    } finally {
      setSessionBusy('');
    }
  };

  const branchFromSnapshot = async (snapshotId) => {
    if (!sessionId || !snapshotId) return;
    setSessionBusy(`branch:${snapshotId}`);
    try {
      const branchName = (sessionBranchName || `branch-${Date.now()}`).trim();
      const detail = await fetch(`${API_BASE}/api/session/snapshots/${encodeURIComponent(snapshotId)}`).then(r => r.json());
      const branched = await fetch(`${API_BASE}/api/session/branch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          snapshot_id: snapshotId,
          branch_name: branchName,
          target_session_id: sessionId,
          label: `branch from ${snapshotId}`,
        }),
      }).then(r => r.json());

      if (!branched.error && !detail.error) {
        setMessages([
          ...historyToMessages(detail.history || []),
          { role: 'system', type: 'text', content: `Branched session to "${branchName}" from ${snapshotId}` },
        ]);
        setSessionBranchName(branchName);
        await fetchSessionSnapshots();
      } else {
        setMessages(prev => [...prev, { role: 'system', type: 'text', content: branched.error || detail.error || 'Branch failed' }]);
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Branch failed: ${e.message}` }]);
    } finally {
      setSessionBusy('');
    }
  };

  const fetchThreads = async () => {
    try {
      const data = await fetch(`${API_BASE}/api/conversations?limit=50`).then(r => r.json());
      setThreads(data.conversations || []);
    } catch { /* ignore */ }
  };

  const createConversationThread = async () => {
    try {
      const data = await fetch(`${API_BASE}/api/conversations/new`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }).then(r => r.json());
      if (data.id) return data.id;
    } catch { /* ignore */ }
    return `thread-${Date.now()}`;
  };

  const saveCurrentThread = useCallback(async (msgs) => {
    if (!currentThreadId || !msgs || msgs.length < 2) return;
    try {
      await fetch(`${API_BASE}/api/conversations/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: currentThreadId, messages: msgs }),
      });
      setThreadsDirty(false);
      try { localStorage.setItem('theora-last-thread', currentThreadId); } catch {}
    } catch { /* ignore */ }
  }, [currentThreadId]);

  const restoreLastThread = async ({ force = false } = {}) => {
    try {
      if (!force && messages.length > 0) return;
      const lastId = localStorage.getItem('theora-last-thread');
      if (lastId) {
        const data = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(lastId)}`).then(r => r.json());
        if (data.messages && data.messages.length > 0) {
          suppressDirtyRef.current = true;
          setMessages(data.messages);
          setCurrentThreadId(lastId);
          setThreadsDirty(false);
          return;
        }
      }
      const list = await fetch(`${API_BASE}/api/conversations?limit=1`).then(r => r.json());
      const recent = (list.conversations || [])[0];
      if (recent?.id) {
        const data = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(recent.id)}`).then(r => r.json());
        if (data.messages && data.messages.length > 0) {
          suppressDirtyRef.current = true;
          setMessages(data.messages);
          setCurrentThreadId(recent.id);
          setThreadsDirty(false);
        }
      }
    } catch { /* fresh start */ }
  };

  useEffect(() => {
    const handleStorage = (event) => {
      if (event.key !== 'theora-last-thread') return;
      if (!event.newValue || event.newValue === currentThreadId) return;
      if (messages.length > 0 || threadsDirty) return;
      restoreLastThread({ force: false });
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, [currentThreadId, messages.length, threadsDirty]);

  useEffect(() => {
    if (threadsDirty && messages.length >= 2) {
      const timer = setTimeout(() => saveCurrentThread(messages), 2000);
      return () => clearTimeout(timer);
    }
  }, [threadsDirty, messages, saveCurrentThread]);

  useEffect(() => {
    if (!currentThreadId) return;
    if (suppressDirtyRef.current) {
      suppressDirtyRef.current = false;
      return;
    }
    if (messages.length > 0) {
      setThreadsDirty(true);
    }
  }, [messages.length, currentThreadId]);

  useEffect(() => {
    if (!currentThreadId && sessionId) {
      setCurrentThreadId(sessionId);
    }
  }, [sessionId]);

  useEffect(() => {
    const handleBeforeUnload = () => {
      if (currentThreadId && messages.length >= 2) {
        const payload = JSON.stringify({ id: currentThreadId, messages });
        navigator.sendBeacon(`${API_BASE}/api/conversations/save`, new Blob([payload], { type: 'application/json' }));
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [currentThreadId, messages]);

  const loadThread = async (threadId) => {
    try {
      if (threadId !== currentThreadId && currentThreadId && threadsDirty && messages.length >= 2) {
        await saveCurrentThread(messages);
      }
      const data = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(threadId)}`).then(r => r.json());
      if (data.messages) {
        suppressDirtyRef.current = true;
        setMessages(data.messages);
        setCurrentThreadId(threadId);
        setThreadsDirty(false);
        setThreadsOpen(false);
        try { localStorage.setItem('theora-last-thread', threadId); } catch {}
      }
    } catch { /* ignore */ }
  };

  const startNewThread = async () => {
    if (messages.length >= 2 && currentThreadId) {
      await saveCurrentThread(messages);
    }
    const threadId = await createConversationThread();
    suppressDirtyRef.current = true;
    setMessages([]);
    setCurrentThreadId(threadId);
    setThreadsDirty(false);
    try { localStorage.setItem('theora-last-thread', threadId); } catch {}
    setThreadsOpen(false);
    await fetchThreads();
  };

  const deleteThread = async (threadId) => {
    try {
      await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(threadId)}`, { method: 'DELETE' });
      setThreads(prev => prev.filter(t => t.id !== threadId));
      if (currentThreadId === threadId) {
        setMessages([]);
        setCurrentThreadId('');
      }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    if (threadsOpen) fetchThreads();
  }, [threadsOpen]);

  const playTTSChunk = useCallback((chunk) => {
    try {
      const audioData = atob(chunk.data_b64);
      const arrayBuffer = new ArrayBuffer(audioData.length);
      const view = new Uint8Array(arrayBuffer);
      for (let i = 0; i < audioData.length; i++) view[i] = audioData.charCodeAt(i);

      const blob = new Blob([arrayBuffer], { type: 'audio/mp3' });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.play().catch(() => {});
      audio.onended = () => URL.revokeObjectURL(url);
    } catch (e) {
      console.error("TTS playback error:", e);
    }
  }, []);

  const handleSend = (e) => {
    e.preventDefault();
    if (!inputText.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    setMessages(prev => [...prev, { role: 'user', type: 'text', content: inputText }]);
    setIsThinking(true);

    const cmd = {
      hop: "client",
      type: "text_command",
      payload: { text: inputText, context: {} }
    };

    wsRef.current.send(JSON.stringify(cmd));
    setInputText('');
  };

  const toggleRecording = async () => {
    if (isRecording) {
      stopRecording();
    } else {
      await startRecording();
    }
  };

  const startRecording = async () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    try {
      const engine = new RealtimeVoiceEngine(wsRef.current);
      voiceEngineRef.current = engine;
      await engine.start();
      setIsRecording(true);
      setVoiceMode('realtime');
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: 'Voice conversation started. Speak naturally — your agent can hear you and use tools.' }]);
    } catch (err) {
      console.error("Voice start failed:", err);
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Mic access denied: ${err.message}` }]);
    }
  };

  const stopRecording = () => {
    if (voiceEngineRef.current) {
      voiceEngineRef.current.stop();
      voiceEngineRef.current = null;
    }
    setIsRecording(false);
    setVoiceMode('off');
  };

  const toggleCamera = async () => {
    if (cameraOn) {
      if (visionRef.current) { visionRef.current.stop(); visionRef.current = null; }
      setCameraOn(false);
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: 'Camera stopped.' }]);
    } else {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      try {
        const vc = new VisionCapture(wsRef.current, 1);
        visionRef.current = vc;
        await vc.start();
        setCameraOn(true);
        setMessages(prev => [...prev, { role: 'system', type: 'text', content: 'Camera active — agent can now see through your webcam.' }]);
      } catch (err) {
        setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Camera error: ${err.message}` }]);
      }
    }
  };

  const handleUIAction = (action_id) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    setMessages(prev => [...prev, { role: 'user', type: 'action', content: `Clicked: ${action_id}` }]);

    const evt = {
      hop: "client",
      type: "ui_event",
      payload: { screen_id: "main", action_id, event: "tap" }
    };
    wsRef.current.send(JSON.stringify(evt));
  };

  const handlePermissionDecision = (reqId, granted) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    const actionPrefix = granted ? 'perm_grant_' : 'perm_deny_';
    wsRef.current.send(JSON.stringify({
      hop: 'client',
      type: 'ui_event',
      payload: { screen_id: 'main', action_id: `${actionPrefix}${reqId}`, event: 'tap' },
    }));
    setPermissionRequest(null);
  };

  const handleSkillProposalDecision = async (proposalId, skillId, action) => {
    if (!skillId) return;
    const busyKey = `${proposalId}:${action}`;
    setSkillProposalBusy(busyKey);
    setMessages(prev => prev.map(msg => (
      msg.type === 'skill_proposal' && msg.proposal_id === proposalId
        ? { ...msg, proposalStatus: 'busy' }
        : msg
    )));

    try {
      const endpoint = action === 'approve' ? 'approve' : 'reject';
      const res = await fetch(`${API_BASE}/api/skills/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skillId }),
      });
      const data = await res.json();
      const ok = !!data.ok;

      setMessages(prev => [
        ...prev.map(msg => (
          msg.type === 'skill_proposal' && msg.proposal_id === proposalId
            ? {
              ...msg,
              proposalStatus: ok ? (action === 'approve' ? 'approved' : 'rejected') : 'error',
              proposalError: ok ? '' : (data.error || `Failed to ${action} skill`),
            }
            : msg
        )),
        {
          role: 'system',
          type: 'text',
          content: ok
            ? `Skill ${action}d: ${skillId}`
            : `Skill ${action} failed: ${data.error || 'unknown error'}`,
        },
      ]);
    } catch (e) {
      setMessages(prev => [
        ...prev.map(msg => (
          msg.type === 'skill_proposal' && msg.proposal_id === proposalId
            ? { ...msg, proposalStatus: 'error', proposalError: e.message || 'request failed' }
            : msg
        )),
        { role: 'system', type: 'text', content: `Skill ${action} failed: ${e.message || 'request failed'}` },
      ]);
    } finally {
      setSkillProposalBusy('');
    }
  };

  return (
    <div className="flex flex-col h-full max-w-full lg:max-w-3xl mx-auto bg-asos-bg relative overflow-hidden">
      {/* Top Bar */}
      <div className="flex-shrink-0 h-14 bg-asos-surface/80 border-b border-asos-border z-10 flex items-center justify-between px-4 backdrop-blur-xl">
        <div className="flex items-center gap-2.5">
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]' : 'bg-red-400'}`} />
          <span className="font-semibold text-sm text-asos-text">THEORA</span>
          {agentRuntime.multi_agent_enabled && (
            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${
              agentRuntime.multi_agent_ready
                ? 'text-cyan-300 border-cyan-500/40 bg-cyan-500/10'
                : 'text-amber-300 border-amber-500/40 bg-amber-500/10'
            }`}>
              MA {agentRuntime.multi_agent_ready ? 'ON' : 'INIT'}
            </span>
          )}
          {agentRuntime.active_subagents > 0 && (
            <span className="text-[10px] px-2 py-0.5 rounded-full border text-violet-300 border-violet-500/40 bg-violet-500/10">
              SUB {agentRuntime.active_subagents}
            </span>
          )}
          {isRecording && (
            <span className="ml-2 text-emerald-400 text-[11px] font-medium animate-pulse flex items-center gap-1">
              <Phone size={11} />
              LIVE
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {hr && (
            <div className="flex items-center gap-1.5 text-rose-400 mr-2">
              <Activity size={14} className="animate-pulse" />
              <span className="font-mono text-xs">{hr}</span>
            </div>
          )}
          <button
            onClick={() => { void startNewThread(); }}
            className="p-2 rounded-lg text-asos-text-muted hover:text-asos-accent hover:bg-asos-accent-dim transition"
            title="Start New Chat"
          >
            <MessageSquarePlus size={15} />
          </button>
          <button
            onClick={() => { setThreadsOpen(v => !v); if (!threadsOpen) fetchThreads(); }}
            className={`p-2 rounded-lg transition ${threadsOpen ? 'text-asos-accent bg-asos-accent-dim' : 'text-asos-text-muted hover:text-asos-text hover:bg-asos-card-hover'}`}
            title="Conversations"
          >
            <History size={15} />
          </button>
          <button
            onClick={() => setWikiOpen(v => !v)}
            className={`p-2 rounded-lg transition ${wikiOpen ? 'text-asos-accent bg-asos-accent-dim' : 'text-asos-text-muted hover:text-asos-text hover:bg-asos-card-hover'}`}
            title="Memory Wiki"
          >
            <BookOpen size={15} />
          </button>
          <button
            onClick={() => navigate('/taskflows')}
            className="relative p-2 rounded-lg text-asos-text-muted hover:text-asos-text hover:bg-asos-card-hover transition"
            title="TaskFlows"
          >
            <ListChecks size={15} />
            {activeFlowCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 rounded-full bg-asos-accent text-[9px] leading-4 text-white text-center font-medium">
                {activeFlowCount}
              </span>
            )}
          </button>
          <button
            onClick={() => {
              setSessionPanelOpen((v) => !v);
              if (!sessionPanelOpen && sessionId) fetchSessionSnapshots();
            }}
            disabled={!sessionId}
            className={`p-2 rounded-lg transition ${
              sessionPanelOpen
                ? 'text-asos-accent bg-asos-accent-dim'
                : 'text-asos-text-muted hover:text-asos-text hover:bg-asos-card-hover'
            } disabled:opacity-40`}
            title="Session snapshots"
          >
            <GitBranch size={15} />
          </button>
          <button onClick={() => navigate('/settings')} className="p-2 rounded-lg text-asos-text-muted hover:text-asos-text hover:bg-asos-card-hover transition">
            <Settings size={15} />
          </button>
        </div>
      </div>

      {/* Transcript overlay */}
      {transcript && (
        <div className="flex-shrink-0 px-4 py-2 bg-asos-accent-dim border-b border-asos-accent/20">
          <span className="text-sm italic text-asos-text-secondary">{transcript}</span>
        </div>
      )}

      {learnedNotice && (
        <div className="flex-shrink-0 px-4 py-2 border-b border-emerald-500/20 bg-emerald-500/10 text-emerald-300 flex items-center gap-2 text-xs">
          <Sparkles size={13} />
          <span className="font-medium">{learnedNotice.name}</span>
          <span className="opacity-80">
            {learnedNotice.mode === 'ready' ? 'is ready to use.' : 'was generated and is pending approval.'}
          </span>
        </div>
      )}

      {permissionRequest && (
        <div className="flex-shrink-0 px-4 py-3 border-b border-amber-500/20 bg-amber-500/10">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="text-amber-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-amber-300">Permission Request</div>
              <div className="text-[11px] text-asos-text-secondary mt-0.5 break-all font-mono">{permissionRequest.path}</div>
              <div className="text-[11px] text-asos-text-muted mt-0.5">{permissionRequest.reason}</div>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={() => handlePermissionDecision(permissionRequest.request_id, true)}
                  className="px-3 py-1 text-[11px] font-medium rounded bg-emerald-500/15 border border-emerald-500/25 text-emerald-400 hover:bg-emerald-500/25 transition"
                >
                  Grant Access
                </button>
                <button
                  onClick={() => handlePermissionDecision(permissionRequest.request_id, false)}
                  className="px-3 py-1 text-[11px] font-medium rounded bg-rose-500/15 border border-rose-500/25 text-rose-400 hover:bg-rose-500/25 transition"
                >
                  Deny
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* No-LLM Banner */}
      {llmStatus && !llmStatus.available && (
        <div className="flex-shrink-0 px-4 py-2 bg-amber-500/10 border-b border-amber-500/20 flex items-center gap-2">
          <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
          <span className="text-xs text-amber-300">
            No LLM connected. Set <code className="bg-black/30 px-1.5 py-0.5 rounded text-[10px] font-mono">OPENAI_API_KEY</code> or start Ollama.
          </span>
        </div>
      )}

      {wikiOpen && (
        <div className="absolute inset-0 z-20 bg-asos-bg/95 backdrop-blur-md flex flex-col">
          <div className="pt-16 px-4 pb-3 border-b border-asos-border">
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-2">
                <BookOpen size={16} className="text-asos-accent" />
                <span className="text-sm font-semibold">Memory Wiki</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setWikiIngestOpen(v => !v)}
                  className={`text-xs px-2 py-1 rounded border flex items-center gap-1 ${
                    wikiIngestOpen
                      ? 'bg-asos-accent/20 border-asos-accent text-asos-accent'
                      : 'bg-asos-card border-asos-border hover:border-asos-accent'
                  }`}
                >
                  Ingest
                </button>
                <button
                  onClick={compileWiki}
                  className="text-xs px-2 py-1 rounded bg-asos-card border border-asos-border hover:border-asos-accent flex items-center gap-1"
                  disabled={wikiLoading}
                >
                  <RefreshCw size={12} className={wikiLoading ? 'animate-spin' : ''} />
                  Compile
                </button>
              </div>
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={wikiQuery}
                onChange={(e) => setWikiQuery(e.target.value)}
                placeholder="Search wiki pages..."
                className="flex-1 bg-asos-card border border-asos-border rounded-full px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
              />
              <button
                onClick={() => fetchWikiPages(wikiQuery)}
                className="px-3 py-2 rounded-full bg-asos-card border border-asos-border hover:border-asos-accent"
              >
                <Search size={14} />
              </button>
            </div>
            {wikiIngestOpen && (
              <div className="mt-3 p-3 bg-asos-card border border-asos-border rounded-xl space-y-2">
                <div className="flex gap-2">
                  <select
                    value={wikiIngestType}
                    onChange={(e) => setWikiIngestType(e.target.value)}
                    className="bg-asos-bg border border-asos-border rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-asos-accent"
                  >
                    <option value="repo">Repo</option>
                    <option value="pdf">PDF</option>
                    <option value="text">Text</option>
                  </select>
                  {(wikiIngestType === 'repo' || wikiIngestType === 'pdf') && (
                    <input
                      type="text"
                      value={wikiIngestPath}
                      onChange={(e) => setWikiIngestPath(e.target.value)}
                      placeholder={wikiIngestType === 'repo' ? '/path/to/repo' : '/path/to/file.pdf'}
                      className="flex-1 bg-asos-bg border border-asos-border rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-asos-accent"
                    />
                  )}
                </div>
                {wikiIngestType === 'text' && (
                  <textarea
                    rows={4}
                    value={wikiIngestContent}
                    onChange={(e) => setWikiIngestContent(e.target.value)}
                    placeholder="Paste text to ingest into memory wiki..."
                    className="w-full bg-asos-bg border border-asos-border rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-asos-accent resize-y"
                  />
                )}
                <div className="flex items-center justify-between">
                  <button
                    onClick={ingestWiki}
                    disabled={wikiIngestBusy}
                    className="text-xs px-3 py-1.5 rounded bg-asos-accent text-white hover:bg-asos-accent/90 disabled:opacity-60"
                  >
                    {wikiIngestBusy ? 'Ingesting...' : 'Run Ingest'}
                  </button>
                  {wikiIngestResult && <span className="text-[11px] text-asos-text-secondary">{wikiIngestResult}</span>}
                </div>
              </div>
            )}
          </div>

          <div className="flex-1 grid grid-cols-1 md:grid-cols-2 overflow-hidden">
            <div className="border-r border-asos-border overflow-y-auto">
              {wikiPages.map((page) => (
                <button
                  key={page.id}
                  onClick={() => openWikiPage(page.id)}
                  className={`w-full text-left px-4 py-3 border-b border-asos-border/40 hover:bg-asos-card ${
                    wikiSelected?.id === page.id ? 'bg-asos-card' : ''
                  }`}
                >
                  <div className="text-sm font-medium">{page.title}</div>
                  <div className="text-xs opacity-60">{page.kind} • {page.id}</div>
                </button>
              ))}
              {!wikiPages.length && !wikiLoading && (
                <div className="p-4 text-sm opacity-60">No wiki pages yet. Press Compile.</div>
              )}
            </div>
            <div className="overflow-y-auto p-4">
              {wikiSelected ? (
                <div className="space-y-3">
                  <div className="text-lg font-semibold">{wikiSelected.title}</div>
                  <div className="text-xs opacity-60">{wikiSelected.kind} • {wikiSelected.id}</div>
                  <pre className="whitespace-pre-wrap text-sm leading-relaxed bg-asos-card border border-asos-border rounded-xl p-3">
                    {wikiSelected.body_markdown}
                  </pre>
                </div>
              ) : (
                <div className="text-sm opacity-60">Select a wiki page to view details.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {sessionPanelOpen && (
        <div className="flex-shrink-0 bg-asos-surface border-b border-asos-border max-h-48 overflow-y-auto">
          <div className="px-4 py-2.5 flex items-center justify-between sticky top-0 bg-asos-surface z-10">
            <div className="flex items-center gap-3">
              <span className="text-xs font-medium text-asos-text-secondary">Snapshots</span>
              <span className="text-[10px] font-mono text-asos-text-muted px-2 py-0.5 rounded bg-asos-card border border-asos-border">
                {sessionBranchName}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <input
                value={sessionBranchName}
                onChange={(e) => setSessionBranchName(e.target.value)}
                className="w-20 bg-asos-bg border border-asos-border rounded-md px-2 py-1 text-[10px] font-mono text-asos-text focus:outline-none focus:ring-1 focus:ring-asos-accent"
                placeholder="branch"
              />
              <button
                onClick={createSnapshot}
                disabled={!sessionId || sessionBusy !== ''}
                className="px-2.5 py-1 rounded-md bg-asos-accent/15 border border-asos-accent/25 text-asos-accent text-[11px] font-medium hover:bg-asos-accent/25 disabled:opacity-40 transition flex items-center gap-1"
              >
                <BookmarkPlus size={11} />
                Save
              </button>
              <button
                onClick={fetchSessionSnapshots}
                className="p-1 rounded text-asos-text-muted hover:text-asos-text transition"
                disabled={sessionLoading}
              >
                <RefreshCw size={12} className={sessionLoading ? 'animate-spin' : ''} />
              </button>
            </div>
          </div>
          {(sessionSnapshots || []).map((snap) => (
            <div key={snap.snapshot_id} className="px-4 py-2 border-t border-asos-border/50 flex items-center justify-between gap-2 hover:bg-asos-card-hover transition">
              <div className="min-w-0">
                <span className="text-[11px] font-mono text-asos-text-secondary truncate block">{snap.snapshot_id}</span>
                {snap.label && <span className="text-[10px] text-asos-text-muted">{snap.label}</span>}
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  onClick={() => branchFromSnapshot(snap.snapshot_id)}
                  disabled={sessionBusy !== ''}
                  className="px-2 py-1 text-[10px] rounded-md bg-sky-500/10 border border-sky-500/20 text-sky-400 font-medium disabled:opacity-40 transition hover:bg-sky-500/20"
                >
                  Branch
                </button>
                <button
                  onClick={() => restoreSnapshot(snap.snapshot_id)}
                  disabled={sessionBusy !== ''}
                  className="px-2 py-1 text-[10px] rounded-md bg-amber-500/10 border border-amber-500/20 text-amber-400 font-medium disabled:opacity-40 transition hover:bg-amber-500/20"
                >
                  Restore
                </button>
              </div>
            </div>
          ))}
          {!sessionLoading && !sessionSnapshots.length && (
            <div className="px-4 py-3 text-xs text-asos-text-muted">No snapshots yet. Click Save to create one.</div>
          )}
        </div>
      )}

      {/* Conversation Threads Panel */}
      {threadsOpen && (
        <div className="flex-shrink-0 bg-asos-surface border-b border-asos-border max-h-72 overflow-y-auto">
          <div className="px-4 py-3 flex items-center justify-between sticky top-0 bg-asos-surface z-10 border-b border-asos-border/50">
            <span className="text-sm font-medium text-asos-text">Conversations</span>
            <button
              onClick={startNewThread}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-asos-accent/15 border border-asos-accent/25 text-asos-accent hover:bg-asos-accent/25 transition"
            >
              <MessageSquarePlus size={13} />
              New
            </button>
          </div>
          {threads.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-asos-text-muted">No saved conversations yet. Start chatting and they will auto-save.</div>
          ) : threads.map(t => (
            <div
              key={t.id}
              className={`px-4 py-3 border-b border-asos-border/30 flex items-center gap-3 cursor-pointer transition hover:bg-asos-card-hover ${
                currentThreadId === t.id ? 'bg-asos-accent-dim' : ''
              }`}
              onClick={() => loadThread(t.id)}
            >
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-asos-text truncate">{t.title}</div>
                <div className="text-[11px] text-asos-text-muted truncate mt-0.5">{t.preview || `${t.message_count} messages`}</div>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); deleteThread(t.id); }}
                className="p-1 rounded text-asos-text-muted hover:text-rose-400 hover:bg-rose-400/10 transition flex-shrink-0"
                title="Delete"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Messages View */}
      <div className="flex-1 overflow-y-auto px-3 lg:px-5 py-4 space-y-2.5">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="w-12 h-12 rounded-xl bg-asos-accent-dim flex items-center justify-center">
              <Brain size={24} className="text-asos-accent" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-asos-text-secondary">What can I help you with?</p>
              <p className="text-[11px] text-asos-text-muted mt-0.5">Type a message or start a voice conversation</p>
            </div>
          </div>
        )}
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'user' ? (
              <div className="max-w-[78%] bg-asos-user text-white rounded-2xl rounded-br-sm px-3.5 py-2 shadow-md shadow-asos-user/10">
                {msg.type === 'text' && (
                  <span className="text-[13px] leading-snug">
                    {msg.source === 'voice' && <Mic size={11} className="inline mr-1 opacity-60" />}
                    {msg.content}
                  </span>
                )}
                {msg.type === 'action' && <span className="text-[11px] italic opacity-80">{msg.content}</span>}
              </div>
            ) : msg.role === 'system' ? (
              <div className="w-full flex justify-center">
                <span className="text-[10px] text-asos-text-muted bg-asos-card px-2.5 py-0.5 rounded-full border border-asos-border">{msg.content}</span>
              </div>
            ) : (
              <div className="max-w-[75%]">
                {msg.type === 'text' && (
                  <div className="bg-asos-assistant border border-asos-border rounded-2xl rounded-bl-sm px-3.5 py-2">
                    <span className="text-[13px] leading-snug text-asos-text">
                      {msg.source === 'voice' && <Mic size={11} className="inline mr-1 text-asos-text-muted" />}
                      {msg.content}
                    </span>
                  </div>
                )}
                {msg.type === 'sdui' && (
                  <div className="rounded-xl overflow-hidden">
                    <SduiRenderer node={msg.payload} onAction={handleUIAction} compact />
                  </div>
                )}
                {msg.type === 'skill_proposal' && (
                  <SkillProposalCard
                    msg={msg}
                    onDecision={handleSkillProposalDecision}
                    busy={skillProposalBusy}
                  />
                )}
              </div>
            )}
          </div>
        ))}
        {isStreaming && streamingText && (
          <div className="flex justify-start">
            <div className="max-w-[75%] bg-asos-assistant border border-asos-border rounded-2xl rounded-bl-sm px-3.5 py-2">
              <span className="text-[13px] leading-snug text-asos-text">{streamingText}</span>
              <span className="inline-block w-1 h-3.5 bg-asos-accent rounded-sm animate-pulse ml-0.5 align-middle" />
            </div>
          </div>
        )}
        {isThinking && !isStreaming && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 px-3.5 py-2 bg-asos-assistant border border-asos-border rounded-2xl rounded-bl-sm">
              <div className="flex gap-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-asos-accent animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-asos-accent animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-asos-accent animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
              <span className="text-[11px] text-asos-text-muted">thinking...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Bottom Composer */}
      <div className="flex-shrink-0 p-3 lg:p-4 bg-asos-surface/80 backdrop-blur-xl border-t border-asos-border">
        <div className="mb-2 flex items-center justify-between">
          <button
            type="button"
            onClick={() => { void startNewThread(); }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-asos-accent/15 border border-asos-accent/25 text-asos-accent hover:bg-asos-accent/25 transition"
          >
            <MessageSquarePlus size={12} />
            Start New Chat
          </button>
          <span className="text-[10px] text-asos-text-muted font-mono">
            {currentThreadId ? `thread:${currentThreadId.slice(0, 10)}` : 'thread:pending'}
          </span>
        </div>
        <form onSubmit={handleSend} className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleCamera}
            title={cameraOn ? "Stop camera" : "Start camera"}
            className={`p-2.5 rounded-xl transition-all active:scale-95 flex-shrink-0 ${
              cameraOn
                ? 'bg-sky-500 text-white shadow-lg shadow-sky-500/25'
                : 'bg-asos-card border border-asos-border text-asos-text-muted hover:text-asos-text hover:border-asos-border-bright'
            }`}
          >
            {cameraOn ? <CameraOff size={16} /> : <Camera size={16} />}
          </button>
          <button
            type="button"
            onClick={toggleRecording}
            title={isRecording ? "Stop voice" : "Start voice"}
            className={`p-2.5 rounded-xl transition-all active:scale-95 flex-shrink-0 ${
              isRecording
                ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-500/25 ring-2 ring-emerald-400/30'
                : 'bg-asos-card border border-asos-border text-asos-text-muted hover:text-asos-text hover:border-asos-border-bright'
            }`}
          >
            {isRecording ? <MicOff size={16} /> : <Mic size={16} />}
          </button>
          <div className="flex-1 relative">
            <input
              type="text"
              className="w-full bg-asos-card border border-asos-border rounded-xl pl-4 pr-11 py-2.5 text-sm text-asos-text placeholder-asos-text-muted focus:outline-none focus:ring-1 focus:ring-asos-accent focus:border-asos-accent transition"
              placeholder="Message THEORA..."
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
            />
            <button
              type="submit"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1.5 bg-asos-accent rounded-lg text-white hover:bg-asos-accent/80 transition active:scale-95"
            >
              <Send size={14} />
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
