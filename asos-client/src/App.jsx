import React, { useState, useEffect, useRef, useCallback } from 'react';
import { SduiRenderer } from './components/SduiRenderer';
import { Activity, Mic, MicOff, Send, Brain, Wifi, WifiOff } from 'lucide-react';

export default function App() {
  const [messages, setMessages] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [inputText, setInputText] = useState('');
  const [hr, setHr] = useState(72);
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [memoryStats, setMemoryStats] = useState(null);
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioContextRef = useRef(null);
  const chunkIndexRef = useRef(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setHr(prev => Math.max(60, Math.min(130, prev + (Math.random() > 0.5 ? 1 : -1))));
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  const connect = () => {
    const ws = new WebSocket('ws://localhost:9090/v1/session');

    ws.onopen = () => setIsConnected(true);

    ws.onclose = () => {
      setIsConnected(false);
      setTimeout(connect, 3000);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        if (msg.type === 'sdui') {
          setMessages(prev => [...prev, { role: 'assistant', type: 'sdui', payload: msg.payload.root }]);
        } else if (msg.type === 'text_response') {
          setMessages(prev => [...prev, { role: 'assistant', type: 'text', content: msg.payload.text }]);
        } else if (msg.type === 'transcript') {
          setTranscript(msg.payload.text);
          if (!msg.payload.is_partial) {
            setMessages(prev => [...prev, { role: 'user', type: 'text', content: msg.payload.text, source: 'voice' }]);
            setTranscript('');
          }
        } else if (msg.type === 'tts_chunk') {
          playTTSChunk(msg.payload);
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
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
          ? 'audio/webm;codecs=opus'
          : 'audio/webm',
      });

      chunkIndexRef.current = 0;
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size > 0 && wsRef.current?.readyState === WebSocket.OPEN) {
          const reader = new FileReader();
          reader.onloadend = () => {
            const base64 = reader.result.split(',')[1];
            const audioMsg = {
              hop: "client",
              type: "audio_chunk",
              payload: {
                encoding: "webm",
                sample_rate: 16000,
                channels: 1,
                chunk_index: chunkIndexRef.current++,
                is_final: false,
                data_b64: base64,
              }
            };
            wsRef.current.send(JSON.stringify(audioMsg));
          };
          reader.readAsDataURL(event.data);
        }
      };

      mediaRecorder.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({
            hop: "client",
            type: "audio_chunk",
            payload: {
              encoding: "webm",
              sample_rate: 16000,
              channels: 1,
              chunk_index: chunkIndexRef.current,
              is_final: true,
              data_b64: "",
            }
          }));
        }
      };

      mediaRecorder.start(1000);
      setIsRecording(true);
    } catch (err) {
      console.error("Mic access denied:", err);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
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
    <div className="flex flex-col h-screen max-w-full lg:max-w-md mx-auto bg-black bg-opacity-80 backdrop-blur-xl relative overflow-hidden">
      {/* Top Bar */}
      <div className="absolute top-0 left-0 right-0 h-16 bg-asos-card border-b border-asos-border z-10 flex items-center justify-between px-4 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-green-500 shadow-[0_0_8px_#22c55e]' : 'bg-red-500'}`} />
          <Brain size={18} className="text-asos-accent" />
          <span className="font-semibold tracking-wider text-sm">THEORA</span>
        </div>
        <div className="flex items-center gap-3">
          {isRecording && (
            <span className="text-red-400 text-xs animate-pulse flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              REC
            </span>
          )}
          <div className="flex items-center gap-1.5 text-red-400">
            <Activity size={16} className="animate-pulse" />
            <span className="font-mono text-sm">{hr}</span>
          </div>
        </div>
      </div>

      {/* Transcript overlay */}
      {transcript && (
        <div className="absolute top-16 left-0 right-0 z-10 px-4 py-2 bg-asos-accent bg-opacity-20 backdrop-blur-sm border-b border-asos-accent border-opacity-30">
          <span className="text-sm italic opacity-80">{transcript}</span>
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
        <div ref={messagesEndRef} />
      </div>

      {/* Bottom Bar */}
      <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black via-black/90 to-transparent">
        <form onSubmit={handleSend} className="relative flex items-center w-full gap-2">
          <button
            type="button"
            onClick={toggleRecording}
            className={`p-3 rounded-full transition-all active:scale-95 ${
              isRecording
                ? 'bg-red-500 text-white animate-pulse shadow-[0_0_15px_rgba(239,68,68,0.5)]'
                : 'bg-asos-card border border-asos-border text-gray-400 hover:text-white'
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
