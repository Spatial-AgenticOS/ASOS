const BRAIN_HOST = import.meta.env.VITE_BRAIN_HOST || window.location.hostname || 'localhost';
const BRAIN_PORT = import.meta.env.VITE_BRAIN_PORT || '9090';
const BRAIN_PROTOCOL = window.location.protocol === 'https:' ? 'wss' : 'ws';
const HTTP_PROTOCOL = window.location.protocol === 'https:' ? 'https' : 'http';

export const API_BASE = `${HTTP_PROTOCOL}://${BRAIN_HOST}:${BRAIN_PORT}`;
export const WS_URL = `${BRAIN_PROTOCOL}://${BRAIN_HOST}:${BRAIN_PORT}/v1/session`;
