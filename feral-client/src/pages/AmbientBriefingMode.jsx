import { useState, useEffect } from 'react';
import { Sun, Cloud, CloudRain, Snowflake, Zap } from 'lucide-react';
import { API_BASE } from '../config';

const WEATHER_ICONS = {
  Clear: Sun,
  Clouds: Cloud,
  Rain: CloudRain,
  Drizzle: CloudRain,
  Snow: Snowflake,
  Thunderstorm: Zap,
};

function formatTime(d) {
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

export default function AmbientBriefingMode({ time }) {
  const [briefing, setBriefing] = useState(null);
  const [nextEvent, setNextEvent] = useState(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/ambient/briefing`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${API_BASE}/api/ambient/next_event`).then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([b, n]) => {
      setBriefing(b);
      setNextEvent(n);
    });
  }, []);

  const WeatherIcon = WEATHER_ICONS[briefing?.weather?.condition] || Sun;

  return (
    <div className="flex flex-col items-center gap-5 max-w-md text-center px-4">
      {/* Greeting */}
      <h2 className="text-xl font-medium text-amber-400 tracking-wide">
        {briefing?.greeting || 'Good morning'}
      </h2>

      {/* Sleep recap */}
      {briefing?.sleep && (
        <div className="text-sm text-feral-text-secondary">
          HRV: <span className="text-feral-text font-medium">{briefing.sleep.hrv_ms}ms</span>
          <span className="mx-2 text-feral-text-muted">·</span>
          <span className="capitalize">{briefing.sleep.trend}</span>
        </div>
      )}

      {/* Weather + outfit */}
      {briefing?.weather && (
        <div className="flex flex-col items-center gap-1 bg-white/5 rounded-xl px-5 py-3 border border-white/5">
          <div className="flex items-center gap-2 text-sm text-feral-text">
            <WeatherIcon size={16} className="text-amber-300" />
            <span>{Math.round(briefing.weather.temp_c)}°C</span>
            <span className="text-feral-text-muted">—</span>
            <span className="text-feral-text-secondary capitalize">{briefing.weather.description}</span>
          </div>
          <div className="text-[11px] text-feral-text-muted">
            Outfit: {briefing.weather.outfit_hint}
          </div>
        </div>
      )}

      {/* Today's agenda */}
      {briefing?.agenda?.length > 0 && (
        <div className="w-full">
          <h3 className="text-[10px] text-feral-text-muted uppercase tracking-wider mb-2">Today's focus</h3>
          <ul className="space-y-1">
            {briefing.agenda.map((a, i) => (
              <li key={i} className="text-sm text-feral-text-secondary">
                • {a.description || a.title || a}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Next event */}
      {nextEvent?.event && (
        <div className="text-sm text-feral-text-secondary bg-white/5 rounded-lg px-4 py-2 border border-white/5">
          Next: <span className="text-feral-text">{nextEvent.event.title}</span>
          {nextEvent.event.start && (
            <span className="text-feral-text-muted ml-1">at {nextEvent.event.start}</span>
          )}
        </div>
      )}

      {/* Goals progress */}
      {briefing?.goals?.length > 0 && (
        <div className="w-full">
          <h3 className="text-[10px] text-feral-text-muted uppercase tracking-wider mb-2">Goals</h3>
          <div className="space-y-2">
            {briefing.goals.map((g, i) => (
              <div key={i}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-feral-text-secondary">{g.title}</span>
                  <span className="text-amber-400">{Math.round(g.progress * 100)}%</span>
                </div>
                <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-amber-400 rounded-full transition-all"
                    style={{ width: `${g.progress * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* VIP emails */}
      {briefing?.vip_emails?.length > 0 && (
        <div className="w-full">
          <h3 className="text-[10px] text-feral-text-muted uppercase tracking-wider mb-2">Waiting for you</h3>
          <div className="space-y-1">
            {briefing.vip_emails.map((e, i) => (
              <div key={i} className="text-xs text-feral-text-secondary truncate">
                <span className="text-feral-text">{e.from}</span>: {e.subject}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="text-[11px] text-feral-text-muted/40 mt-2">
        Say "Feral, run my morning" for voice briefing
      </div>
    </div>
  );
}
