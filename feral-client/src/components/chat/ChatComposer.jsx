import React, { useRef, useEffect } from 'react';
import { Camera, CameraOff, Mic, MicOff, Send, MessageSquarePlus, Paperclip } from 'lucide-react';
import VoiceWaveform from '../VoiceWaveform';

export default function ChatComposer({
  inputText, setInputText, isRecording, isThinking, isStreaming,
  cameraOn, currentThreadId,
  onSubmit, onToggleRecording, onToggleCamera, onStartNewThread,
  fileInputRef, attachedFiles = [], setAttachedFiles,
}) {
  const textareaRef = useRef(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 200) + 'px';
    }
  }, [inputText]);

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

      {attachedFiles.length > 0 && (
        <div className="flex gap-1.5 px-1 pb-2 flex-wrap">
          {attachedFiles.map((f, i) => (
            <div key={i} className="flex items-center gap-1.5 bg-feral-card border border-feral-border px-2 py-1 rounded-lg text-[11px] text-feral-text-secondary">
              <Paperclip size={10} className="text-feral-accent flex-shrink-0" />
              <span className="truncate max-w-[120px]">{f.name}</span>
              <button
                type="button"
                onClick={() => setAttachedFiles(prev => prev.filter((_, j) => j !== i))}
                className="text-rose-400 hover:text-rose-300 transition ml-0.5 leading-none"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

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
          <textarea
            ref={textareaRef}
            className="w-full bg-feral-card border border-feral-border rounded-xl pl-4 pr-20 py-2.5 text-sm text-feral-text placeholder-feral-text-muted focus:outline-none focus:ring-1 focus:ring-feral-accent focus:border-feral-accent transition resize-none"
            placeholder="Message FERAL..."
            value={inputText}
            rows={1}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                onSubmit(e);
              }
            }}
            style={{ overflow: 'hidden', minHeight: '40px', maxHeight: '200px' }}
          />
          <div className="absolute right-1.5 bottom-1.5 flex items-center gap-0.5">
            <button
              type="button"
              onClick={() => fileInputRef?.current?.click()}
              title="Attach file"
              className="p-1.5 rounded-lg text-feral-text-muted hover:text-feral-accent transition"
            >
              <Paperclip size={14} />
            </button>
            <button
              type="submit"
              className="p-1.5 bg-feral-accent rounded-lg text-white hover:bg-feral-accent/80 transition active:scale-95"
            >
              <Send size={14} />
            </button>
          </div>
        </div>
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          multiple
          accept="image/*,.pdf,.txt,.md,.json,.csv"
          onChange={(e) => {
            const files = Array.from(e.target.files || []);
            if (setAttachedFiles) setAttachedFiles(prev => [...prev, ...files]);
            e.target.value = '';
          }}
        />
      </form>
    </div>
  );
}
