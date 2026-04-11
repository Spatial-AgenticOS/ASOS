import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import App from './App';
import SetupWizard from './pages/SetupWizard';
import Settings from './pages/Settings';
import Dashboard from './pages/Dashboard';
import TaskFlows from './pages/TaskFlows';
import AppShell from './components/AppShell';
import { API_BASE } from './config';
import './index.css';

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
        </Route>
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
