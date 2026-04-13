import { useState, useRef, useCallback, useEffect } from 'react';
import { WS_URL, API_BASE } from '../config';

export function useFeralSession({ voiceEngineRef }) {
  const [messages, setMessages] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [hr, setHr] = useState(null);
  const [sessionId, setSessionId] = useState('');
  const [activeFlowCount, setActiveFlowCount] = useState(0);
  const [agentRuntime, setAgentRuntime] = useState({
    multi_agent_enabled: false,
    multi_agent_ready: false,
    active_subagents: 0,
    pending_confirmations: 0,
  });
  const [learnedNotice, setLearnedNotice] = useState(null);
  const [permissionRequest, setPermissionRequest] = useState(null);
  const [proactiveAlert, setProactiveAlert] = useState(null);
  const [screenContext, setScreenContext] = useState('');
  const [transcript, setTranscript] = useState('');
  const [llmStatus, setLlmStatus] = useState(null);
  const [skillProposalBusy, setSkillProposalBusy] = useState('');
  const [greeting, setGreeting] = useState(null);

  const wsRef = useRef(null);
  const streamBufferRef = useRef('');
  const greetingReceivedRef = useRef(false);
  const unmountedRef = useRef(false);
  const reconnectTimerRef = useRef(null);

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
      console.error('TTS playback error:', e);
    }
  }, []);

  const connect = () => {
    if (unmountedRef.current) return;
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      if (unmountedRef.current) { ws.close(); return; }
      setIsConnected(true);
      greetingReceivedRef.current = false;
    };

    ws.onclose = () => {
      setIsConnected(false);
      if (unmountedRef.current) return;
      reconnectTimerRef.current = setTimeout(connect, 3000);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.session_id) setSessionId(msg.session_id);

        if (msg.type === 'sdui') {
          setIsThinking(false);
          setMessages(prev => [...prev, { role: 'assistant', type: 'sdui', payload: msg.payload.root }]);
        } else if (msg.type === 'text_response') {
          setIsThinking(false);
          const text = msg.payload?.text || '';
          if (text === 'FERAL Brain connected. How can I help?') {
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
          console.log('Voice config acknowledged:', msg.payload);
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
        } else if (msg.type === 'state_push') {
          const { event, data } = msg;
          if (event === 'dashboard_update' && data) {
            const heartRate = data?.health?.heart_rate;
            if (heartRate) setHr(heartRate);
            setActiveFlowCount(data?.taskflows?.running || 0);
          } else if (event === 'proactive_alert' && data) {
            setProactiveAlert({
              kind: data.kind || 'info',
              title: data.title || '',
              message: data.message || '',
              action_label: data.action_label || '',
              action_id: data.action_id || '',
            });
          } else if (event === 'ambient_context' && data) {
            if (data.screen_description) setScreenContext(data.screen_description);
          }
        }
      } catch (e) {
        console.error('Message error:', e);
      }
    };

    wsRef.current = ws;
  };

  useEffect(() => {
    fetch(`${API_BASE}/api/dashboard`).then(r => r.json()).then(data => {
      if (data?.health?.heart_rate) setHr(data.health.heart_rate);
    }).catch(() => {});
    fetch(`${API_BASE}/api/identity/greeting`).then(r => r.json()).then(data => {
      if (data && !data.error) setGreeting(data);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    connect();
    fetch(`${API_BASE}/api/llm/status`).then(r => r.json()).then(setLlmStatus).catch(() => {});
    return () => {
      unmountedRef.current = true;
      clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/system/info`).then(r => r.json()).then(data => {
      setAgentRuntime(data.orchestrator || {
        multi_agent_enabled: false, multi_agent_ready: false,
        active_subagents: 0, pending_confirmations: 0,
      });
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!learnedNotice) return undefined;
    const timer = setTimeout(() => setLearnedNotice(null), 7000);
    return () => clearTimeout(timer);
  }, [learnedNotice]);

  const handleUIAction = (action_id) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    setMessages(prev => [...prev, { role: 'user', type: 'action', content: `Clicked: ${action_id}` }]);
    wsRef.current.send(JSON.stringify({
      hop: 'client', type: 'ui_event',
      payload: { screen_id: 'main', action_id, event: 'tap' },
    }));
  };

  const handlePermissionDecision = (reqId, granted) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    const actionPrefix = granted ? 'perm_grant_' : 'perm_deny_';
    wsRef.current.send(JSON.stringify({
      hop: 'client', type: 'ui_event',
      payload: { screen_id: 'main', action_id: `${actionPrefix}${reqId}`, event: 'tap' },
    }));
    setPermissionRequest(null);
  };

  const handleSkillProposalDecision = async (proposalId, skillId, action) => {
    if (!skillId) return;
    const busyKey = `${proposalId}:${action}`;
    setSkillProposalBusy(busyKey);
    setMessages(prev => prev.map(m =>
      m.type === 'skill_proposal' && m.proposal_id === proposalId ? { ...m, proposalStatus: 'busy' } : m
    ));
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
        ...prev.map(m =>
          m.type === 'skill_proposal' && m.proposal_id === proposalId
            ? { ...m, proposalStatus: ok ? (action === 'approve' ? 'approved' : 'rejected') : 'error', proposalError: ok ? '' : (data.error || `Failed to ${action} skill`) }
            : m
        ),
        { role: 'system', type: 'text', content: ok ? `Skill ${action}d: ${skillId}` : `Skill ${action} failed: ${data.error || 'unknown error'}` },
      ]);
    } catch (e) {
      setMessages(prev => [
        ...prev.map(m =>
          m.type === 'skill_proposal' && m.proposal_id === proposalId
            ? { ...m, proposalStatus: 'error', proposalError: e.message || 'request failed' }
            : m
        ),
        { role: 'system', type: 'text', content: `Skill ${action} failed: ${e.message || 'request failed'}` },
      ]);
    } finally {
      setSkillProposalBusy('');
    }
  };

  return {
    wsRef,
    messages, setMessages,
    isConnected,
    streamingText, isStreaming,
    isThinking, setIsThinking,
    hr,
    sessionId,
    activeFlowCount, agentRuntime,
    learnedNotice, setLearnedNotice,
    permissionRequest,
    proactiveAlert, setProactiveAlert,
    screenContext,
    transcript,
    llmStatus,
    skillProposalBusy,
    greeting,
    handleUIAction,
    handlePermissionDecision,
    handleSkillProposalDecision,
  };
}
