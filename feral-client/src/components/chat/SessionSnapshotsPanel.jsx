import React from 'react';
import { BookmarkPlus, RefreshCw } from 'lucide-react';

export default function SessionSnapshotsPanel({
  sessionSnapshots, sessionLoading, sessionBusy,
  sessionBranchName, setSessionBranchName,
  sessionId,
  fetchSessionSnapshots, createSnapshot,
  restoreSnapshot, branchFromSnapshot,
}) {
  return (
    <div className="flex-shrink-0 bg-feral-surface border-b border-feral-border max-h-48 overflow-y-auto">
      <div className="px-4 py-2.5 flex items-center justify-between sticky top-0 bg-feral-surface z-10">
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-feral-text-secondary">Snapshots</span>
          <span className="text-[10px] font-mono text-feral-text-muted px-2 py-0.5 rounded bg-feral-card border border-feral-border">
            {sessionBranchName}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={sessionBranchName}
            onChange={(e) => setSessionBranchName(e.target.value)}
            className="w-20 bg-feral-bg border border-feral-border rounded-md px-2 py-1 text-[10px] font-mono text-feral-text focus:outline-none focus:ring-1 focus:ring-feral-accent"
            placeholder="branch"
          />
          <button
            onClick={createSnapshot}
            disabled={!sessionId || sessionBusy !== ''}
            className="px-2.5 py-1 rounded-md bg-feral-accent/15 border border-feral-accent/25 text-feral-accent text-[11px] font-medium hover:bg-feral-accent/25 disabled:opacity-40 transition flex items-center gap-1"
          >
            <BookmarkPlus size={11} />
            Save
          </button>
          <button
            onClick={fetchSessionSnapshots}
            className="p-1 rounded text-feral-text-muted hover:text-feral-text transition"
            disabled={sessionLoading}
          >
            <RefreshCw size={12} className={sessionLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>
      {(sessionSnapshots || []).map((snap) => (
        <div key={snap.snapshot_id} className="px-4 py-2 border-t border-feral-border/50 flex items-center justify-between gap-2 hover:bg-feral-card-hover transition">
          <div className="min-w-0">
            <span className="text-[11px] font-mono text-feral-text-secondary truncate block">{snap.snapshot_id}</span>
            {snap.label && <span className="text-[10px] text-feral-text-muted">{snap.label}</span>}
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
        <div className="px-4 py-3 text-xs text-feral-text-muted">No snapshots yet. Click Save to create one.</div>
      )}
    </div>
  );
}
