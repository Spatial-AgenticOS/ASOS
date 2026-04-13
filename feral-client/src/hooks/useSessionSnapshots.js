import { useState, useEffect } from 'react';
import { API_BASE } from '../config';

function historyToMessages(history = []) {
  return (history || [])
    .filter(h => h && ['user', 'assistant', 'system', 'tool'].includes(h.role))
    .map(h => {
      const content = typeof h.content === 'string' ? h.content : JSON.stringify(h.content || {});
      return { role: h.role === 'tool' ? 'assistant' : h.role, type: 'text', content };
    });
}

export function useSessionSnapshots({ sessionId, messages, setMessages }) {
  const [sessionSnapshots, setSessionSnapshots] = useState([]);
  const [sessionPanelOpen, setSessionPanelOpen] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionBusy, setSessionBusy] = useState('');
  const [sessionBranchName, setSessionBranchName] = useState('main');

  async function fetchSessionSnapshots() {
    if (!sessionId) return;
    setSessionLoading(true);
    try {
      const data = await fetch(
        `${API_BASE}/api/session/snapshots?session_id=${encodeURIComponent(sessionId)}&limit=50`,
      ).then(r => r.json());
      setSessionSnapshots(data.snapshots || []);
    } catch (e) {
      console.error('Snapshot list failed:', e);
    } finally {
      setSessionLoading(false);
    }
  }

  const createSnapshot = async () => {
    if (!sessionId) return;
    setSessionBusy('snapshot');
    try {
      await fetch(`${API_BASE}/api/session/snapshot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          label: `manual ${new Date().toLocaleString()}`,
          branch_name: sessionBranchName || 'main',
        }),
      });
      await fetchSessionSnapshots();
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: 'Session snapshot saved.' }]);
    } catch (e) {
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Snapshot failed: ${e.message}` }]);
    } finally {
      setSessionBusy('');
    }
  };

  const restoreSnapshot = async (snapshotId) => {
    if (!sessionId || !snapshotId) return;
    if (!window.confirm('Restore this snapshot into the current session?')) return;
    setSessionBusy(`restore:${snapshotId}`);
    try {
      const detail = await fetch(`${API_BASE}/api/session/snapshots/${encodeURIComponent(snapshotId)}`).then(r => r.json());
      const restored = await fetch(`${API_BASE}/api/session/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          snapshot_id: snapshotId,
          session_id: sessionId,
          as_new_session: false,
          label: `restore ${snapshotId}`,
        }),
      }).then(r => r.json());
      if (!restored.error && !detail.error) {
        setMessages([
          ...historyToMessages(detail.history || []),
          { role: 'system', type: 'text', content: `Restored snapshot ${snapshotId}` },
        ]);
        setSessionBranchName(detail.branch_name || 'main');
        await fetchSessionSnapshots();
      } else {
        setMessages(prev => [...prev, { role: 'system', type: 'text', content: restored.error || detail.error || 'Restore failed' }]);
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Restore failed: ${e.message}` }]);
    } finally {
      setSessionBusy('');
    }
  };

  const branchFromSnapshot = async (snapshotId) => {
    if (!sessionId || !snapshotId) return;
    setSessionBusy(`branch:${snapshotId}`);
    try {
      const branchName = (sessionBranchName || `branch-${Date.now()}`).trim();
      const detail = await fetch(`${API_BASE}/api/session/snapshots/${encodeURIComponent(snapshotId)}`).then(r => r.json());
      const branched = await fetch(`${API_BASE}/api/session/branch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          snapshot_id: snapshotId,
          branch_name: branchName,
          target_session_id: sessionId,
          label: `branch from ${snapshotId}`,
        }),
      }).then(r => r.json());
      if (!branched.error && !detail.error) {
        setMessages([
          ...historyToMessages(detail.history || []),
          { role: 'system', type: 'text', content: `Branched session to "${branchName}" from ${snapshotId}` },
        ]);
        setSessionBranchName(branchName);
        await fetchSessionSnapshots();
      } else {
        setMessages(prev => [...prev, { role: 'system', type: 'text', content: branched.error || detail.error || 'Branch failed' }]);
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'system', type: 'text', content: `Branch failed: ${e.message}` }]);
    } finally {
      setSessionBusy('');
    }
  };

  useEffect(() => {
    if (sessionPanelOpen && sessionId) fetchSessionSnapshots();
  }, [sessionPanelOpen, sessionId]);

  return {
    sessionSnapshots,
    sessionPanelOpen, setSessionPanelOpen,
    sessionLoading,
    sessionBusy,
    sessionBranchName, setSessionBranchName,
    fetchSessionSnapshots,
    createSnapshot,
    restoreSnapshot,
    branchFromSnapshot,
  };
}
