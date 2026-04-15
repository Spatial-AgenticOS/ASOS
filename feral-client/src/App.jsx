import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, AlertTriangle, Phone, MessageSquarePlus, History, Sparkles, Command } from 'lucide-react';
import { RealtimeVoiceEngine } from './lib/voiceRealtime';
import { VisionCapture } from './lib/visionCapture';
import ProactiveToast from './components/ProactiveToast';
import TheOrb from './components/TheOrb';
import AmbientStrip from './components/AmbientStrip';
import CommandPalette from './components/CommandPalette';
import WikiPanel from './components/chat/WikiPanel';
import SessionSnapshotsPanel from './components/chat/SessionSnapshotsPanel';
import ThreadsPanel from './components/chat/ThreadsPanel';
import MessageList from './components/chat/MessageList';
import ChatComposer from './components/chat/ChatComposer';
import { useFeralSession } from './hooks/useFeralSession';
import { useWikiPanel } from './hooks/useWikiPanel';
import { useSessionSnapshots } from './hooks/useSessionSnapshots';
import { useConversationThreads } from './hooks/useConversationThreads';

export default function App() {
  const [inputText, setInputText] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [voiceMode, setVoiceMode] = useState('off');
  const [voiceState, setVoiceState] = useState('off'); // 'active' | 'reconnecting' | 'degraded' | 'off'
  const [pushToTalk, setPushToTalk] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sessionStartTime] = useState(Date.now());
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const pttActiveRef = useRef(false);

  const voiceEngineRef = useRef(null);
  const visionRef = useRef(null);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const cameraPreviewRef = useRef(null);
  const navigate = useNavigate();

  const session = useFeralSession({ voiceEngineRef });
  const wiki = useWikiPanel();
  const snapshots = useSessionSnapshots({
    sessionId: session.sessionId,
    messages: session.messages,
    setMessages: session.setMessages,
  });
  const threads = useConversationThreads({
    messages: session.messages,
    setMessages: session.setMessages,
    sessionId: session.sessionId,
  });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [session.messages, session.isThinking]);

  // Push-to-talk: hold Space to unmute, release to mute
  useEffect(() => {
    if (!pushToTalk || !isRecording) return;

    const onKeyDown = (e) => {
      if (e.code !== 'Space' || e.repeat) return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
      e.preventDefault();
      if (!pttActiveRef.current && voiceEngineRef.current) {
        pttActiveRef.current = true;
        voiceEngineRef.current.unmuteMic();
      }
    };

    const onKeyUp = (e) => {
      if (e.code !== 'Space') return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
      e.preventDefault();
      if (pttActiveRef.current && voiceEngineRef.current) {
        pttActiveRef.current = false;
        voiceEngineRef.current.muteMic();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [pushToTalk, isRecording]);

  const handleSend = async (e) => {
    e.preventDefault();
    if ((!inputText.trim() && attachedFiles.length === 0) || !session.wsRef.current || session.wsRef.current.readyState !== WebSocket.OPEN) return;

    const fileData = await Promise.all(attachedFiles.map(async (f) => {
      const buffer = await f.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      let binary = '';
      for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
      return { name: f.name, type: f.type, size: f.size, data: btoa(binary) };
    }));

    const displayText = inputText.trim() || `[Sent ${attachedFiles.length} file${attachedFiles.length > 1 ? 's' : ''}]`;
    session.setMessages(prev => [...prev, {
      role: 'user', type: 'text',
      content: displayText + (fileData.length > 0 ? ` (${fileData.map(f => f.name).join(', ')})` : ''),
    }]);
    session.setIsThinking(true);

    const payload = { text: inputText, context: {} };
    if (fileData.length > 0) payload.files = fileData;
    session.wsRef.current.send(JSON.stringify({ hop: 'client', type: 'text_command', payload }));

    setInputText('');
    setAttachedFiles([]);
  };

  const sendQuickMessage = (text) => {
    if (!session.wsRef.current || session.wsRef.current.readyState !== WebSocket.OPEN) return;
    session.setMessages(prev => [...prev, { role: 'user', type: 'text', content: text }]);
    session.wsRef.current.send(JSON.stringify({ hop: 'client', type: 'text_command', payload: { text, context: {} } }));
  };

  const startRecording = async () => {
    if (!session.wsRef.current || session.wsRef.current.readyState !== WebSocket.OPEN) return;
    try {
      const engine = new RealtimeVoiceEngine(session.wsRef.current, {
        onStateChange: (state) => setVoiceState(state),
        onError: (kind, msg) => {
          if (kind === 'reconnect') {
            session.setMessages(prev => [...prev, { role: 'system', type: 'text', content: msg }]);
          }
        },
      });
      voiceEngineRef.current = engine;
      await engine.start();
      if (pushToTalk) engine.muteMic();
      setIsRecording(true);
      setVoiceMode('realtime');
      setVoiceState('active');
      const modeLabel = pushToTalk ? 'Push-to-talk active. Hold Space to speak.' : 'Speak naturally — your agent can hear you and use tools.';
      session.setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Voice conversation started. ${modeLabel}` }]);
    } catch (err) {
      session.setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Mic access denied: ${err.message}` }]);
    }
  };

  const stopRecording = () => {
    if (voiceEngineRef.current) {
      voiceEngineRef.current.stop();
      voiceEngineRef.current = null;
    }
    setIsRecording(false);
    setVoiceMode('off');
    setVoiceState('off');
  };

  const toggleCamera = async () => {
    if (cameraOn) {
      if (visionRef.current) { visionRef.current.stop(); visionRef.current = null; }
      if (cameraPreviewRef.current) cameraPreviewRef.current.srcObject = null;
      setCameraOn(false);
      session.setMessages(prev => [...prev, { role: 'system', type: 'text', content: 'Camera stopped.' }]);
    } else {
      if (!session.wsRef.current || session.wsRef.current.readyState !== WebSocket.OPEN) return;
      try {
        const vc = new VisionCapture(session.wsRef.current, 1);
        visionRef.current = vc;
        await vc.start();
        if (cameraPreviewRef.current && vc.stream) {
          cameraPreviewRef.current.srcObject = vc.stream;
        }
        setCameraOn(true);
        session.setMessages(prev => [...prev, { role: 'system', type: 'text', content: 'Camera active — agent can now see through your webcam.' }]);
      } catch (err) {
        session.setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Camera error: ${err.message}` }]);
      }
    }
  };

  const handleDragOver = (e) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e) => {
    if (e.currentTarget.contains(e.relatedTarget)) return;
    setIsDragging(false);
  };
  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) setAttachedFiles(prev => [...prev, ...files]);
  };

  return (
    <div
      className="flex flex-col h-full max-w-full lg:max-w-3xl mx-auto bg-feral-bg relative overflow-hidden"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {isDragging && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-feral-bg/80 backdrop-blur-sm border-2 border-dashed border-feral-accent rounded-xl pointer-events-none">
          <div className="text-center">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="mx-auto mb-2 text-feral-accent">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
            </svg>
            <p className="text-sm font-medium text-feral-accent">Drop files to attach</p>
          </div>
        </div>
      )}

      {!session.isConnected && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0,
          padding: '6px 16px',
          background: '#78350f',
          color: '#fbbf24',
          fontSize: 13,
          textAlign: 'center',
          zIndex: 9999,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 8,
        }}>
          <span className="animate-spin" style={{ width: 12, height: 12, border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', display: 'inline-block' }} />
          Reconnecting to FERAL Brain...
        </div>
      )}

      <ProactiveToast
        alert={session.proactiveAlert}
        onDismiss={() => session.setProactiveAlert(null)}
        onAction={(a) => { if (a.action_id) session.handleUIAction(a.action_id); }}
      />

      {/* Top Bar */}
      <div className="flex-shrink-0 h-12 bg-feral-surface/80 border-b border-feral-border z-10 flex items-center justify-between px-4 backdrop-blur-xl">
        <div className="flex items-center gap-2.5">
          <TheOrb
            size={20}
            mode={!session.isConnected ? 'disconnected' : session.isThinking ? 'thinking' : session.isStreaming ? 'speaking' : isRecording ? 'listening' : session.proactiveAlert ? 'alert' : 'idle'}
            connected={session.isConnected}
          />
          <span className="font-semibold text-sm text-feral-text">FERAL</span>
          {session.agentRuntime.active_subagents > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full border border-feral-accent/30 text-feral-accent bg-feral-accent-dim">
              {session.agentRuntime.active_subagents} agents
            </span>
          )}
          {isRecording && (
            <span className="text-emerald-400 text-[10px] font-medium animate-pulse flex items-center gap-1">
              <Phone size={10} /> LIVE
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {session.hr && (
            <div className="flex items-center gap-1.5 text-rose-400 mr-1.5">
              <Activity size={13} />
              <span className="font-mono text-[11px]">{session.hr}</span>
            </div>
          )}
          <button onClick={() => { void threads.startNewThread(); }} className="p-2 rounded-lg text-feral-text-muted hover:text-feral-accent hover:bg-feral-accent-dim transition" title="New Chat">
            <MessageSquarePlus size={15} />
          </button>
          <button
            onClick={() => { threads.setThreadsOpen(v => !v); if (!threads.threadsOpen) threads.fetchThreads(); }}
            className={`p-2 rounded-lg transition ${threads.threadsOpen ? 'text-feral-accent bg-feral-accent-dim' : 'text-feral-text-muted hover:text-feral-text hover:bg-feral-card-hover'}`}
            title="Conversations"
          >
            <History size={15} />
          </button>
          <button onClick={() => setPaletteOpen(true)} className="p-2 rounded-lg text-feral-text-muted hover:text-feral-text hover:bg-feral-card-hover transition" title="Command Palette (⌘K)">
            <Command size={15} />
          </button>
        </div>
      </div>

      <AmbientStrip screenContext={session.screenContext} hr={session.hr} sessionStartTime={sessionStartTime} />

      <CommandPalette
        open={paletteOpen}
        onClose={(action) => { if (action === 'open') setPaletteOpen(true); else setPaletteOpen(false); }}
        onCommand={sendQuickMessage}
        onToggle={(target) => { if (target === 'wiki') wiki.setWikiOpen(v => !v); }}
      />

      {session.transcript && (
        <div className="flex-shrink-0 px-4 py-2 bg-feral-accent-dim border-b border-feral-accent/20">
          <span className="text-sm italic text-feral-text-secondary">{session.transcript}</span>
        </div>
      )}

      {session.learnedNotice && (
        <div className="flex-shrink-0 px-4 py-2 border-b border-emerald-500/20 bg-emerald-500/10 text-emerald-300 flex items-center gap-2 text-xs">
          <Sparkles size={13} />
          <span className="font-medium">{session.learnedNotice.name}</span>
          <span className="opacity-80">
            {session.learnedNotice.mode === 'ready' ? 'is ready to use.' : 'was generated and is pending approval.'}
          </span>
        </div>
      )}

      {session.permissionRequest && (
        <div className="flex-shrink-0 px-4 py-3 border-b border-amber-500/20 bg-amber-500/10">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="text-amber-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-amber-300">Permission Request</div>
              <div className="text-[11px] text-feral-text-secondary mt-0.5 break-all font-mono">{session.permissionRequest.path}</div>
              <div className="text-[11px] text-feral-text-muted mt-0.5">{session.permissionRequest.reason}</div>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={() => session.handlePermissionDecision(session.permissionRequest.request_id, true)}
                  className="px-3 py-1 text-[11px] font-medium rounded bg-emerald-500/15 border border-emerald-500/25 text-emerald-400 hover:bg-emerald-500/25 transition"
                >
                  Grant Access
                </button>
                <button
                  onClick={() => session.handlePermissionDecision(session.permissionRequest.request_id, false)}
                  className="px-3 py-1 text-[11px] font-medium rounded bg-rose-500/15 border border-rose-500/25 text-rose-400 hover:bg-rose-500/25 transition"
                >
                  Deny
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {session.llmStatus && !session.llmStatus.available && (
        <div className="flex-shrink-0 px-4 py-2 bg-amber-500/10 border-b border-amber-500/20 flex items-center gap-2">
          <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
          <span className="text-xs text-amber-300">
            No LLM connected. Set <code className="bg-black/30 px-1.5 py-0.5 rounded text-[10px] font-mono">OPENAI_API_KEY</code> or start Ollama.
          </span>
        </div>
      )}

      {wiki.wikiOpen && <WikiPanel {...wiki} />}
      {snapshots.sessionPanelOpen && <SessionSnapshotsPanel {...snapshots} sessionId={session.sessionId} />}
      {threads.threadsOpen && <ThreadsPanel threads={threads.threads} currentThreadId={threads.currentThreadId} loadThread={threads.loadThread} startNewThread={threads.startNewThread} deleteThread={threads.deleteThread} />}

      <MessageList
        messages={session.messages}
        isConnected={session.isConnected}
        isStreaming={session.isStreaming}
        streamingText={session.streamingText}
        isThinking={session.isThinking}
        greeting={session.greeting}
        onQuickAction={sendQuickMessage}
        onUIAction={session.handleUIAction}
        onSkillDecision={session.handleSkillProposalDecision}
        skillProposalBusy={session.skillProposalBusy}
        messagesEndRef={messagesEndRef}
      />

      <ChatComposer
        inputText={inputText}
        setInputText={setInputText}
        isRecording={isRecording}
        isThinking={session.isThinking}
        isStreaming={session.isStreaming}
        cameraOn={cameraOn}
        currentThreadId={threads.currentThreadId}
        onSubmit={handleSend}
        onToggleRecording={() => isRecording ? stopRecording() : startRecording()}
        onToggleCamera={toggleCamera}
        onStartNewThread={threads.startNewThread}
        fileInputRef={fileInputRef}
        attachedFiles={attachedFiles}
        setAttachedFiles={setAttachedFiles}
      />

      {cameraOn && (
        <div style={{
          position: 'fixed', bottom: 80, right: 20,
          width: 160, height: 120,
          borderRadius: 12, overflow: 'hidden',
          border: '2px solid #06b6d4',
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
          zIndex: 100,
        }}>
          <video
            ref={cameraPreviewRef}
            autoPlay
            playsInline
            muted
            style={{ width: '100%', height: '100%', objectFit: 'cover', transform: 'scaleX(-1)' }}
          />
          <div style={{
            position: 'absolute', top: 4, right: 4,
            background: '#ef4444', borderRadius: '50%', width: 8, height: 8,
            animation: 'pulse 2s infinite',
          }} />
        </div>
      )}
    </div>
  );
}
