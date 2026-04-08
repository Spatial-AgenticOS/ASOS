import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { SduiRenderer } from './components/SduiRenderer';
import { Activity, Mic, MicOff, Send, Brain, Wifi, WifiOff, Zap, Settings, AlertTriangle, Phone, Camera, CameraOff } from 'lucide-react';
import { WS_URL, API_BASE } from './config';
import { RealtimeVoiceEngine } from './lib/voiceRealtime';
import { VisionCapture } from './lib/visionCapture';

export default function App() {
  const [messages, setMessages] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [inputText, setInputText] = useState('');
  const [hr, setHr] = useState(72);
  const [isRecording, setIsRecording] = useState(false);
  const [voiceMode, setVoiceMode] = useState('off');
  const [transcript, setTranscript] = useState('');
  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [llmStatus, setLlmStatus] = useState(null);
  const [cameraOn, setCameraOn] = useState(false);
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
    const interval = setInterval(() => {
      setHr(prev => Math.max(60, Math.min(130, prev + (Math.random() > 0.5 ? 1 : -1))));
    }, 2000);
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
        }
      } catch (e) {
        console.error("Message error:", e);
      }
    };

    wsRef.current = ws;
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
          <div className="flex items-center gap-1.5 text-red-400">
            <Activity size={16} className="animate-pulse" />
            <span className="font-mono text-sm">{hr}</span>
          </div>
          <button onClick={() => navigate('/settings')} className="p-1 text-gray-400 hover:text-white transition">
            <Settings size={16} />
          </button>
        </div>
      </div>

      {/* Transcript overlay */}
      {transcript && (
        <div className="absolute top-16 left-0 right-0 z-10 px-4 py-2 bg-asos-accent bg-opacity-20 backdrop-blur-sm border-b border-asos-accent border-opacity-30">
          <span className="text-sm italic opacity-80">{transcript}</span>
        </div>
      )}

      {/* No-LLM Banner */}
      {llmStatus && !llmStatus.available && (
        <div className="absolute top-16 left-0 right-0 z-[5] px-4 py-2 bg-yellow-500 bg-opacity-15 border-b border-yellow-500 border-opacity-30 flex items-center gap-2">
          <AlertTriangle size={14} className="text-yellow-400 flex-shrink-0" />
          <span className="text-xs text-yellow-300">
            No LLM connected. Set <code className="bg-black bg-opacity-30 px-1 rounded text-[10px]">OPENAI_API_KEY</code> or start Ollama for full conversation.
          </span>
        </div>
      )}

      {/* Messages View */}
      <div className="flex-1 overflow-y-auto px-4 pt-20 pb-28 space-y-6">
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
