import React, { useCallback, useEffect, useState } from 'react';
import { API_BASE as API } from '../config';
import { Crosshair, Plus, RefreshCw, CheckCircle2, Circle, BarChart3, Target, Loader2 } from 'lucide-react';
import { useToast } from '../components/Toast';

export default function Intents() {
  const { addToast } = useToast();
  const [intentText, setIntentText] = useState('');
  const [compiling, setCompiling] = useState(false);
  const [todayActions, setTodayActions] = useState([]);
  const [plans, setPlans] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [completing, setCompleting] = useState('');

  const fetchAll = useCallback(async () => {
    try {
      const [todayRes, plansRes, statsRes] = await Promise.all([
        fetch(`${API}/api/intents/today`).then(r => r.json()),
        fetch(`${API}/api/intents/list`).then(r => r.json()),
        fetch(`${API}/api/intents/stats`).then(r => r.json()),
      ]);
      setTodayActions(todayRes.actions || []);
      setPlans(plansRes.plans || []);
      setStats(statsRes);
    } catch (e) {
      addToast(e.message || 'Failed to load intents');
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 12000);
    return () => clearInterval(iv);
  }, [fetchAll]);

  const handleCompile = async () => {
    if (!intentText.trim() || compiling) return;
    setCompiling(true);
    try {
      await fetch(`${API}/api/intents/compile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent: intentText.trim() }),
      });
      setIntentText('');
      await fetchAll();
    } catch (e) {
      addToast(e.message || 'Failed to compile intent');
    } finally {
      setCompiling(false);
    }
  };

  const handleComplete = async (planId, actionId) => {
    const key = `${planId}:${actionId}`;
    if (completing === key) return;
    setCompleting(key);
    try {
      await fetch(`${API}/api/intents/${planId}/complete/${actionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ result: 'Completed via UI' }),
      });
      await fetchAll();
    } catch (e) {
      addToast(e.message || 'Failed to complete action');
    } finally {
      setCompleting('');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full bg-feral-bg">
        <Loader2 className="w-6 h-6 animate-spin text-feral-accent" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-feral-bg p-4 md:p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Crosshair className="w-6 h-6 text-feral-accent" />
          <h1 className="text-xl font-semibold text-feral-text">Intent Compiler</h1>
        </div>
        <button
          onClick={() => fetchAll()}
          className="p-2 rounded-lg text-feral-text-muted hover:text-feral-text hover:bg-feral-card-hover transition"
        >
          <RefreshCw size={16} />
        </button>
      </div>

      {/* New Intent Form */}
      <div className="bg-feral-surface border border-feral-border rounded-xl p-4">
        <label className="block text-xs font-medium text-feral-text-secondary mb-2">
          New Intent
        </label>
        <div className="flex gap-3">
          <input
            type="text"
            value={intentText}
            onChange={e => setIntentText(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCompile()}
            placeholder="Describe your goal — e.g. 'Learn Spanish basics this week'"
            className="flex-1 bg-feral-bg border border-feral-border rounded-lg px-3 py-2.5 text-sm text-feral-text placeholder:text-feral-text-muted focus:outline-none focus:border-feral-accent transition"
          />
          <button
            onClick={handleCompile}
            disabled={!intentText.trim() || compiling}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-feral-accent text-white text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            {compiling ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Compile
          </button>
        </div>
      </div>

      {/* Stats */}
      {stats && stats.total_plans > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Total Plans', value: stats.total_plans, color: 'text-feral-accent' },
            { label: 'Active', value: stats.active_plans, color: 'text-blue-400' },
            { label: 'Completed', value: stats.completed_plans, color: 'text-green-400' },
            { label: 'Avg Progress', value: `${Math.round((stats.average_progress || 0) * 100)}%`, color: 'text-yellow-400' },
          ].map(s => (
            <div key={s.label} className="bg-feral-surface border border-feral-border rounded-xl p-3 text-center">
              <div className={`text-lg font-bold ${s.color}`}>{s.value}</div>
              <div className="text-[11px] text-feral-text-muted mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Today's Actions */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Target size={15} className="text-feral-accent" />
          <h2 className="text-sm font-semibold text-feral-text">Today&apos;s Actions</h2>
          <span className="text-xs text-feral-text-muted">({todayActions.length})</span>
        </div>
        {todayActions.length === 0 ? (
          <div className="bg-feral-surface border border-feral-border rounded-xl p-6 text-center text-sm text-feral-text-muted">
            No pending actions — compile an intent to get started.
          </div>
        ) : (
          <div className="space-y-2">
            {todayActions.map(a => {
              const key = `${a.plan_id}:${a.action_id}`;
              const busy = completing === key;
              return (
                <div
                  key={key}
                  className="flex items-center gap-3 bg-feral-surface border border-feral-border rounded-xl px-4 py-3 group hover:border-feral-accent/40 transition"
                >
                  <button
                    onClick={() => handleComplete(a.plan_id, a.action_id)}
                    disabled={busy}
                    className="flex-shrink-0 text-feral-text-muted hover:text-green-400 transition"
                  >
                    {busy ? (
                      <Loader2 size={18} className="animate-spin" />
                    ) : (
                      <Circle size={18} />
                    )}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-feral-text truncate">{a.action || a.description}</div>
                    {a.tool_hint && (
                      <div className="text-[11px] text-feral-text-muted mt-0.5">
                        Tool: {a.tool_hint}
                      </div>
                    )}
                  </div>
                  <div className="flex-shrink-0 text-[10px] text-feral-text-muted bg-feral-bg px-2 py-0.5 rounded">
                    {a.intent?.slice(0, 30)}{a.intent?.length > 30 ? '…' : ''}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Active Plans */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <BarChart3 size={15} className="text-feral-accent" />
          <h2 className="text-sm font-semibold text-feral-text">Active Plans</h2>
          <span className="text-xs text-feral-text-muted">({plans.length})</span>
        </div>
        {plans.length === 0 ? (
          <div className="bg-feral-surface border border-feral-border rounded-xl p-6 text-center text-sm text-feral-text-muted">
            No plans yet.
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {plans.map(p => {
              const pct = Math.round((p.progress || 0) * 100);
              const isComplete = p.status === 'completed';
              return (
                <div
                  key={p.plan_id}
                  className={`bg-feral-surface border rounded-xl p-4 transition ${
                    isComplete ? 'border-green-500/30' : 'border-feral-border hover:border-feral-accent/40'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="text-sm text-feral-text font-medium leading-snug line-clamp-2">
                      {p.intent}
                    </div>
                    <span
                      className={`flex-shrink-0 text-[10px] px-2 py-0.5 rounded-full font-medium ${
                        isComplete
                          ? 'text-green-300 bg-green-500/15'
                          : p.status === 'active'
                          ? 'text-blue-300 bg-blue-500/15'
                          : 'text-feral-text-muted bg-gray-500/15'
                      }`}
                    >
                      {p.status}
                    </span>
                  </div>

                  {/* Progress bar */}
                  <div className="w-full h-1.5 bg-feral-bg rounded-full overflow-hidden mb-2">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        isComplete ? 'bg-green-500' : 'bg-feral-accent'
                      }`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>

                  <div className="flex items-center justify-between text-[11px] text-feral-text-muted">
                    <span>
                      {isComplete ? <CheckCircle2 size={11} className="inline mr-1 text-green-400" /> : null}
                      {p.actions_done}/{p.actions_total} actions
                    </span>
                    <span>{pct}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
