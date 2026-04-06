import React from 'react';
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

export const SduiRenderer = ({ node, onAction }) => {
  if (!node || typeof node !== 'object') return null;

  const {
    type, children, spacing, padding, value, style, color,
    corner_radius, name, size, label, action_id, text_color,
    columns, url, max_height, icon, unit,
  } = node;

  const getSpacingClass = (sp) => {
    if (!sp) return '';
    const map = { 4: 'gap-1', 8: 'gap-2', 10: 'gap-2.5', 12: 'gap-3', 16: 'gap-4', 20: 'gap-5', 24: 'gap-6' };
    return map[sp] || 'gap-2';
  };

  const getPaddingClass = (pad) => {
    if (!pad) return '';
    const map = { 8: 'p-2', 12: 'p-3', 16: 'p-4', 20: 'p-5', 24: 'p-6' };
    return map[pad] || 'p-4';
  };

  switch (type) {
    case 'VStack':
      return (
        <div className={`flex flex-col ${getSpacingClass(spacing)} ${getPaddingClass(padding)} w-full`}>
          {children && children.map((child, i) => <SduiRenderer key={i} node={child} onAction={onAction} />)}
        </div>
      );

    case 'HStack':
      return (
        <div className={`flex flex-row items-center ${getSpacingClass(spacing)} ${getPaddingClass(padding)} w-full`}>
          {children && children.map((child, i) => <SduiRenderer key={i} node={child} onAction={onAction} />)}
        </div>
      );

    case 'Text': {
      let textClass = 'text-base';
      if (style === 'headline') textClass = 'text-xl font-bold tracking-wide';
      else if (style === 'subtitle') textClass = 'text-lg font-semibold';
      else if (style === 'caption') textClass = 'text-sm opacity-70';
      else if (style === 'body') textClass = 'text-base leading-relaxed';
      return <span className={textClass} style={{ color: color || 'inherit' }}>{value}</span>;
    }

    case 'Card':
      return (
        <div
          className={`bg-asos-card border border-asos-border backdrop-blur-md shadow-lg flex flex-col ${getSpacingClass(spacing || 12)} p-4`}
          style={{ borderRadius: corner_radius || 12 }}
        >
          {children && children.map((child, i) => <SduiRenderer key={i} node={child} onAction={onAction} />)}
        </div>
      );

    case 'Icon':
      return <LucideDynamicIcon name={name} size={size} color={color} />;

    case 'Badge':
      return (
        <span
          className="px-2 py-1 text-xs font-semibold rounded-full w-max"
          style={{ backgroundColor: color || 'rgba(255,255,255,0.1)', color: text_color || '#fff' }}
        >
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
            style === 'primary'
              ? 'bg-asos-accent text-white hover:bg-opacity-90'
              : style === 'danger'
              ? 'bg-red-600 text-white hover:bg-red-500'
              : 'bg-asos-card border border-asos-border hover:bg-white hover:bg-opacity-10'
          }`}
        >
          {label}
        </button>
      );

    case 'Image':
    case 'AsyncImage':
      return (
        <img
          src={url || node.url}
          alt=""
          className="w-full h-auto object-cover"
          style={{ borderRadius: corner_radius || 8 }}
          loading="lazy"
        />
      );

    case 'Grid':
      return (
        <div
          className={`grid ${getPaddingClass(padding)} ${getSpacingClass(spacing || 12)} w-full`}
          style={{ gridTemplateColumns: `repeat(${columns || 2}, minmax(0, 1fr))` }}
        >
          {children && children.map((child, i) => <SduiRenderer key={i} node={child} onAction={onAction} />)}
        </div>
      );

    case 'ScrollView':
      return (
        <div
          className={`overflow-y-auto ${getPaddingClass(padding)} w-full`}
          style={{ maxHeight: max_height || 400 }}
        >
          <div className={`flex flex-col ${getSpacingClass(spacing || 12)}`}>
            {children && children.map((child, i) => <SduiRenderer key={i} node={child} onAction={onAction} />)}
          </div>
        </div>
      );

    case 'MetricCard':
      return (
        <div
          className="bg-asos-card border border-asos-border backdrop-blur-md shadow-lg p-4 flex flex-col items-center gap-2"
          style={{ borderRadius: corner_radius || 16 }}
        >
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
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.max(0, Math.min(100, (node.value || 0) * 100))}%`,
                backgroundColor: color || '#6c5ce7',
              }}
            />
          </div>
        </div>
      );

    case 'MapView':
      return (
        <div
          className="w-full bg-asos-card border border-asos-border flex items-center justify-center text-sm opacity-50"
          style={{ height: node.height || 200, borderRadius: corner_radius || 12 }}
        >
          Map: {(node.lat || node.center_lat) && (node.lon || node.center_lon)
            ? `${node.lat || node.center_lat}, ${node.lon || node.center_lon}`
            : 'No coordinates'}
        </div>
      );

    case 'AudioPlayer':
      return (
        <div className="w-full bg-asos-card border border-asos-border rounded-xl p-3 flex items-center gap-3">
          <button
            onClick={() => onAction && onAction(action_id || 'audio_play')}
            className="w-10 h-10 rounded-full bg-asos-accent flex items-center justify-center hover:scale-105 transition"
          >
            <LucideIcons.Play size={18} />
          </button>
          <div className="flex-1">
            {label && <span className="text-sm font-medium block">{label}</span>}
            <div className="w-full h-1 bg-asos-border rounded-full mt-1">
              <div className="h-full bg-asos-accent rounded-full" style={{ width: '0%' }} />
            </div>
          </div>
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
