import React from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import { LayoutDashboard, MessageSquare, Settings, Brain, Cpu } from 'lucide-react';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/chat', icon: MessageSquare, label: 'Chat' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function AppShell() {
  return (
    <div className="flex h-screen bg-black text-white">
      {/* Sidebar */}
      <nav className="w-16 lg:w-56 flex-shrink-0 bg-asos-card border-r border-asos-border flex flex-col">
        <div className="flex items-center gap-2 px-4 py-5 border-b border-asos-border">
          <Brain size={22} className="text-asos-accent flex-shrink-0" />
          <span className="hidden lg:block font-bold tracking-wider text-sm">THEORA</span>
        </div>

        <div className="flex-1 py-4 space-y-1 px-2">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all text-sm ${
                  isActive
                    ? 'bg-asos-accent bg-opacity-20 text-asos-accent'
                    : 'text-gray-400 hover:text-white hover:bg-white hover:bg-opacity-5'
                }`
              }
            >
              <Icon size={18} className="flex-shrink-0" />
              <span className="hidden lg:block">{label}</span>
            </NavLink>
          ))}
        </div>

        <div className="px-3 py-4 border-t border-asos-border">
          <div className="flex items-center gap-2 text-xs opacity-40">
            <Cpu size={12} />
            <span className="hidden lg:block">v0.4.0</span>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
