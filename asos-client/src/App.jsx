import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { SduiRenderer } from './components/SduiRenderer';
import { Activity, Mic, MicOff, Send, Brain, Wifi, WifiOff, Zap, Settings, AlertTriangle, Phone, Camera, CameraOff, BookOpen, RefreshCw, Search, ListChecks, GitBranch, RotateCcw, BookmarkPlus } from 'lucide-react';
import { WS_URL, API_BASE } from './config';
import { RealtimeVoiceEngine } from './lib/voiceRealtime';
import { VisionCapture } from './lib/visionCapture';

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
  const [skillProposalBusy, setSkillProposalBusy] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [sessionSnapshots, setSessionSnapshots] = useState([]);
  const [sessionPanelOpen, setSessionPanelOpen] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionBusy, setSessionBusy] = useState('');
  const [sessionBranchName, setSessionBranchName] = useState('main');
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const voiceEngineRef = useRef(null);
  const visionRef = useRef(null);
  const chunkIndexRef = useRef(0);
  const streamBufferRef = useRef('');
  const greetingReceivedRef = useRef(false);
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
    if (wikiOpen) {
      fetchWikiPages(wikiQuery);
    }
  }, [wikiOpen, wikiQuery]);

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
    <div className="flex flex-col h-full max-w-full lg:max-w-md mx-auto bg-black bg-opacity-80 backdrop-blur-xl relative overflow-hidden">
      {/* Top Bar */}
      <div className="absolute top-0 left-0 right-0 h-16 bg-asos-card border-b border-asos-border z-10 flex items-center justify-between px-4 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-green-500 shadow-[0_0_8px_#22c55e]' : 'bg-red-500'}`} />
          <Brain size={18} className="text-asos-accent" />
          <span className="font-semibold tracking-wider text-sm">THEORA</span>
        </div>
        <div className="flex items-center gap-3">
          {isRecording && (
            <span className="text-green-400 text-xs animate-pulse flex items-center gap-1">
              <Phone size={12} />
              LIVE
            </span>
          )}
          {hr && (
            <div className="flex items-center gap-1.5 text-red-400">
              <Activity size={16} className="animate-pulse" />
              <span className="font-mono text-sm">{hr}</span>
            </div>
          )}
          <button
            onClick={() => setWikiOpen(v => !v)}
            className={`p-1 transition ${wikiOpen ? 'text-asos-accent' : 'text-gray-400 hover:text-white'}`}
            title="Memory Wiki"
          >
            <BookOpen size={16} />
          </button>
          <button
            onClick={() => navigate('/taskflows')}
            className="relative p-1 text-gray-400 hover:text-white transition"
            title="TaskFlows"
          >
            <ListChecks size={16} />
            {activeFlowCount > 0 && (
              <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full bg-asos-accent text-[10px] leading-4 text-white text-center">
                {activeFlowCount}
              </span>
            )}
          </button>
          <button onClick={() => navigate('/settings')} className="p-1 text-gray-400 hover:text-white transition">
            <Settings size={16} />
          </button>
        </div>
      </div>

      {/* Session Toolbar */}
      <div className="absolute top-16 left-0 right-0 z-10 px-3 py-2 bg-black/50 border-b border-asos-border flex items-center gap-2 backdrop-blur-sm">
        <span className="text-[10px] uppercase tracking-wider text-gray-400">Session</span>
        <span className="text-[10px] font-mono text-gray-500 truncate max-w-[90px]">{sessionId || 'connecting'}</span>
        <span className="text-[10px] px-2 py-0.5 rounded-full border border-asos-border bg-asos-card text-gray-300">
          branch: {sessionBranchName}
        </span>
        <input
          value={sessionBranchName}
          onChange={(e) => setSessionBranchName(e.target.value)}
          className="ml-auto w-24 bg-black border border-asos-border rounded px-2 py-1 text-[10px] font-mono focus:outline-none focus:ring-1 focus:ring-asos-accent"
          placeholder="branch"
        />
        <button
          onClick={createSnapshot}
          disabled={!sessionId || sessionBusy !== ''}
          className="px-2 py-1 rounded bg-asos-card border border-asos-border hover:border-asos-accent text-[10px] flex items-center gap-1 disabled:opacity-50"
          title="Create snapshot"
        >
          <BookmarkPlus size={11} />
          Snapshot
        </button>
        <button
          onClick={() => {
            setSessionPanelOpen((v) => !v);
            if (!sessionPanelOpen && sessionId) fetchSessionSnapshots();
          }}
          disabled={!sessionId}
          className={`px-2 py-1 rounded border text-[10px] flex items-center gap-1 ${
            sessionPanelOpen
              ? 'bg-asos-accent/20 border-asos-accent text-asos-accent'
              : 'bg-asos-card border-asos-border text-gray-300 hover:border-asos-accent'
          } disabled:opacity-50`}
          title="Toggle snapshots"
        >
          <GitBranch size={11} />
          Snapshots
        </button>
      </div>

      {/* Transcript overlay */}
      {transcript && (
        <div className="absolute top-24 left-0 right-0 z-10 px-4 py-2 bg-asos-accent bg-opacity-20 backdrop-blur-sm border-b border-asos-accent border-opacity-30">
          <span className="text-sm italic opacity-80">{transcript}</span>
        </div>
      )}

      {/* No-LLM Banner */}
      {llmStatus && !llmStatus.available && (
        <div className="absolute top-24 left-0 right-0 z-[5] px-4 py-2 bg-yellow-500 bg-opacity-15 border-b border-yellow-500 border-opacity-30 flex items-center gap-2">
          <AlertTriangle size={14} className="text-yellow-400 flex-shrink-0" />
          <span className="text-xs text-yellow-300">
            No LLM connected. Set <code className="bg-black bg-opacity-30 px-1 rounded text-[10px]">OPENAI_API_KEY</code> or start Ollama for full conversation.
          </span>
        </div>
      )}

      {wikiOpen && (
        <div className="absolute inset-0 z-20 bg-black/90 backdrop-blur-sm flex flex-col">
          <div className="pt-24 px-4 pb-3 border-b border-asos-border">
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
                    className="bg-black border border-asos-border rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-asos-accent"
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
                      className="flex-1 bg-black border border-asos-border rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-asos-accent"
                    />
                  )}
                </div>
                {wikiIngestType === 'text' && (
                  <textarea
                    rows={4}
                    value={wikiIngestContent}
                    onChange={(e) => setWikiIngestContent(e.target.value)}
                    placeholder="Paste text to ingest into memory wiki..."
                    className="w-full bg-black border border-asos-border rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-asos-accent resize-y"
                  />
                )}
                <div className="flex items-center justify-between">
                  <button
                    onClick={ingestWiki}
                    disabled={wikiIngestBusy}
                    className="text-xs px-3 py-1.5 rounded bg-asos-accent text-white hover:bg-opacity-90 disabled:opacity-60"
                  >
                    {wikiIngestBusy ? 'Ingesting...' : 'Run Ingest'}
                  </button>
                  {wikiIngestResult && <span className="text-[11px] text-gray-300">{wikiIngestResult}</span>}
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
        <div className="absolute top-24 left-0 right-0 z-20 bg-black/90 border-b border-asos-border max-h-56 overflow-y-auto">
          <div className="px-3 py-2 text-[11px] text-gray-400 flex items-center justify-between">
            <span>Session snapshots</span>
            <button
              onClick={fetchSessionSnapshots}
              className="px-2 py-1 rounded bg-asos-card border border-asos-border text-[10px] hover:border-asos-accent"
              disabled={sessionLoading}
            >
              <RefreshCw size={10} className={`inline mr-1 ${sessionLoading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
          {(sessionSnapshots || []).map((snap) => (
            <div key={snap.snapshot_id} className="px-3 py-2 border-t border-asos-border/40">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs">
                  <span className="font-mono text-gray-300">{snap.snapshot_id}</span>
                  <span className="ml-2 text-gray-500">{snap.branch_name || 'main'}</span>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => branchFromSnapshot(snap.snapshot_id)}
                    disabled={sessionBusy !== ''}
                    className="px-2 py-1 text-[10px] rounded bg-blue-500/20 border border-blue-500/30 text-blue-300 disabled:opacity-50"
                    title="Branch into current session"
                  >
                    <GitBranch size={10} className="inline mr-1" />
                    Branch
                  </button>
                  <button
                    onClick={() => restoreSnapshot(snap.snapshot_id)}
                    disabled={sessionBusy !== ''}
                    className="px-2 py-1 text-[10px] rounded bg-yellow-500/20 border border-yellow-500/30 text-yellow-300 disabled:opacity-50"
                    title="Restore into current session"
                  >
                    <RotateCcw size={10} className="inline mr-1" />
                    Restore
                  </button>
                </div>
              </div>
              {snap.label && <div className="text-[10px] text-gray-500 mt-1">{snap.label}</div>}
            </div>
          ))}
          {!sessionLoading && !sessionSnapshots.length && (
            <div className="px-3 py-3 text-xs text-gray-500">No snapshots yet.</div>
          )}
        </div>
      )}

      {/* Messages View */}
      <div className="flex-1 overflow-y-auto px-4 pt-28 pb-28 space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full opacity-40 gap-3">
            <Brain size={48} />
            <span className="text-sm">Say something or type a command</span>
          </div>
        )}
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[90%] ${msg.role === 'user' ? 'bg-asos-accent text-white rounded-2xl rounded-tr-sm px-4 py-2' : ''}`}>
              {msg.type === 'text' && (
                <span>
                  {msg.source === 'voice' && <Mic size={12} className="inline mr-1 opacity-60" />}
                  {msg.content}
                </span>
              )}
              {msg.type === 'action' && <span className="text-xs italic opacity-80">{msg.content}</span>}
              {msg.type === 'sdui' && <SduiRenderer node={msg.payload} onAction={handleUIAction} />}
              {msg.type === 'skill_proposal' && (
                <div className="bg-asos-card border border-asos-border rounded-xl p-3 w-full">
                  <div className="text-xs uppercase tracking-wider text-asos-accent mb-1">Skill Proposal</div>
                  <div className="text-sm font-semibold">{msg.manifest?.brand?.name || msg.manifest?.skill_id || 'Generated Skill'}</div>
                  {msg.reason && <div className="text-xs text-gray-400 mt-1">Reason: {msg.reason}</div>}
                  <div className="text-xs text-gray-300 mt-2">{msg.manifest?.description || 'No description'}</div>
                  <div className="text-[11px] text-gray-500 mt-2 font-mono">
                    {msg.manifest?.skill_id || 'unknown_skill'} • endpoints: {msg.manifest?.endpoints?.length || 0}
                  </div>

                  {msg.proposalStatus === 'pending' || msg.proposalStatus === 'busy' ? (
                    <div className="flex items-center gap-2 mt-3">
                      <button
                        onClick={() => handleSkillProposalDecision(msg.proposal_id, msg.manifest?.skill_id, 'approve')}
                        disabled={skillProposalBusy !== ''}
                        className="px-3 py-1.5 text-xs rounded-lg bg-green-500/20 border border-green-500/30 text-green-300 disabled:opacity-50"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleSkillProposalDecision(msg.proposal_id, msg.manifest?.skill_id, 'reject')}
                        disabled={skillProposalBusy !== ''}
                        className="px-3 py-1.5 text-xs rounded-lg bg-red-500/20 border border-red-500/30 text-red-300 disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  ) : (
                    <div className={`mt-3 text-xs ${
                      msg.proposalStatus === 'approved'
                        ? 'text-green-300'
                        : msg.proposalStatus === 'rejected'
                          ? 'text-red-300'
                          : 'text-yellow-300'
                    }`}>
                      {msg.proposalStatus === 'approved' && 'Approved and registered'}
                      {msg.proposalStatus === 'rejected' && 'Rejected'}
                      {msg.proposalStatus === 'error' && (msg.proposalError || 'Request failed')}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {isStreaming && streamingText && (
          <div className="flex justify-start">
            <div className="max-w-[90%]">
              <div className="flex items-center gap-2 mb-1 opacity-60">
                <Zap size={12} className="text-asos-accent animate-pulse" />
                <span className="text-xs">streaming...</span>
              </div>
              <span className="leading-relaxed">{streamingText}</span>
              <span className="inline-block w-2 h-4 bg-asos-accent animate-pulse ml-0.5" />
            </div>
          </div>
        )}
        {isThinking && !isStreaming && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 px-4 py-2 bg-asos-card rounded-2xl rounded-tl-sm border border-asos-border">
              <div className="flex gap-1">
                <span className="w-2 h-2 rounded-full bg-asos-accent animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 rounded-full bg-asos-accent animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 rounded-full bg-asos-accent animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
              <span className="text-xs opacity-50">thinking...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Bottom Bar */}
      <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black via-black/90 to-transparent">
        <form onSubmit={handleSend} className="relative flex items-center w-full gap-2">
          <button
            type="button"
            onClick={toggleCamera}
            title={cameraOn ? "Stop camera" : "Start camera (vision)"}
            className={`p-3 rounded-full transition-all active:scale-95 ${
              cameraOn
                ? 'bg-blue-500 text-white shadow-[0_0_12px_rgba(59,130,246,0.5)]'
                : 'bg-asos-card border border-asos-border text-gray-400 hover:text-white hover:border-blue-400'
            }`}
          >
            {cameraOn ? <CameraOff size={16} /> : <Camera size={16} />}
          </button>
          <button
            type="button"
            onClick={toggleRecording}
            title={isRecording ? "Stop voice conversation" : "Start voice conversation (realtime)"}
            className={`p-3 rounded-full transition-all active:scale-95 ${
              isRecording
                ? 'bg-green-500 text-white shadow-[0_0_20px_rgba(34,197,94,0.5)] ring-2 ring-green-400 ring-opacity-50'
                : 'bg-asos-card border border-asos-border text-gray-400 hover:text-white hover:border-asos-accent'
            }`}
          >
            {isRecording ? <MicOff size={18} /> : <Mic size={18} />}
          </button>
          <input
            type="text"
            className="flex-1 bg-asos-card border border-asos-border rounded-full pl-5 pr-12 py-3 focus:outline-none focus:ring-1 focus:ring-asos-accent text-white placeholder-gray-500 text-sm"
            placeholder="Speak or type..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
          />
          <button
            type="submit"
            className="absolute right-2 p-2 bg-asos-accent rounded-full hover:bg-opacity-80 transition active:scale-95"
          >
            <Send size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}
