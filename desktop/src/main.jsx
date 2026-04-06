import React from 'react';
import ReactDOM from 'react-dom/client';

/**
 * THEORA Desktop — Tauri wrapper
 *
 * This loads the THEORA web client in a native window.
 * In production, point VITE_BRAIN_HOST to localhost.
 * The Tauri sidecar can optionally start the Brain process.
 */

const BRAIN_URL = 'http://localhost:3000';

function App() {
  return (
    <div style={{
      width: '100vw', height: '100vh', margin: 0, padding: 0,
      display: 'flex', flexDirection: 'column', background: '#0a0a0f',
    }}>
      <iframe
        src={BRAIN_URL}
        style={{ flex: 1, border: 'none', width: '100%', height: '100%' }}
        title="THEORA"
      />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
