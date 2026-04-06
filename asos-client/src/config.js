const BRAIN_HOST = import.meta.env.VITE_BRAIN_HOST || window.location.hostname || 'localhost';
const BRAIN_PORT = import.meta.env.VITE_BRAIN_PORT || window.location.port || '9090';
const BRAIN_PROTOCOL = window.location.protocol === 'https:' ? 'wss' : 'ws';
const HTTP_PROTOCOL = window.location.protocol === 'https:' ? 'https' : 'http';

const origin = `${BRAIN_HOST}${BRAIN_PORT ? ':' + BRAIN_PORT : ''}`;
export const API_BASE = `${HTTP_PROTOCOL}://${origin}`;
export const WS_URL = `${BRAIN_PROTOCOL}://${origin}/v1/session`;
