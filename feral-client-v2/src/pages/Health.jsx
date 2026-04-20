import React, { useEffect, useState } from 'react';
import { Heart, AlertTriangle, TrendingUp, Activity } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import Tabs from '../ui/Tabs';
import EmptyState from '../ui/EmptyState';
import StatusDot from '../ui/StatusDot';
import { apiJson } from '../lib/api';

export default function Health() {
  const [tab, setTab] = useState('summary');
  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane
        title="Health baseline"
        actions={(
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { id: 'summary', label: 'Summary' },
              { id: 'metrics', label: 'Metrics' },
              { id: 'alerts', label: 'Alerts' },
              { id: 'today', label: 'Today' },
            ]}
          />
        )}
      >
        <p className="v2-p v2-p--muted">
          FERAL's baseline engine watches your HR, sleep, activity, BP, and cognitive
          load. Deviations surface as alerts. Never diagnostic — always informational.
        </p>
      </Pane>
      {tab === 'summary' && <SummaryTab />}
      {tab === 'metrics' && <MetricsTab />}
      {tab === 'alerts' && <AlertsTab />}
      {tab === 'today' && <TodayTab />}
    </div>
  );
}

function SummaryTab() {
  const [s, setS] = useState(null);
  useEffect(() => { apiJson('/api/baseline/summary').then(setS).catch(() => setS({})); }, []);
  if (!s) return <Pane title="Summary"><EmptyState title="Loading…" /></Pane>;
  return (
    <Pane title="Summary">
      <div className="v2-grid v2-grid--stats">
        <Glass level={1} radius="md" padding="md">
          <div className="v2-stat-label">Metrics tracked</div>
          <div className="v2-stat-value">{s.metrics_tracked ?? 0}</div>
        </Glass>
        <Glass level={1} radius="md" padding="md">
          <div className="v2-stat-label">Recent alerts</div>
          <div className="v2-stat-value">{s.recent_alerts ?? 0}</div>
        </Glass>
        <Glass level={1} radius="md" padding="md">
          <div className="v2-stat-label">Categories</div>
          <div className="v2-stat-value">{Array.isArray(s.categories) ? s.categories.length : 0}</div>
        </Glass>
      </div>
      {Array.isArray(s.categories) && s.categories.length > 0 && (
        <div className="v2-skill-card-phrases" style={{ marginTop: 12 }}>
          {s.categories.map((c) => <span key={c} className="v2-chip">{c}</span>)}
        </div>
      )}
    </Pane>
  );
}

function MetricsTab() {
  const [metrics, setMetrics] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    apiJson('/api/baseline/metrics')
      .then((d) => setMetrics(d.metrics || d || []))
      .finally(() => setLoading(false));
  }, []);
  return (
    <Pane title={`Metrics (${metrics.length})`}>
      {loading && <EmptyState title="Loading…" />}
      {!loading && metrics.length === 0 && <EmptyState title="No metrics yet" hint="Pair a wristband or phone to start populating baselines." />}
      <div className="v2-skills-grid">
        {metrics.map((m, i) => (
          <Glass key={m.metric || i} level={0} radius="md" padding="md">
            <header className="v2-skill-card-head">
              <h3 className="v2-skill-card-name">{m.metric || m.name}</h3>
              {m.unit && <code className="v2-skill-card-id">{m.unit}</code>}
            </header>
            <div className="v2-stat-value">{typeof m.value === 'number' ? m.value.toFixed(1) : m.value}</div>
            <div className="v2-skill-card-meta">
              {m.trend && <span className="v2-chip"><TrendingUp size={10} /> {m.trend}</span>}
              {m.samples && <span className="v2-chip">{m.samples} samples</span>}
            </div>
          </Glass>
        ))}
      </div>
    </Pane>
  );
}

function AlertsTab() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    apiJson('/api/baseline/alerts')
      .then((d) => setAlerts(d.alerts || d || []))
      .finally(() => setLoading(false));
  }, []);

  const tone = (sev) => sev === 'high' || sev === 'critical' ? 'error' : sev === 'medium' ? 'warn' : 'live';

  return (
    <Pane title={`Alerts (${alerts.length})`}>
      {loading && <EmptyState title="Loading…" />}
      {!loading && alerts.length === 0 && <EmptyState title="No anomalies detected" />}
      <ul className="v2-mem-list">
        {alerts.map((a, i) => (
          <li key={a.id || i}>
            <Glass level={0} radius="md" padding="md">
              <div className="v2-flow-card-head">
                <StatusDot tone={tone(a.severity)} />
                <div className="v2-flow-card-title"><AlertTriangle size={12} /> {a.metric || a.title || a.id}</div>
                <div className="v2-flow-card-status">{a.severity}</div>
              </div>
              <div className="v2-mem-content">{a.message || a.description || JSON.stringify(a).slice(0, 160)}</div>
            </Glass>
          </li>
        ))}
      </ul>
    </Pane>
  );
}

function TodayTab() {
  const [today, setToday] = useState(null);
  useEffect(() => { apiJson('/api/health-summary').then(setToday).catch(() => setToday({})); }, []);
  if (!today) return <Pane title="Today"><EmptyState title="Loading…" /></Pane>;
  return (
    <Pane title="Today's vitals">
      <div className="v2-grid v2-grid--stats">
        {Object.entries(today).filter(([k]) => !k.startsWith('_')).map(([k, v]) => (
          <Glass key={k} level={1} radius="md" padding="md">
            <div className="v2-stat-label">{k.replace(/_/g, ' ')}</div>
            <div className="v2-stat-value">{typeof v === 'number' ? v : JSON.stringify(v).slice(0, 40)}</div>
          </Glass>
        ))}
      </div>
    </Pane>
  );
}
