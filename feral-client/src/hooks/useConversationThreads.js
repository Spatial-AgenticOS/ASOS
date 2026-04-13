import { useState, useRef, useCallback, useEffect } from 'react';
import { API_BASE } from '../config';

export function useConversationThreads({ messages, setMessages, sessionId }) {
  const [threadsOpen, setThreadsOpen] = useState(false);
  const [threads, setThreads] = useState([]);
  const [currentThreadId, setCurrentThreadId] = useState('');
  const [threadsDirty, setThreadsDirty] = useState(false);
  const suppressDirtyRef = useRef(false);

  const fetchThreads = async () => {
    try {
      const data = await fetch(`${API_BASE}/api/conversations?limit=50`).then(r => r.json());
      setThreads(data.conversations || []);
    } catch { /* ignore */ }
  };

  const createConversationThread = async () => {
    try {
      const data = await fetch(`${API_BASE}/api/conversations/new`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }).then(r => r.json());
      if (data.id) return data.id;
    } catch { /* ignore */ }
    return `thread-${Date.now()}`;
  };

  const saveCurrentThread = useCallback(async (msgs) => {
    if (!currentThreadId || !msgs || msgs.length < 2) return;
    try {
      await fetch(`${API_BASE}/api/conversations/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: currentThreadId, messages: msgs }),
      });
      setThreadsDirty(false);
      try { localStorage.setItem('feral-last-thread', currentThreadId); } catch {}
    } catch { /* ignore */ }
  }, [currentThreadId]);

  const restoreLastThread = async ({ force = false } = {}) => {
    try {
      if (!force && messages.length > 0) return;
      const lastId = localStorage.getItem('feral-last-thread');
      if (lastId) {
        const data = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(lastId)}`).then(r => r.json());
        if (data.messages && data.messages.length > 0) {
          suppressDirtyRef.current = true;
          setMessages(data.messages);
          setCurrentThreadId(lastId);
          setThreadsDirty(false);
          return;
        }
      }
      const list = await fetch(`${API_BASE}/api/conversations?limit=1`).then(r => r.json());
      const recent = (list.conversations || [])[0];
      if (recent?.id) {
        const data = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(recent.id)}`).then(r => r.json());
        if (data.messages && data.messages.length > 0) {
          suppressDirtyRef.current = true;
          setMessages(data.messages);
          setCurrentThreadId(recent.id);
          setThreadsDirty(false);
        }
      }
    } catch { /* fresh start */ }
  };

  const loadThread = async (threadId) => {
    try {
      if (threadId !== currentThreadId && currentThreadId && threadsDirty && messages.length >= 2) {
        await saveCurrentThread(messages);
      }
      const data = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(threadId)}`).then(r => r.json());
      if (data.messages) {
        suppressDirtyRef.current = true;
        setMessages(data.messages);
        setCurrentThreadId(threadId);
        setThreadsDirty(false);
        setThreadsOpen(false);
        try { localStorage.setItem('feral-last-thread', threadId); } catch {}
      }
    } catch { /* ignore */ }
  };

  const startNewThread = async () => {
    if (messages.length >= 2 && currentThreadId) {
      await saveCurrentThread(messages);
    }
    const threadId = await createConversationThread();
    suppressDirtyRef.current = true;
    setMessages([]);
    setCurrentThreadId(threadId);
    setThreadsDirty(false);
    try { localStorage.setItem('feral-last-thread', threadId); } catch {}
    setThreadsOpen(false);
    await fetchThreads();
  };

  const deleteThread = async (threadId) => {
    try {
      await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(threadId)}`, { method: 'DELETE' });
      setThreads(prev => prev.filter(t => t.id !== threadId));
      if (currentThreadId === threadId) {
        setMessages([]);
        setCurrentThreadId('');
      }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    restoreLastThread();
  }, []);

  useEffect(() => {
    if (!currentThreadId && sessionId) setCurrentThreadId(sessionId);
  }, [sessionId]);

  useEffect(() => {
    const handleStorage = (event) => {
      if (event.key !== 'feral-last-thread') return;
      if (!event.newValue || event.newValue === currentThreadId) return;
      if (messages.length > 0 || threadsDirty) return;
      restoreLastThread({ force: false });
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, [currentThreadId, messages.length, threadsDirty]);

  useEffect(() => {
    if (threadsDirty && messages.length >= 2) {
      const timer = setTimeout(() => saveCurrentThread(messages), 2000);
      return () => clearTimeout(timer);
    }
  }, [threadsDirty, messages, saveCurrentThread]);

  useEffect(() => {
    if (!currentThreadId) return;
    if (suppressDirtyRef.current) {
      suppressDirtyRef.current = false;
      return;
    }
    if (messages.length > 0) setThreadsDirty(true);
  }, [messages.length, currentThreadId]);

  useEffect(() => {
    const handleBeforeUnload = () => {
      if (currentThreadId && messages.length >= 2) {
        const payload = JSON.stringify({ id: currentThreadId, messages });
        navigator.sendBeacon(`${API_BASE}/api/conversations/save`, new Blob([payload], { type: 'application/json' }));
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [currentThreadId, messages]);

  useEffect(() => {
    if (threadsOpen) fetchThreads();
  }, [threadsOpen]);

  return {
    threads,
    threadsOpen, setThreadsOpen,
    currentThreadId,
    threadsDirty,
    fetchThreads,
    loadThread,
    startNewThread,
    deleteThread,
    saveCurrentThread,
    restoreLastThread,
  };
}
