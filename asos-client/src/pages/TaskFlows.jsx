import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { API_BASE as API } from '../config';
import { Play, Pause, RefreshCw, XCircle, Plus, ListChecks } from 'lucide-react';

const DEFAULT_STEPS = [
  { type: 'note.save', content: 'TaskFlow started from UI', tags: ['taskflow', 'ui'] },
  { type: 'sleep', seconds: 10 },
  { type: 'wiki.compile' },
];

function statusClass(status) {
  switch (status) {
    case 'running':
      return 'text-blue-300 bg-blue-500/15 border-blue-500/30';
    case 'waiting':
      return 'text-yellow-300 bg-yellow-500/15 border-yellow-500/30';
    case 'completed':
      return 'text-green-300 bg-green-500/15 border-green-500/30';
    case 'failed':
      return 'text-red-300 bg-red-500/15 border-red-500/30';
    case 'cancelled':
      return 'text-gray-300 bg-gray-500/15 border-gray-500/30';
    default:
      return 'text-purple-300 bg-purple-500/15 border-purple-500/30';
  }
}

export default function TaskFlows() {
  const [flows, setFlows] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [selectedFlow, setSelectedFlow] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actionBusy, setActionBusy] = useState('');
  const [createBusy, setCreateBusy] = useState(false);
  const [error, setError] = useState('');
  const [newTitle, setNewTitle] = useState('UI TaskFlow');
  const [newSessionId, setNewSessionId] = useState('');
  const [newStepsJson, setNewStepsJson] = useState(JSON.stringify(DEFAULT_STEPS, null, 2));

  const fetchFlows = useCallback(async ({ withSpinner = false } = {}) => {
    if (withSpinner) setRefreshing(true);
    try {
      const res = await fetch(`${API}/api/taskflows?limit=100`);
      const data = await res.json();
      const nextFlows = data.flows || [];
      setFlows(nextFlows);

      const nextSelectedId = selectedId || nextFlows[0]?.id || '';
      setSelectedId(nextSelectedId);
      if (nextSelectedId) {
        const detail = await fetch(`${API}/api/taskflows/${encodeURIComponent(nextSelectedId)}`).then(r => r.json());
        if (!detail.error) {
          setSelectedFlow(detail);
        } else {
          setSelectedFlow(null);
        }
      } else {
        setSelectedFlow(null);
      }
      setError('');
    } catch (e) {
      setError(e.message || 'Failed to load taskflows');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selectedId]);

  useEffect(() => {
    fetchFlows();
    const iv = setInterval(() => fetchFlows(), 3000);
    return () => clearInterval(iv);
  }, [fetchFlows]);

  const loadFlow = async (flowId) => {
    setSelectedId(flowId);
    try {
      const detail = await fetch(`${API}/api/taskflows/${encodeURIComponent(flowId)}`).then(r => r.json());
      if (!detail.error) setSelectedFlow(detail);
    } catch (e) {
      setError(e.message || 'Failed to load flow');
    }
  };

  const runAction = async (kind) => {
    if (!selectedFlow?.id) return;
    setActionBusy(kind);
    try {
      const endpoint = kind === 'resume' ? 'resume' : 'cancel';
      await fetch(`${API}/api/taskflows/${encodeURIComponent(selectedFlow.id)}/${endpoint}`, { method: 'POST' });
      await fetchFlows();
    } catch (e) {
      setError(e.message || `Failed to ${kind} taskflow`);
    } finally {
      setActionBusy('');
    }
  };

  const createFlow = async () => {
    setCreateBusy(true);
    setError('');
    try {
      const steps = JSON.parse(newStepsJson);
      const body = {
        title: newTitle || 'UI TaskFlow',
        session_id: newSessionId || '',
        steps,
        context: { source: 'web_ui_taskflows_page' },
      };
      const created = await fetch(`${API}/api/taskflows`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(r => r.json());
      if (created.error) {
        setError(created.error);
      } else {
        setSelectedId(created.id);
        await fetchFlows();
      }
    } catch (e) {
      setError(`Invalid steps JSON: ${e.message}`);
    } finally {
      setCreateBusy(false);
    }
  };

  const stats = useMemo(() => {
    const grouped = { running: 0, waiting: 0, completed: 0, failed: 0, cancelled: 0, queued: 0 };
    for (const flow of flows) {
      grouped[flow.status] = (grouped[flow.status] || 0) + 1;
    }
    return grouped;
  }, [flows]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-asos-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-4 lg:p-8 space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">TaskFlows</h1>
            <p className="text-xs text-gray-500 mt-1">Persistent background workflows with resume and cancel controls.</p>
          </div>
          <button
            onClick={() => fetchFlows({ withSpinner: true })}
            className="px-3 py-2 rounded-lg bg-asos-card border border-asos-border text-sm flex items-center gap-2 hover:border-asos-accent"
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
          {Object.entries(stats).map(([status, count]) => (
            <div key={status} className="bg-asos-card border border-asos-border rounded-lg px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-gray-400">{status}</div>
              <div className="text-lg font-semibold">{count}</div>
            </div>
          ))}
        </div>

        {error && (
          <div className="px-3 py-2 text-sm rounded-lg border border-red-600/40 bg-red-500/10 text-red-300">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="bg-asos-card border border-asos-border rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-asos-border flex items-center justify-between">
              <span className="text-sm font-medium">Flows</span>
              <span className="text-xs text-gray-500">{flows.length} total</span>
            </div>
            <div className="max-h-[440px] overflow-y-auto">
              {flows.map((flow) => (
                <button
                  key={flow.id}
                  onClick={() => loadFlow(flow.id)}
                  className={`w-full text-left px-4 py-3 border-b border-asos-border/30 hover:bg-black/20 ${
                    selectedId === flow.id ? 'bg-black/30' : ''
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-medium truncate">{flow.title}</div>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusClass(flow.status)}`}>
                      {flow.status}
                    </span>
                  </div>
                  <div className="text-[11px] text-gray-500 mt-1 font-mono">{flow.id}</div>
                </button>
              ))}
              {flows.length === 0 && (
                <div className="p-4 text-sm text-gray-500">No taskflows yet.</div>
              )}
            </div>
          </div>

          <div className="bg-asos-card border border-asos-border rounded-xl p-4 lg:col-span-2 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-lg font-semibold">{selectedFlow?.title || 'Select a flow'}</div>
                {selectedFlow?.id && <div className="text-[11px] text-gray-500 font-mono">{selectedFlow.id}</div>}
              </div>
              {selectedFlow && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => runAction('resume')}
                    disabled={actionBusy !== ''}
                    className="px-3 py-2 rounded-lg text-xs bg-blue-500/15 border border-blue-500/30 text-blue-200 flex items-center gap-1 disabled:opacity-50"
                  >
                    <Play size={12} className={actionBusy === 'resume' ? 'animate-pulse' : ''} />
                    Resume
                  </button>
                  <button
                    onClick={() => runAction('cancel')}
                    disabled={actionBusy !== ''}
                    className="px-3 py-2 rounded-lg text-xs bg-red-500/15 border border-red-500/30 text-red-200 flex items-center gap-1 disabled:opacity-50"
                  >
                    <XCircle size={12} className={actionBusy === 'cancel' ? 'animate-pulse' : ''} />
                    Cancel
                  </button>
                </div>
              )}
            </div>

            {selectedFlow?.steps?.length ? (
              <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
                {selectedFlow.steps.map((step) => (
                  <div key={step.id} className="border border-asos-border rounded-lg p-3 bg-black/20">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium flex items-center gap-2">
                        <ListChecks size={13} className="text-asos-accent" />
                        Step {step.step_index + 1}: {step.step_type}
                      </div>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusClass(step.status)}`}>
                        {step.status}
                      </span>
                    </div>
                    {step.error && <div className="text-xs text-red-300 mt-2">{step.error}</div>}
                    {step.result && (
                      <pre className="mt-2 text-[11px] text-gray-300 whitespace-pre-wrap bg-black/30 rounded p-2 overflow-x-auto">
                        {JSON.stringify(step.result, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm text-gray-500">Choose a flow to inspect step timeline and outputs.</div>
            )}
          </div>
        </div>

        <div className="bg-asos-card border border-asos-border rounded-xl p-4 space-y-3">
          <div className="text-sm font-semibold">Create TaskFlow</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              className="bg-black border border-asos-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
              placeholder="Flow title"
            />
            <input
              value={newSessionId}
              onChange={(e) => setNewSessionId(e.target.value)}
              className="bg-black border border-asos-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent font-mono"
              placeholder="session_id (optional)"
            />
          </div>
          <textarea
            rows={8}
            value={newStepsJson}
            onChange={(e) => setNewStepsJson(e.target.value)}
            className="w-full bg-black border border-asos-border rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-asos-accent resize-y"
            placeholder='[{"type":"sleep","seconds":5}]'
          />
          <button
            onClick={createFlow}
            disabled={createBusy}
            className="px-4 py-2 rounded-lg bg-asos-accent text-white text-sm font-medium flex items-center gap-2 hover:bg-opacity-90 disabled:opacity-60"
          >
            {createBusy ? <Pause size={14} className="animate-pulse" /> : <Plus size={14} />}
            Create Flow
          </button>
        </div>
      </div>
    </div>
  );
}
