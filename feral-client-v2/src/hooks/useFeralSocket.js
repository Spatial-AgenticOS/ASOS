import { useEffect, useMemo } from 'react';
import { FeralSocket } from '../lib/ws';

/**
 * Single shared FeralSocket instance for the whole v2 app. Components call
 * `socket.subscribe(fn)` to receive every message; Ambient, LiveOps, Chat,
 * Forge all share the same connection.
 */
let sharedSocket = null;

function getShared() {
  if (!sharedSocket) {
    sharedSocket = new FeralSocket();
    sharedSocket.connect();
  }
  return sharedSocket;
}

export function useFeralSocket() {
  const socket = useMemo(() => getShared(), []);
  useEffect(() => {
    socket.connect();
  }, [socket]);
  return socket;
}
