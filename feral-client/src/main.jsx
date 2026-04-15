import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import App from './App';
import SetupWizard from './pages/SetupWizard';
import Settings from './pages/Settings';
import Dashboard from './pages/Dashboard';
import TaskFlows from './pages/TaskFlows';
import Timeline from './pages/Timeline';
import Ambient from './pages/Ambient';
import AppShell from './components/AppShell';
import { API_BASE } from './config';
import { ToastProvider } from './components/Toast';
import 'highlight.js/styles/github-dark.css';
import './index.css';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, info) {
    console.error('FERAL Error Boundary:', error, info);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '2rem', textAlign: 'center', color: '#ff4444', background: '#0a0a0a', minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <h1 style={{ fontSize: '1.5rem', marginBottom: '1rem' }}>Something went wrong</h1>
          <p style={{ color: '#888', marginBottom: '1rem' }}>{this.state.error?.message}</p>
          <button onClick={() => window.location.reload()} style={{ padding: '0.5rem 1.5rem', background: '#222', border: '1px solid #444', color: '#fff', borderRadius: '6px', cursor: 'pointer' }}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function Root() {
  const [setupComplete, setSetupComplete] = React.useState(null);

  React.useEffect(() => {
    fetch(`${API_BASE}/api/setup/status`)
      .then(r => r.json())
      .then(data => setSetupComplete(data.setup_complete))
      .catch(() => setSetupComplete(false));
  }, []);

  if (setupComplete === null) {
    return (
      <div className="flex items-center justify-center h-screen bg-feral-bg">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-feral-accent border-t-transparent rounded-full animate-spin" />
          <span className="text-sm opacity-50">Connecting to FERAL Brain...</span>
        </div>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/setup" element={<SetupWizard onComplete={() => setSetupComplete(true)} />} />
        <Route element={<AppShell />}>
          <Route path="/" element={setupComplete ? <Dashboard /> : <Navigate to="/setup" />} />
          <Route path="/chat" element={setupComplete ? <App /> : <Navigate to="/setup" />} />
          <Route path="/settings" element={setupComplete ? <Settings /> : <Navigate to="/setup" />} />
          <Route path="/taskflows" element={setupComplete ? <TaskFlows /> : <Navigate to="/setup" />} />
          <Route path="/timeline" element={setupComplete ? <Timeline /> : <Navigate to="/setup" />} />
        </Route>
        <Route path="/ambient" element={setupComplete ? <Ambient /> : <Navigate to="/setup" />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <ToastProvider>
        <Root />
      </ToastProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
