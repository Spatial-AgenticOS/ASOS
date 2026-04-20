import { useEffect, useState } from 'react';
import { useFeralSocket } from './useFeralSocket';

export function useConnectionStatus() {
  const socket = useFeralSocket();
  const [state, setState] = useState(socket.state || 'closed');
  useEffect(() => socket.onState(setState), [socket]);
  return { state };
}
