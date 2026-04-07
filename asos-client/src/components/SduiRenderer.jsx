import React, { useState, useRef, useEffect } from 'react';
import * as LucideIcons from 'lucide-react';

const LucideDynamicIcon = ({ name, size = 24, color = "currentColor" }) => {
  let iconName = name;
  if (name.includes('.')) {
    if (name.includes('checkmark')) iconName = 'CheckCircle';
    else if (name.includes('xmark')) iconName = 'XCircle';
    else if (name.includes('exclamation')) iconName = 'AlertTriangle';
    else if (name.includes('note')) iconName = 'StickyNote';
    else if (name.includes('brain')) iconName = 'Brain';
    else if (name.includes('heart')) iconName = 'Heart';
    else if (name.includes('shield')) iconName = 'Shield';
    else iconName = 'Activity';
  } else {
    iconName = name.split('-').map(str => str.charAt(0).toUpperCase() + str.slice(1)).join('');
  }
  const IconComponent = LucideIcons[iconName] || LucideIcons.HelpCircle;
  return <IconComponent size={size} color={color} />;
};

const LeafletMap = ({ lat, lon, zoom, markers, height }) => {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);

  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;
    const loadMap = async () => {
      try {
        const L = await import('leaflet');
        await import('leaflet/dist/leaflet.css');
        const map = L.map(mapRef.current).setView([lat || 0, lon || 0], zoom || 13);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          attribution: '&copy; OpenStreetMap',
          maxZoom: 19,
        }).addTo(map);
        if (markers && markers.length) {
          markers.forEach(m => {
            L.marker([m.lat, m.lon]).addTo(map)
              .bindPopup(m.label || '');
          });
        } else if (lat && lon) {
          L.marker([lat, lon]).addTo(map);
        }
        mapInstanceRef.current = map;
        setTimeout(() => map.invalidateSize(), 100);
      } catch {
        if (mapRef.current) {
          mapRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;opacity:0.5">Map: ${lat}, ${lon}</div>`;
        }
      }
    };
    loadMap();
    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, [lat, lon, zoom, markers]);

  return <div ref={mapRef} style={{ height: height || 200, width: '100%', borderRadius: 12 }} />;
};

const RealAudioPlayer = ({ url, label, action_id, onAction }) => {
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);

  const togglePlay = () => {
    if (!audioRef.current) return;
    if (playing) {
      audioRef.current.pause();
    } else {
      audioRef.current.play().catch(() => {});
    }
    setPlaying(!playing);
  };

  return (
    <div className="w-full bg-asos-card border border-asos-border rounded-xl p-3 flex items-center gap-3">
      <audio
        ref={audioRef}
        src={url}
        onTimeUpdate={() => {
          if (audioRef.current && audioRef.current.duration) {
            setProgress((audioRef.current.currentTime / audioRef.current.duration) * 100);
          }
        }}
        onEnded={() => { setPlaying(false); setProgress(0); }}
      />
      <button
        onClick={togglePlay}
        className="w-10 h-10 rounded-full bg-asos-accent flex items-center justify-center hover:scale-105 transition flex-shrink-0"
      >
        {playing ? <LucideIcons.Pause size={18} /> : <LucideIcons.Play size={18} />}
      </button>
      <div className="flex-1 min-w-0">
        {label && <span className="text-sm font-medium block truncate">{label}</span>}
        <div className="w-full h-1 bg-asos-border rounded-full mt-1">
          <div className="h-full bg-asos-accent rounded-full transition-all" style={{ width: `${progress}%` }} />
        </div>
      </div>
    </div>
  );
};

const GraphView = ({ nodes = [], links = [], height = 280 }) => {
  const w = 400;
  const h = height;
  const cx = w / 2;
  const cy = h / 2;
  const r = Math.min(w, h) * 0.36;
  const n = Math.max(nodes.length, 1);
  const pos = {};
  nodes.forEach((node, i) => {
    const id = node.id ?? node.name ?? `n${i}`;
    const ang = (2 * Math.PI * i) / n - Math.PI / 2;
    pos[id] = { x: cx + r * Math.cos(ang), y: cy + r * Math.sin(ang), label: node.name ?? id };
  });
  const lineKey = (l, i) => `${l.source}-${l.target}-${i}`;

  return (
    <div className="w-full bg-asos-card border border-asos-border rounded-xl overflow-hidden">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ maxHeight: h }}>
        {links.map((l, i) => {
          const a = pos[l.source];
          const b = pos[l.target];
          if (!a || !b) return null;
          return (
            <line
              key={lineKey(l, i)}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="rgba(255,255,255,0.25)"
              strokeWidth={1.5}
            />
          );
        })}
        {nodes.map((node, i) => {
          const id = node.id ?? node.name ?? `n${i}`;
          const p = pos[id];
          if (!p) return null;
          return (
            <g key={id}>
              <circle cx={p.x} cy={p.y} r={10} fill="#6c5ce7" opacity={0.9} />
              <text
                x={p.x}
                y={p.y + 22}
                textAnchor="middle"
                fill="rgba(255,255,255,0.75)"
                fontSize={10}
                style={{ pointerEvents: 'none' }}
              >
                {(p.label || '').slice(0, 18)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

const ChartView = ({ data, chart_type, label, color, height }) => {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || !data) return;
    const ctx = canvasRef.current.getContext('2d');
    const w = canvasRef.current.width;
    const h = canvasRef.current.height;
    ctx.clearRect(0, 0, w, h);

    const values = Array.isArray(data) ? data : Object.values(data);
    if (!values.length) return;
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const range = max - min || 1;
    const chartColor = color || '#6c5ce7';

    if (chart_type === 'bar') {
      const barW = (w - 20) / values.length;
      values.forEach((v, i) => {
        const barH = ((v - min) / range) * (h - 30);
        ctx.fillStyle = chartColor;
        ctx.fillRect(10 + i * barW + 2, h - 20 - barH, barW - 4, barH);
      });
    } else {
      ctx.beginPath();
      ctx.strokeStyle = chartColor;
      ctx.lineWidth = 2;
      values.forEach((v, i) => {
        const x = 10 + (i / (values.length - 1)) * (w - 20);
        const y = h - 20 - ((v - min) / range) * (h - 30);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
  }, [data, chart_type, color]);

  return (
    <div className="w-full">
      {label && <span className="text-sm font-medium mb-1 block">{label}</span>}
      <canvas ref={canvasRef} width={400} height={height || 150} className="w-full bg-asos-card border border-asos-border rounded-xl" />
    </div>
  );
};

const FormView = ({ fields, action_id, submit_label, onAction }) => {
  const [values, setValues] = useState({});

  const handleSubmit = (e) => {
    e.preventDefault();
    if (onAction) onAction(action_id || 'form_submit', values);
  };

  return (
    <form onSubmit={handleSubmit} className="w-full flex flex-col gap-3 bg-asos-card border border-asos-border rounded-xl p-4">
      {fields && fields.map((field, i) => (
        <div key={i} className="flex flex-col gap-1">
          <label className="text-xs opacity-70">{field.label || field.name}</label>
          {field.type === 'select' ? (
            <select
              className="bg-black border border-asos-border rounded-lg px-3 py-2 text-sm"
              value={values[field.name] || ''}
              onChange={e => setValues(prev => ({ ...prev, [field.name]: e.target.value }))}
            >
              <option value="">Select...</option>
              {(field.options || []).map((opt, j) => (
                <option key={j} value={opt.value || opt}>{opt.label || opt}</option>
              ))}
            </select>
          ) : field.type === 'textarea' ? (
            <textarea
              className="bg-black border border-asos-border rounded-lg px-3 py-2 text-sm resize-none"
              rows={3}
              placeholder={field.placeholder || ''}
              value={values[field.name] || ''}
              onChange={e => setValues(prev => ({ ...prev, [field.name]: e.target.value }))}
            />
          ) : (
            <input
              type={field.type || 'text'}
              className="bg-black border border-asos-border rounded-lg px-3 py-2 text-sm"
              placeholder={field.placeholder || ''}
              value={values[field.name] || ''}
              onChange={e => setValues(prev => ({ ...prev, [field.name]: e.target.value }))}
            />
          )}
        </div>
      ))}
      <button type="submit" className="px-4 py-2 bg-asos-accent text-white rounded-lg font-medium hover:bg-opacity-90 transition">
        {submit_label || 'Submit'}
      </button>
    </form>
  );
};

const WebViewComponent = ({ url, height, sandbox }) => (
  <iframe
    src={url}
    className="w-full border border-asos-border rounded-xl"
    style={{ height: height || 300 }}
    sandbox={sandbox || "allow-scripts allow-same-origin"}
    title="Embedded content"
  />
);

const TableView = ({ headers, rows, color }) => (
  <div className="w-full overflow-x-auto">
    <table className="w-full text-sm border border-asos-border rounded-xl overflow-hidden">
      {headers && (
        <thead>
          <tr className="bg-asos-card">
            {headers.map((h, i) => (
              <th key={i} className="text-left px-3 py-2 font-medium opacity-80 border-b border-asos-border">{h}</th>
            ))}
          </tr>
        </thead>
      )}
      <tbody>
        {rows && rows.map((row, i) => (
          <tr key={i} className="border-b border-asos-border last:border-0">
            {(Array.isArray(row) ? row : Object.values(row)).map((cell, j) => (
              <td key={j} className="px-3 py-2">{String(cell)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const CodeBlock = ({ code, language }) => (
  <pre className="w-full bg-black border border-asos-border rounded-xl p-4 overflow-x-auto text-sm font-mono">
    <code>{code}</code>
  </pre>
);

const MarkdownView = ({ content }) => (
  <div className="prose prose-invert prose-sm max-w-none" dangerouslySetInnerHTML={{ __html: content }} />
);

export const SduiRenderer = ({ node, onAction }) => {
  if (!node || typeof node !== 'object') return null;

  const {
    type, children, spacing, padding, value, style, color,
    corner_radius, name, size, label, action_id, text_color,
    columns, url, max_height, icon, unit,
  } = node;

  const sp = (sp) => {
    if (!sp) return '';
    const m = { 4: 'gap-1', 8: 'gap-2', 10: 'gap-2.5', 12: 'gap-3', 16: 'gap-4', 20: 'gap-5', 24: 'gap-6' };
    return m[sp] || 'gap-2';
  };
  const pd = (p) => {
    if (!p) return '';
    const m = { 8: 'p-2', 12: 'p-3', 16: 'p-4', 20: 'p-5', 24: 'p-6' };
    return m[p] || 'p-4';
  };

  switch (type) {
    case 'VStack':
      return (
        <div className={`flex flex-col ${sp(spacing)} ${pd(padding)} w-full`}>
          {children && children.map((c, i) => <SduiRenderer key={i} node={c} onAction={onAction} />)}
        </div>
      );
    case 'HStack':
      return (
        <div className={`flex flex-row items-center ${sp(spacing)} ${pd(padding)} w-full`}>
          {children && children.map((c, i) => <SduiRenderer key={i} node={c} onAction={onAction} />)}
        </div>
      );
    case 'Text': {
      let cls = 'text-base';
      if (style === 'headline') cls = 'text-xl font-bold tracking-wide';
      else if (style === 'subtitle') cls = 'text-lg font-semibold';
      else if (style === 'caption') cls = 'text-sm opacity-70';
      else if (style === 'body') cls = 'text-base leading-relaxed';
      return <span className={cls} style={{ color: color || 'inherit' }}>{value}</span>;
    }
    case 'Card':
      return (
        <div className={`bg-asos-card border border-asos-border backdrop-blur-md shadow-lg flex flex-col ${sp(spacing || 12)} p-4`}
          style={{ borderRadius: corner_radius || 12 }}>
          {children && children.map((c, i) => <SduiRenderer key={i} node={c} onAction={onAction} />)}
        </div>
      );
    case 'Icon':
      return <LucideDynamicIcon name={name} size={size} color={color} />;
    case 'Badge':
      return (
        <span className="px-2 py-1 text-xs font-semibold rounded-full w-max"
          style={{ backgroundColor: color || 'rgba(255,255,255,0.1)', color: text_color || '#fff' }}>
          {label}
        </span>
      );
    case 'Divider':
      return <div className="w-full h-px bg-asos-border my-2" />;
    case 'Button':
      return (
        <button
          onClick={() => onAction && onAction(action_id)}
          className={`px-4 py-2 rounded-lg font-medium transition-all hover:scale-105 active:scale-95 ${
            style === 'primary' ? 'bg-asos-accent text-white hover:bg-opacity-90'
            : style === 'danger' ? 'bg-red-600 text-white hover:bg-red-500'
            : 'bg-asos-card border border-asos-border hover:bg-white hover:bg-opacity-10'
          }`}>
          {label}
        </button>
      );
    case 'Image':
    case 'AsyncImage':
      return <img src={url || node.url} alt="" className="w-full h-auto object-cover" style={{ borderRadius: corner_radius || 8 }} loading="lazy" />;
    case 'Grid':
      return (
        <div className={`grid ${pd(padding)} ${sp(spacing || 12)} w-full`}
          style={{ gridTemplateColumns: `repeat(${columns || 2}, minmax(0, 1fr))` }}>
          {children && children.map((c, i) => <SduiRenderer key={i} node={c} onAction={onAction} />)}
        </div>
      );
    case 'ScrollView':
      return (
        <div className={`overflow-y-auto ${pd(padding)} w-full`} style={{ maxHeight: max_height || 400 }}>
          <div className={`flex flex-col ${sp(spacing || 12)}`}>
            {children && children.map((c, i) => <SduiRenderer key={i} node={c} onAction={onAction} />)}
          </div>
        </div>
      );
    case 'MetricCard':
      return (
        <div className="bg-asos-card border border-asos-border backdrop-blur-md shadow-lg p-4 flex flex-col items-center gap-2"
          style={{ borderRadius: corner_radius || 16 }}>
          {icon && <LucideDynamicIcon name={icon} size={28} color={color || '#6c5ce7'} />}
          <span className="text-3xl font-bold" style={{ color: color || '#fff' }}>{value}</span>
          {unit && <span className="text-xs opacity-60 uppercase tracking-wider">{unit}</span>}
          <span className="text-sm opacity-80">{label}</span>
        </div>
      );
    case 'ProgressBar':
      return (
        <div className="w-full">
          {label && <span className="text-xs opacity-70 mb-1 block">{label}</span>}
          <div className="w-full h-2 bg-asos-border rounded-full overflow-hidden">
            <div className="h-full rounded-full transition-all duration-500"
              style={{ width: `${Math.max(0, Math.min(100, (node.value || 0) * 100))}%`, backgroundColor: color || '#6c5ce7' }} />
          </div>
        </div>
      );
    case 'MapView':
      return <LeafletMap lat={node.lat || node.center_lat} lon={node.lon || node.center_lon} zoom={node.zoom} markers={node.markers} height={node.height} />;
    case 'GraphView':
      return <GraphView nodes={node.nodes} links={node.links} height={node.height} />;
    case 'AudioPlayer':
      return <RealAudioPlayer url={node.url || node.audio_url} label={label} action_id={action_id} onAction={onAction} />;
    case 'Chart':
    case 'ChartView':
      return <ChartView data={node.data} chart_type={node.chart_type} label={label} color={color} height={node.height} />;
    case 'Form':
    case 'FormView':
      return <FormView fields={node.fields} action_id={action_id} submit_label={node.submit_label} onAction={onAction} />;
    case 'WebView':
      return <WebViewComponent url={url} height={node.height} sandbox={node.sandbox} />;
    case 'Table':
    case 'TableView':
      return <TableView headers={node.headers} rows={node.rows} color={color} />;
    case 'CodeBlock':
      return <CodeBlock code={node.code || value} language={node.language} />;
    case 'Markdown':
      return <MarkdownView content={node.content || value} />;
    case 'VideoPlayer':
      return (
        <video src={node.url || url} controls className="w-full rounded-xl border border-asos-border"
          style={{ maxHeight: node.height || 300 }} />
      );
    case 'Skeleton':
      return (
        <div className="w-full animate-pulse">
          {Array.from({ length: node.lines || 3 }).map((_, i) => (
            <div key={i} className="h-4 bg-asos-border rounded mb-2" style={{ width: `${70 + Math.random() * 30}%` }} />
          ))}
        </div>
      );
    case 'Spacer':
      return <div style={{ height: node.height || 16 }} />;
    default:
      return (
        <div className="p-2 border border-yellow-600 text-yellow-500 text-xs rounded">
          Unknown: {type}
        </div>
      );
  }
};
