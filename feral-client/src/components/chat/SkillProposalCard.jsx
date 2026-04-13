import React, { useState } from 'react';
import { Zap, ChevronDown, ChevronUp } from 'lucide-react';

export default function SkillProposalCard({ msg, onDecision, busy }) {
  const [expanded, setExpanded] = useState(false);
  const resolved = msg.proposalStatus !== 'pending' && msg.proposalStatus !== 'busy';
  const name = msg.manifest?.brand?.name || msg.manifest?.skill_id || 'Generated Skill';
  const epCount = msg.manifest?.endpoints?.length || 0;

  return (
    <div className="bg-feral-assistant border border-feral-border rounded-xl px-3 py-2">
      <div className="flex items-center gap-2">
        <Zap size={12} className="text-feral-accent flex-shrink-0" />
        <span className="text-[12px] font-semibold text-feral-text truncate flex-1">{name}</span>
        <span className="text-[10px] text-feral-text-muted font-mono flex-shrink-0">{epCount} ep</span>
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
        <button onClick={() => setExpanded(v => !v)} className="p-0.5 text-feral-text-muted hover:text-feral-text transition">
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
      </div>
      {expanded && (
        <div className="mt-1.5 pt-1.5 border-t border-feral-border/50 space-y-1">
          {msg.reason && <div className="text-[11px] text-feral-text-muted">Reason: {msg.reason}</div>}
          <div className="text-[11px] text-feral-text-secondary">{msg.manifest?.description || 'No description'}</div>
          <div className="text-[10px] text-feral-text-muted font-mono">{msg.manifest?.skill_id || 'unknown'}</div>
        </div>
      )}
    </div>
  );
}
