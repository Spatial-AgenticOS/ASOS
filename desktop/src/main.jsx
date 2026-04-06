import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom/client';

const BRAIN_PORT = 9090;
const BRAIN_URL = `http://localhost:${BRAIN_PORT}`;

function App() {
  const [brainReady, setBrainReady] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let attempts = 0;
    const check = async () => {
      try {
        const resp = await fetch(`${BRAIN_URL}/health`);
        if (resp.ok) { setBrainReady(true); setChecking(false); return; }
      } catch {}
      attempts++;
      if (attempts < 30) setTimeout(check, 2000);
      else setChecking(false);
    };
    check();
  }, []);

  if (checking && !brainReady) {
    return (
      <div style={styles.container}>
        <div style={styles.spinner} />
        <p style={styles.text}>Connecting to THEORA Brain...</p>
        <p style={styles.hint}>Make sure the server is running: <code>theora serve</code></p>
      </div>
    );
  }

  if (!brainReady) {
    return (
      <div style={styles.container}>
        <p style={styles.text}>THEORA Brain not reachable at localhost:{BRAIN_PORT}</p>
        <p style={styles.hint}>Start it with: <code>theora serve</code></p>
        <button style={styles.btn} onClick={() => { setChecking(true); setBrainReady(false); location.reload(); }}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={{ width: '100vw', height: '100vh', margin: 0, padding: 0, background: '#0a0a0f' }}>
      <iframe src={BRAIN_URL} style={{ width: '100%', height: '100%', border: 'none' }} title="THEORA" />
    </div>
  );
}

const styles = {
  container: {
    width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center', background: '#0a0a0f', color: '#e0e0e0',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  text: { fontSize: '1.2rem', marginBottom: '0.5rem' },
  hint: { fontSize: '0.85rem', opacity: 0.6 },
  btn: {
    marginTop: '1rem', padding: '0.6rem 1.5rem', background: '#6366f1', color: '#fff',
    border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '0.9rem',
  },
  spinner: {
    width: 40, height: 40, border: '3px solid #333', borderTop: '3px solid #6366f1',
    borderRadius: '50%', animation: 'spin 1s linear infinite', marginBottom: '1rem',
  },
};

const styleSheet = document.createElement('style');
styleSheet.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
document.head.appendChild(styleSheet);

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
