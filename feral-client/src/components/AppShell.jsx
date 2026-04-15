import React from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import { LayoutDashboard, MessageSquare, Settings, Cpu, ListChecks, Clock, Sun, Moon, BrainCircuit } from 'lucide-react';
import { useTheme } from '../hooks/useTheme';
import TheOrb from './TheOrb';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/chat', icon: MessageSquare, label: 'Chat' },
  { to: '/taskflows', icon: ListChecks, label: 'Flows' },
  { to: '/timeline', icon: Clock, label: 'Timeline' },
  { to: '/glass-brain', icon: BrainCircuit, label: 'Glass Brain' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function AppShell() {
  const { theme, toggle: toggleTheme } = useTheme();

  return (
    <div className="flex flex-col lg:flex-row h-screen bg-feral-bg text-feral-text">
      {/* Desktop Sidebar */}
      <nav className="hidden lg:flex w-[220px] flex-shrink-0 bg-feral-surface border-r border-feral-border flex-col">
        <div className="flex items-center gap-3 px-5 py-5 border-b border-feral-border">
          <TheOrb size={28} mode="idle" connected />
          <div>
            <span className="font-semibold text-sm tracking-wide block">FERAL</span>
            <span className="text-[10px] text-feral-text-muted">Unleashed AI</span>
          </div>
        </div>

        <div className="flex-1 py-3 px-2.5 space-y-0.5">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all text-[13px] font-medium ${
                  isActive
                    ? 'bg-feral-accent-dim text-feral-accent'
                    : 'text-feral-text-secondary hover:text-feral-text hover:bg-feral-card-hover'
                }`
              }
            >
              <Icon size={17} className="flex-shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </div>

        <div className="px-4 py-4 border-t border-feral-border flex items-center justify-between">
          <div className="flex items-center gap-2 text-[11px] text-feral-text-muted">
            <Cpu size={11} />
            <span>v1.2.0</span>
          </div>
          <button
            onClick={toggleTheme}
            className="p-1.5 rounded-lg text-feral-text-muted hover:text-feral-text hover:bg-feral-card-hover transition"
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>
        </div>
      </nav>

      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>

      {/* Mobile Bottom Tab Bar */}
      <nav className="lg:hidden flex-shrink-0 bg-feral-surface border-t border-feral-border flex items-center justify-around px-1 py-1.5 safe-area-bottom">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-lg transition-all ${
                isActive ? 'text-feral-accent' : 'text-feral-text-muted'
              }`
            }
          >
            <Icon size={19} />
            <span className="text-[10px] font-medium">{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
