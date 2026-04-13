import React from 'react';
import { MessageSquarePlus, Trash2 } from 'lucide-react';

export default function ThreadsPanel({
  threads, currentThreadId,
  loadThread, startNewThread, deleteThread,
}) {
  return (
    <div className="flex-shrink-0 bg-feral-surface border-b border-feral-border max-h-72 overflow-y-auto">
      <div className="px-4 py-3 flex items-center justify-between sticky top-0 bg-feral-surface z-10 border-b border-feral-border/50">
        <span className="text-sm font-medium text-feral-text">Conversations</span>
        <button
          onClick={startNewThread}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-feral-accent/15 border border-feral-accent/25 text-feral-accent hover:bg-feral-accent/25 transition"
        >
          <MessageSquarePlus size={13} />
          New
        </button>
      </div>
      {threads.length === 0 ? (
        <div className="px-4 py-6 text-center text-xs text-feral-text-muted">No saved conversations yet. Start chatting and they will auto-save.</div>
      ) : threads.map(t => (
        <div
          key={t.id}
          className={`px-4 py-3 border-b border-feral-border/30 flex items-center gap-3 cursor-pointer transition hover:bg-feral-card-hover ${
            currentThreadId === t.id ? 'bg-feral-accent-dim' : ''
          }`}
          onClick={() => loadThread(t.id)}
        >
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-feral-text truncate">{t.title}</div>
            <div className="text-[11px] text-feral-text-muted truncate mt-0.5">{t.preview || `${t.message_count} messages`}</div>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); deleteThread(t.id); }}
            className="p-1 rounded text-feral-text-muted hover:text-rose-400 hover:bg-rose-400/10 transition flex-shrink-0"
            title="Delete"
          >
            <Trash2 size={13} />
          </button>
        </div>
      ))}
    </div>
  );
}
