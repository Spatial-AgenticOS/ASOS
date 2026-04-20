import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Shell from './shell/Shell';
import Chat from './pages/Chat';
import Forge from './pages/Forge';
import Devices from './pages/Devices';
import GenUICanvas from './pages/GenUICanvas';
import GlassBrain from './pages/GlassBrain';
import Timeline from './pages/Timeline';
import Flows from './pages/Flows';
import Intents from './pages/Intents';
import Home from './pages/Home';
import Marketplace from './pages/Marketplace';
import Settings from './pages/Settings';
import SetupWizard from './pages/SetupWizard';
import Skills from './pages/Skills';
import Memory from './pages/Memory';
import Wiki from './pages/Wiki';
import Identity from './pages/Identity';
import Agents from './pages/Agents';
import Health from './pages/Health';
import Webhooks from './pages/Webhooks';
import Geofences from './pages/Geofences';

export default function App() {
  return (
    <Routes>
      <Route path="/setup" element={<SetupWizard />} />
      <Route element={<Shell />}>
        <Route path="/" element={<Home />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/forge" element={<Forge />} />
        <Route path="/skills" element={<Skills />} />
        <Route path="/memory" element={<Memory />} />
        <Route path="/wiki" element={<Wiki />} />
        <Route path="/identity" element={<Identity />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/health" element={<Health />} />
        <Route path="/webhooks" element={<Webhooks />} />
        <Route path="/geofences" element={<Geofences />} />
        <Route path="/devices" element={<Devices />} />
        <Route path="/canvas" element={<GenUICanvas />} />
        <Route path="/glass-brain" element={<GlassBrain />} />
        <Route path="/timeline" element={<Timeline />} />
        <Route path="/flows" element={<Flows />} />
        <Route path="/intents" element={<Intents />} />
        <Route path="/marketplace" element={<Marketplace />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/ambient" element={<Home />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
