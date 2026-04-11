import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search, LayoutDashboard, Settings, ListChecks, MessageSquare,
  Zap, Heart, Sun, BookOpen, Cpu, Brain, Globe, Monitor, Home,
  Command,
} from 'lucide-react';

const ALL_ITEMS = [
  { id: 'briefing',   section: 'Quick Actions', icon: Zap,              label: 'Start morning briefing',   action: 'command', text: 'Give me my morning briefing' },
  { id: 'health',     section: 'Quick Actions', icon: Heart,            label: 'Check my health',          action: 'command', text: 'How is my health right now?' },
  { id: 'focus',      section: 'Quick Actions', icon: Sun,              label: 'Set lights to focus mode', action: 'command', text: 'Set the lights to focus mode' },
  { id: 'memory',     section: 'Quick Actions', icon: Brain,            label: 'Show my memories',         action: 'command', text: 'What do you remember about me?' },
  { id: 'web',        section: 'Quick Actions', icon: Globe,            label: 'Search the web',           action: 'command', text: 'Search the web for latest AI news' },
  { id: 'nav-dash',   section: 'Navigation',    icon: LayoutDashboard,  label: 'Dashboard',                action: 'navigate', path: '/' },
  { id: 'nav-chat',   section: 'Navigation',    icon: MessageSquare,    label: 'Chat',                     action: 'navigate', path: '/chat' },
  { id: 'nav-flows',  section: 'Navigation',    icon: ListChecks,       label: 'TaskFlows',                action: 'navigate', path: '/taskflows' },
  { id: 'nav-settings', section: 'Navigation',  icon: Settings,         label: 'Settings',                 action: 'navigate', path: '/settings' },
  { id: 'wiki',       section: 'Memory',        icon: BookOpen,         label: 'Memory Wiki',              action: 'toggle', target: 'wiki' },
];

export default function CommandPalette({ open, onClose, onCommand, onToggle }) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  const filtered = query.trim()
    ? ALL_ITEMS.filter(i => i.label.toLowerCase().includes(query.toLowerCase()))
    : ALL_ITEMS;

  const sections = [...new Set(filtered.map(i => i.section))];

  useEffect(() => {
    if (open) {
      setQuery('');
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (open) onClose();
        else onClose?.('open');
      }
      if (e.key === 'Escape' && open) {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const execute = useCallback((item) => {
    onClose();
    if (item.action === 'navigate') {
      navigate(item.path);
    } else if (item.action === 'command' && onCommand) {
      onCommand(item.text);
    } else if (item.action === 'toggle' && onToggle) {
      onToggle(item.target);
    }
  }, [onClose, onCommand, onToggle, navigate]);

  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelected(s => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelected(s => Math.max(s - 1, 0));
    } else if (e.key === 'Enter' && filtered[selected]) {
      e.preventDefault();
      execute(filtered[selected]);
    }
  };

  if (!open) return null;

  let flatIdx = 0;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] palette-backdrop" onClick={onClose}>
      <div
        className="palette-panel w-full max-w-md bg-asos-surface/95 backdrop-blur-2xl border border-asos-border-bright rounded-2xl shadow-2xl shadow-black/40 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-asos-border">
          <Search size={16} className="text-asos-text-muted flex-shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => { setQuery(e.target.value); setSelected(0); }}
            onKeyDown={handleKeyDown}
            placeholder="Search actions, pages, skills..."
            className="flex-1 bg-transparent text-sm text-asos-text placeholder:text-asos-text-muted outline-none"
          />
          <kbd className="hidden sm:inline text-[10px] text-asos-text-muted bg-asos-card px-1.5 py-0.5 rounded border border-asos-border font-mono">
            esc
          </kbd>
        </div>

        <div className="max-h-72 overflow-y-auto py-1">
          {filtered.length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-asos-text-muted">No results</div>
          )}
          {sections.map(section => {
            const sectionItems = filtered.filter(i => i.section === section);
            return (
              <div key={section}>
                <div className="px-4 pt-2 pb-1 text-[10px] text-asos-text-muted uppercase tracking-wider">{section}</div>
                {sectionItems.map(item => {
                  const idx = flatIdx++;
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.id}
                      onClick={() => execute(item)}
                      className={`w-full flex items-center gap-3 px-4 py-2 text-left text-sm transition-colors ${
                        idx === selected
                          ? 'bg-asos-accent-dim text-asos-accent'
                          : 'text-asos-text-secondary hover:bg-asos-card-hover'
                      }`}
                    >
                      <Icon size={15} className="flex-shrink-0 opacity-60" />
                      <span>{item.label}</span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-between px-4 py-2 border-t border-asos-border text-[10px] text-asos-text-muted">
          <span className="flex items-center gap-1">
            <Command size={10} /> K to toggle
          </span>
          <span>arrows to navigate · enter to select</span>
        </div>
      </div>
    </div>
  );
}
