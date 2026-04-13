import React from 'react';
import { Camera, CameraOff, Mic, MicOff, Send, MessageSquarePlus } from 'lucide-react';
import VoiceWaveform from '../VoiceWaveform';

export default function ChatComposer({
  inputText, setInputText, isRecording, isThinking, isStreaming,
  cameraOn, currentThreadId,
  onSubmit, onToggleRecording, onToggleCamera, onStartNewThread,
}) {
  return (
    <div className="flex-shrink-0 p-3 lg:p-4 bg-feral-surface/80 backdrop-blur-xl border-t border-feral-border">
      <div className="mb-2 flex items-center justify-between">
        <button
          type="button"
          onClick={() => { void onStartNewThread(); }}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-feral-accent/15 border border-feral-accent/25 text-feral-accent hover:bg-feral-accent/25 transition"
        >
          <MessageSquarePlus size={12} />
          Start New Chat
        </button>
        <span className="text-[10px] text-feral-text-muted font-mono">
          {currentThreadId ? `thread:${currentThreadId.slice(0, 10)}` : 'thread:pending'}
        </span>
      </div>
      <form onSubmit={onSubmit} className="flex items-center gap-2">
        <button
          type="button"
          onClick={onToggleCamera}
          title={cameraOn ? 'Stop camera' : 'Start camera'}
          className={`p-2.5 rounded-xl transition-all active:scale-95 flex-shrink-0 ${
            cameraOn
              ? 'bg-sky-500 text-white shadow-lg shadow-sky-500/25'
              : 'bg-feral-card border border-feral-border text-feral-text-muted hover:text-feral-text hover:border-feral-border-bright'
          }`}
        >
          {cameraOn ? <CameraOff size={16} /> : <Camera size={16} />}
        </button>
        <button
          type="button"
          onClick={onToggleRecording}
          title={isRecording ? 'Stop voice' : 'Start voice'}
          className={`p-2.5 rounded-xl transition-all active:scale-95 flex-shrink-0 ${
            isRecording
              ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-500/25 ring-2 ring-emerald-400/30'
              : 'bg-feral-card border border-feral-border text-feral-text-muted hover:text-feral-text hover:border-feral-border-bright'
          }`}
        >
          {isRecording ? <MicOff size={16} /> : <Mic size={16} />}
        </button>
        {isRecording && (
          <VoiceWaveform mode={isThinking ? 'thinking' : isStreaming ? 'speaking' : 'listening'} />
        )}
        <div className="flex-1 relative">
          <input
            type="text"
            className="w-full bg-feral-card border border-feral-border rounded-xl pl-4 pr-11 py-2.5 text-sm text-feral-text placeholder-feral-text-muted focus:outline-none focus:ring-1 focus:ring-feral-accent focus:border-feral-accent transition"
            placeholder="Message FERAL..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
          />
          <button
            type="submit"
            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1.5 bg-feral-accent rounded-lg text-white hover:bg-feral-accent/80 transition active:scale-95"
          >
            <Send size={14} />
          </button>
        </div>
      </form>
    </div>
  );
}
