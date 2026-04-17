import { useEffect, useRef, useState, useCallback } from 'react';
import { useToast } from '../components/Toast';
import { apiFetch, ensureClientApiKey } from '../api';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';

const API = import.meta.env.VITE_BRAIN_URL || `http://${location.hostname}:9090`;
const WS_BASE = import.meta.env.VITE_BRAIN_WS || `ws://${location.hostname}:9090/v1/session`;

function buildWsUrl(token) {
  const t = token || '';
  if (!t) return WS_BASE;
  const sep = WS_BASE.includes('?') ? '&' : '?';
  return `${WS_BASE}${sep}token=${encodeURIComponent(t)}`;
}

const COLORS = {
  brain: 0x06b6d4,
  memory: 0x8b5cf6,
  tool: 0xf59e0b,
  device: 0x10b981,
  alert: 0xef4444,
  calm: 0x3b82f6,
  stress: 0xef4444,
};

const EVENT_COLORS = {
  llm_call: '#06b6d4',
  tool_exec: '#f59e0b',
  memory_write: '#8b5cf6',
  device_telemetry: '#10b981',
  proactive_alert: '#ef4444',
  channel_message_in: '#3b82f6',
  channel_message_out: '#0ea5e9',
  voice_session: '#ec4899',
  email_received: '#a855f7',
  device_route: '#14b8a6',
};

const CHANNEL_COLORS = {
  telegram: 0x0088cc,
  discord: 0x5865f2,
  slack: 0x4a154b,
  whatsapp: 0x25d366,
  email: 0xa855f7,
};

const EVENT_MODES = {
  all: null,
  comms: new Set(['channel_message_in', 'channel_message_out', 'voice_session', 'email_received']),
  devices: new Set(['device_telemetry', 'device_route']),
  llm: new Set(['llm_call', 'tool_exec', 'memory_write']),
};

export default function GlassBrain() {
  const { addToast } = useToast();
  const [wsToken, setWsToken] = useState(
    () => (typeof localStorage !== 'undefined' ? localStorage.getItem('feral_api_key') || '' : ''),
  );
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const eventsRef = useRef([]);
  const [stats, setStats] = useState(null);
  const [eventLog, setEventLog] = useState([]);
  const [voiceActive, setVoiceActive] = useState(false);
  const [mode, setMode] = useState('all');
  const [inspected, setInspected] = useState(null);
  const modeRef = useRef(mode);
  const voiceActiveRef = useRef(voiceActive);

  useEffect(() => { modeRef.current = mode; }, [mode]);
  useEffect(() => { voiceActiveRef.current = voiceActive; }, [voiceActive]);

  const drawArc = useCallback((fromVec3, toVec3, color, durationMs = 2000) => {
    if (!sceneRef.current) return;
    const { scene } = sceneRef.current;
    const mid = new THREE.Vector3().addVectors(fromVec3, toVec3).multiplyScalar(0.5);
    mid.y += 1.5;
    const curve = new THREE.QuadraticBezierCurve3(fromVec3.clone(), mid, toVec3.clone());
    const points = curve.getPoints(32);
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.9 });
    const line = new THREE.Line(geo, mat);
    scene.add(line);
    if (!sceneRef.current.arcs) sceneRef.current.arcs = [];
    sceneRef.current.arcs.push(line);
    const start = Date.now();
    const fade = setInterval(() => {
      const elapsed = Date.now() - start;
      const progress = elapsed / durationMs;
      if (progress >= 1) {
        scene.remove(line);
        geo.dispose();
        mat.dispose();
        const idx = sceneRef.current.arcs?.indexOf(line);
        if (idx >= 0) sceneRef.current.arcs.splice(idx, 1);
        clearInterval(fade);
        return;
      }
      mat.opacity = 0.9 * (1 - progress);
    }, 30);
  }, []);

  const flashChannelSatellite = useCallback((channelType, direction) => {
    if (!sceneRef.current) return;
    const { satellites, brain } = sceneRef.current;
    const sat = satellites.find(s => s.userData.kind === 'channel' && s.userData.type === channelType);
    if (!sat) return;
    sat.material.emissiveIntensity = 2.0;
    setTimeout(() => { sat.material.emissiveIntensity = 0.5; }, 600);
    const from = direction === 'in' ? sat.position : brain.position;
    const to = direction === 'in' ? brain.position : sat.position;
    const color = direction === 'in' ? 0x3b82f6 : 0x0ea5e9;
    drawArc(from, to, color, 1500);
  }, [drawArc]);

  const flashVIPEmail = useCallback(() => {
    if (!sceneRef.current) return;
    const { scene, brain } = sceneRef.current;
    const burstCount = 12;
    for (let i = 0; i < burstCount; i++) {
      const geo = new THREE.SphereGeometry(0.04, 6, 6);
      const mat = new THREE.MeshBasicMaterial({ color: 0xa855f7, transparent: true, opacity: 1.0 });
      const particle = new THREE.Mesh(geo, mat);
      const angle = (i / burstCount) * Math.PI * 2;
      particle.position.copy(brain.position);
      const vel = new THREE.Vector3(Math.cos(angle) * 0.08, Math.random() * 0.04, Math.sin(angle) * 0.08);
      scene.add(particle);
      const fadeInt = setInterval(() => {
        particle.position.add(vel);
        mat.opacity -= 0.03;
        if (mat.opacity <= 0) { scene.remove(particle); geo.dispose(); mat.dispose(); clearInterval(fadeInt); }
      }, 25);
    }
  }, []);

  const drawRouteArc = useCallback((fromNodeId, toNodeId) => {
    if (!sceneRef.current) return;
    const { satellites, brain } = sceneRef.current;
    const fromPos = fromNodeId === 'brain' ? brain.position : (satellites.find(s => s.userData.nodeId === fromNodeId)?.position || brain.position);
    const toSat = satellites.find(s => s.userData.nodeId === toNodeId || s.userData.type === toNodeId);
    const toPos = toSat ? toSat.position : new THREE.Vector3(2, 1, 0);
    drawArc(fromPos, toPos, 0x14b8a6, 2000);
  }, [drawArc]);

  const handleBrainEvent = useCallback((payload) => {
    const event = payload.event;
    const modeFilter = EVENT_MODES[modeRef.current];
    if (modeFilter && !modeFilter.has(event)) return;

    const ts = new Date().toLocaleTimeString();

    const last = eventsRef.current[eventsRef.current.length - 1];
    if (last && last.event === event && last.type === payload.type) {
      last.count = (last.count || 1) + 1;
      last.ts = ts;
      eventsRef.current = [...eventsRef.current.slice(0, -1), last];
    } else {
      eventsRef.current = [...eventsRef.current.slice(-19), { event, ts, count: 1, ...payload }];
    }
    setEventLog([...eventsRef.current]);

    if (sceneRef.current) {
      const { scene, brain, brainMat, pointLight, satellites, ring, ringMat, particlesMat } = sceneRef.current;
      if (event === 'llm_call') {
        brainMat.emissiveIntensity = 1.0;
        pointLight.intensity = 5;
        setTimeout(() => { brainMat.emissiveIntensity = 0.3; pointLight.intensity = 2; }, 500);
      } else if (event === 'tool_exec') {
        ringMat.opacity = 0.8;
        ring.scale.setScalar(1.3);
        setTimeout(() => { ringMat.opacity = 0.2; ring.scale.setScalar(1); }, 600);
        const canvas = document.createElement('canvas');
        canvas.width = 256; canvas.height = 64;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#f59e0b';
        ctx.font = 'bold 24px monospace';
        ctx.fillText(payload.tool || 'tool', 10, 40);
        const texture = new THREE.CanvasTexture(canvas);
        const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true });
        const sprite = new THREE.Sprite(spriteMat);
        sprite.position.set(Math.random() * 2 - 1, 2, Math.random() * 2 - 1);
        sprite.scale.set(2, 0.5, 1);
        scene.add(sprite);
        const fadeInterval = setInterval(() => {
          sprite.position.y += 0.02;
          spriteMat.opacity -= 0.02;
          if (spriteMat.opacity <= 0) { scene.remove(sprite); texture.dispose(); spriteMat.dispose(); clearInterval(fadeInterval); }
        }, 30);
      } else if (event === 'memory_write') {
        particlesMat.opacity = 1.0;
        particlesMat.size = 0.08;
        setTimeout(() => { particlesMat.opacity = 0.5; particlesMat.size = 0.04; }, 700);
      } else if (event === 'device_telemetry') {
        satellites.forEach(sat => {
          if (sat.userData.kind !== 'channel') {
            sat.material.emissiveIntensity = 1.5;
            setTimeout(() => { sat.material.emissiveIntensity = 0.5; }, 500);
          }
        });
      } else if (event === 'proactive_alert') {
        brainMat.color.setHex(COLORS.alert);
        brainMat.emissive.setHex(COLORS.alert);
        pointLight.color.setHex(COLORS.alert);
        setTimeout(() => {
          brainMat.color.setHex(COLORS.brain);
          brainMat.emissive.setHex(COLORS.brain);
          pointLight.color.setHex(COLORS.brain);
        }, 1000);
      } else if (event === 'channel_message_in' || event === 'channel_message_out') {
        flashChannelSatellite(payload.channel, event === 'channel_message_in' ? 'in' : 'out');
      } else if (event === 'voice_session') {
        setVoiceActive(payload.active === true);
      } else if (event === 'email_received') {
        if (payload.vip) flashVIPEmail();
        else flashChannelSatellite('email', 'in');
      } else if (event === 'device_route') {
        drawRouteArc(payload.from_node, payload.to_node);
      }
    }
  }, [flashChannelSatellite, flashVIPEmail, drawRouteArc]);

  const unmountedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    ensureClientApiKey().then(() => {
      if (cancelled) return;
      const k = typeof localStorage !== 'undefined' ? localStorage.getItem('feral_api_key') || '' : '';
      setWsToken(k);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    unmountedRef.current = false;
    let ws;
    let reconnectTimer;

    function connect() {
      const url = buildWsUrl(wsToken);
      ws = new WebSocket(url);
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === 'brain_event') {
            handleBrainEvent(msg.payload);
          } else if (msg.type === 'state_push' && msg.event === 'proactive_alert') {
            handleBrainEvent({ event: 'proactive_alert', ...msg.data });
          }
        } catch (e) { addToast(e.message || 'Failed to parse brain event'); }
      };
      ws.onclose = (ev) => {
        if (!unmountedRef.current) {
          if (ev.code !== 1000) {
            addToast(
              `Brain WebSocket closed (${ev.code}). Check Settings → API key. ${!wsToken ? 'No API key in browser storage.' : ''}`,
            );
          }
          reconnectTimer = setTimeout(connect, 3000);
        }
      };
      ws.onerror = () => {
        addToast('Cannot connect to brain WebSocket — open Settings and confirm API key, or use http://localhost:9090 on this machine.');
        try { ws.close(); } catch (e) { /* ignore */ }
      };
    }
    connect();

    return () => {
      unmountedRef.current = true;
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [handleBrainEvent, wsToken, addToast]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x050510);
    scene.fog = new THREE.FogExp2(0x050510, 0.015);

    const camera = new THREE.PerspectiveCamera(60, mount.clientWidth / mount.clientHeight, 0.1, 1000);
    camera.position.set(0, 2, 8);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.5;
    controls.maxDistance = 20;
    controls.minDistance = 3;
    let userInteracted = false;
    controls.addEventListener('start', () => { userInteracted = true; controls.autoRotate = false; });

    const brainGeo = new THREE.IcosahedronGeometry(0.8, 3);
    const brainMat = new THREE.MeshPhongMaterial({
      color: COLORS.brain,
      emissive: COLORS.brain,
      emissiveIntensity: 0.3,
      transparent: true,
      opacity: 0.6,
      wireframe: true,
    });
    const brain = new THREE.Mesh(brainGeo, brainMat);
    scene.add(brain);

    const glowGeo = new THREE.IcosahedronGeometry(0.6, 2);
    const glowMat = new THREE.MeshBasicMaterial({
      color: COLORS.brain,
      transparent: true,
      opacity: 0.15,
    });
    const glow = new THREE.Mesh(glowGeo, glowMat);
    scene.add(glow);

    const particleCount = 500;
    const particlesGeo = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 20;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 20;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 20;
      const c = new THREE.Color(COLORS.memory);
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }
    particlesGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    particlesGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const particlesMat = new THREE.PointsMaterial({ size: 0.04, vertexColors: true, transparent: true, opacity: 0.5 });
    const particles = new THREE.Points(particlesGeo, particlesMat);
    scene.add(particles);

    const satellites = [];

    scene.add(new THREE.AmbientLight(0x111122, 0.5));
    const pointLight = new THREE.PointLight(COLORS.brain, 2, 15);
    pointLight.position.set(0, 0, 0);
    scene.add(pointLight);

    const ringGeo = new THREE.TorusGeometry(2, 0.02, 8, 64);
    const ringMat = new THREE.MeshBasicMaterial({ color: COLORS.tool, transparent: true, opacity: 0.2 });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = Math.PI / 2;
    scene.add(ring);

    // Voice ring — slightly larger, pink, hidden by default
    const voiceRingGeo = new THREE.TorusGeometry(2.3, 0.03, 8, 64);
    const voiceRingMat = new THREE.MeshBasicMaterial({ color: 0xec4899, transparent: true, opacity: 0 });
    const voiceRing = new THREE.Mesh(voiceRingGeo, voiceRingMat);
    voiceRing.rotation.x = Math.PI / 2;
    scene.add(voiceRing);

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloomPass = new UnrealBloomPass(
      new THREE.Vector2(mount.clientWidth, mount.clientHeight),
      0.8, 0.3, 0.85
    );
    composer.addPass(bloomPass);

    // Raycaster for click-to-inspect
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    const onCanvasClick = (e) => {
      const rect = mount.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const targets = [brain, ...satellites];
      const hits = raycaster.intersectObjects(targets, false);
      if (hits.length > 0) {
        const obj = hits[0].object;
        if (obj === brain) {
          setInspected({ kind: 'brain', type: 'brain', label: 'FERAL Brain Core' });
        } else if (obj.userData) {
          setInspected({
            kind: obj.userData.kind || 'device',
            type: obj.userData.type || 'unknown',
            label: (obj.userData.kind === 'channel' ? `${obj.userData.type} channel` : `${obj.userData.type} device`),
            nodeId: obj.userData.nodeId,
          });
        }
      } else {
        setInspected(null);
      }
    };
    mount.addEventListener('click', onCanvasClick);

    let frame = 0;
    const animate = () => {
      frame = requestAnimationFrame(animate);
      const t = Date.now() * 0.001;

      const pulse = 1 + Math.sin(t * 2) * 0.05;
      brain.scale.setScalar(pulse);
      glow.scale.setScalar(pulse * 0.75);
      brainMat.emissiveIntensity = 0.3 + Math.sin(t * 3) * 0.1;

      brain.rotation.y += 0.003;
      brain.rotation.x = Math.sin(t * 0.5) * 0.1;

      particles.rotation.y += 0.0005;
      particles.rotation.x += 0.0002;

      satellites.forEach(sat => {
        const d = sat.userData;
        d.angle += d.speed * 0.01;
        sat.position.x = Math.cos(d.angle) * d.radius;
        sat.position.z = Math.sin(d.angle) * d.radius;
        sat.position.y = Math.sin(d.angle * 2) * 0.5;
        sat.rotation.y += 0.02;
      });

      ring.scale.setScalar(1 + Math.sin(t * 1.5) * 0.05);

      // Voice ring pulse when active
      if (voiceActiveRef.current) {
        voiceRingMat.opacity = 0.4 + Math.sin(t * 4) * 0.3;
        voiceRing.scale.setScalar(1 + Math.sin(t * 3) * 0.08);
      } else {
        voiceRingMat.opacity = Math.max(0, voiceRingMat.opacity - 0.02);
      }

      controls.update();
      composer.render();
    };
    animate();

    const handleResize = () => {
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
      composer.setSize(mount.clientWidth, mount.clientHeight);
    };
    window.addEventListener('resize', handleResize);

    const fetchStats = async () => {
      try {
        const r = await apiFetch('/api/dashboard');
        if (!r.ok) {
          addToast(`Dashboard ${r.status}: add API key in Settings or open via localhost`);
          return;
        }
        const data = await r.json();
        setStats(data);
      } catch (e) { addToast(e.message || 'Failed to load dashboard stats'); }
    };
    fetchStats();
    const interval = setInterval(fetchStats, 5000);

    sceneRef.current = { scene, renderer, composer, camera, brain, brainMat, glowMat, pointLight, satellites, ring, ringMat, voiceRing, voiceRingMat, particlesMat, arcs: [] };

    return () => {
      cancelAnimationFrame(frame);
      clearInterval(interval);
      window.removeEventListener('resize', handleResize);
      mount.removeEventListener('click', onCanvasClick);
      controls.dispose();
      (sceneRef.current?.arcs || []).forEach(a => { scene.remove(a); a.geometry?.dispose(); a.material?.dispose(); });
      mount.removeChild(renderer.domElement);
      renderer.dispose();
    };
  }, []);

  // Dynamic satellite management — devices + channels
  useEffect(() => {
    if (!sceneRef.current) return;
    const { scene, satellites } = sceneRef.current;

    satellites.forEach(s => {
      scene.remove(s);
      if (s.geometry) s.geometry.dispose();
      if (s.material) s.material.dispose();
    });
    satellites.length = 0;

    const deviceList = stats?.devices || [];
    deviceList.forEach((device, i) => {
      const satGeo = new THREE.OctahedronGeometry(0.15, 0);
      const satMat = new THREE.MeshPhongMaterial({
        color: COLORS.device,
        emissive: COLORS.device,
        emissiveIntensity: 0.5,
      });
      const sat = new THREE.Mesh(satGeo, satMat);
      sat.userData = {
        kind: 'device',
        type: device.type || 'unknown',
        nodeId: device.node_id,
        angle: (i / Math.max(1, deviceList.length)) * Math.PI * 2,
        radius: 3,
        speed: 0.3 + i * 0.1,
      };
      scene.add(sat);
      satellites.push(sat);
    });

    const channelList = stats?.channels || [];
    channelList.forEach((channel, i) => {
      const satGeo = new THREE.TorusGeometry(0.2, 0.05, 8, 16);
      const color = CHANNEL_COLORS[channel.type] || 0x3b82f6;
      const satMat = new THREE.MeshPhongMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.5,
      });
      const sat = new THREE.Mesh(satGeo, satMat);
      sat.userData = {
        kind: 'channel',
        type: channel.type,
        angle: Math.PI + (i / Math.max(1, channelList.length)) * Math.PI,
        radius: 3.5,
        speed: 0.2 + i * 0.08,
      };
      scene.add(sat);
      satellites.push(sat);
    });
  }, [stats?.devices?.length, stats?.channels?.length]);

  // Brain color from somatic cognitive load
  useEffect(() => {
    if (!sceneRef.current) return;
    const { brainMat, glowMat, pointLight } = sceneRef.current;
    if (!brainMat) return;

    const load = stats?.somatic?.cognitive_load || 0;
    let color = 0x06b6d4;
    if (load > 0.7) color = 0xef4444;
    else if (load > 0.4) color = 0xf59e0b;

    brainMat.color.setHex(color);
    if (glowMat) glowMat.color.setHex(color);
    if (pointLight) pointLight.color.setHex(color);
  }, [stats?.somatic?.cognitive_load]);

  const filteredEventsForInspect = inspected
    ? eventLog.filter(ev => {
        if (inspected.kind === 'brain') return ['llm_call', 'tool_exec', 'memory_write', 'proactive_alert'].includes(ev.event);
        if (inspected.kind === 'channel') return (ev.event === 'channel_message_in' || ev.event === 'channel_message_out' || ev.event === 'email_received') && ev.channel === inspected.type;
        if (inspected.kind === 'device') return (ev.event === 'device_telemetry' || ev.event === 'device_route');
        return false;
      }).slice(-10)
    : [];

  const modeButtons = [
    { key: 'all', label: 'All' },
    { key: 'comms', label: 'Comms' },
    { key: 'devices', label: 'Devices' },
    { key: 'llm', label: 'LLM' },
  ];

  return (
    <div style={{ position: 'relative', width: '100%', height: '100vh', background: '#050510' }}>
      <div ref={mountRef} style={{ width: '100%', height: '100%' }} />

      {/* Mode toggle toolbar */}
      <div style={{
        position: 'absolute', top: 16, left: '50%', transform: 'translateX(-50%)',
        display: 'flex', gap: 2, background: 'rgba(5,5,16,0.85)',
        border: '1px solid rgba(6,182,212,0.2)', borderRadius: 20,
        padding: '3px 4px', fontFamily: 'monospace', fontSize: 12,
        zIndex: 10,
      }}>
        {modeButtons.map(b => (
          <button
            key={b.key}
            onClick={() => setMode(b.key)}
            style={{
              padding: '4px 14px', borderRadius: 16, border: 'none', cursor: 'pointer',
              background: mode === b.key ? 'rgba(6,182,212,0.25)' : 'transparent',
              color: mode === b.key ? '#06b6d4' : '#71717a',
              fontFamily: 'monospace', fontSize: 12, fontWeight: mode === b.key ? 600 : 400,
              transition: 'all 0.2s',
            }}
          >
            {b.label}
          </button>
        ))}
      </div>

      {/* Overlay stats */}
      <div style={{
        position: 'absolute', top: 20, left: 20,
        color: '#06b6d4', fontSize: 12, fontFamily: 'monospace',
        background: 'rgba(5,5,16,0.7)', padding: '12px 16px', borderRadius: 8,
        border: '1px solid rgba(6,182,212,0.2)',
      }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: '#fff' }}>FERAL Glass Brain</div>
        {stats && (
          <>
            <div>Sessions: {stats.session_count || 0}</div>
            <div>Devices: {stats.devices?.length || 0}</div>
            <div>Channels: {stats.channels?.length || 0}</div>
            <div>Skills: {stats.skills_count || 0}</div>
            <div>Memory: {stats.memory?.notes || 0} notes / {stats.memory?.episodes || 0} episodes</div>
            {stats.health?.heart_rate > 0 && <div>HR: {stats.health.heart_rate} bpm</div>}
            {voiceActive && <div style={{ color: '#ec4899' }}>Voice Active</div>}
          </>
        )}
      </div>

      {/* Live event log */}
      {eventLog.length > 0 && (
        <div style={{
          position: 'absolute', bottom: 20, left: 20,
          fontFamily: 'monospace', fontSize: 11,
          background: 'rgba(5,5,16,0.8)', padding: '10px 14px', borderRadius: 8,
          border: '1px solid rgba(6,182,212,0.15)',
          maxWidth: 400, maxHeight: 300, overflowY: 'auto', pointerEvents: 'none',
        }}>
          <div style={{ color: '#71717a', fontSize: 10, marginBottom: 6, letterSpacing: 1 }}>BRAIN EVENTS</div>
          {[...eventLog].reverse().map((ev, i) => (
            <div key={i} style={{
              color: EVENT_COLORS[ev.event] || '#06b6d4',
              opacity: 1 - i * 0.04,
              lineHeight: 1.6,
              fontSize: 11,
            }}>
              [{ev.ts}] {ev.event}
              {ev.count > 1 && <span style={{ color: '#71717a', marginLeft: 4 }}>x{ev.count}</span>}
              {ev.tool && <span style={{ color: '#71717a', marginLeft: 4 }}>{ev.tool}</span>}
              {ev.channel && <span style={{ color: '#71717a', marginLeft: 4 }}>{ev.channel}</span>}
              {ev.preview && <span style={{ color: '#52525b', marginLeft: 4 }}>{ev.preview.slice(0, 40)}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Click-to-inspect side panel */}
      {inspected && (
        <div style={{
          position: 'absolute', top: 80, right: 20,
          width: 280, maxHeight: 'calc(100vh - 140px)', overflowY: 'auto',
          background: 'rgba(5,5,16,0.92)', border: '1px solid rgba(6,182,212,0.25)',
          borderRadius: 10, padding: '14px 16px', fontFamily: 'monospace', fontSize: 12,
          color: '#a1a1aa',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ color: '#06b6d4', fontWeight: 600, fontSize: 13 }}>{inspected.label}</span>
            <button
              onClick={() => setInspected(null)}
              style={{ background: 'none', border: 'none', color: '#71717a', cursor: 'pointer', fontSize: 16, padding: 0 }}
            >
              &times;
            </button>
          </div>
          <div style={{ fontSize: 11, color: '#71717a', marginBottom: 8 }}>
            Kind: {inspected.kind} &middot; Type: {inspected.type}
            {inspected.nodeId && <span> &middot; Node: {inspected.nodeId}</span>}
          </div>
          <div style={{ fontSize: 10, color: '#52525b', marginBottom: 6, letterSpacing: 1 }}>RECENT EVENTS</div>
          {filteredEventsForInspect.length === 0 && (
            <div style={{ color: '#3f3f46', fontSize: 11 }}>No events yet for this node.</div>
          )}
          {filteredEventsForInspect.map((ev, i) => (
            <div key={i} style={{ color: EVENT_COLORS[ev.event] || '#06b6d4', fontSize: 11, lineHeight: 1.6 }}>
              [{ev.ts}] {ev.event}
              {ev.preview && <span style={{ color: '#52525b', marginLeft: 4 }}>{ev.preview.slice(0, 30)}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Onboarding overlay */}
      {(!stats || (stats?.devices?.length === 0 && stats?.channels?.length === 0 && eventLog.length === 0)) && (
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          background: 'rgba(5, 5, 16, 0.95)',
          border: '1px solid rgba(6,182,212,0.2)',
          borderRadius: 12,
          padding: '24px 32px',
          maxWidth: 440,
          textAlign: 'center',
          color: '#a1a1aa',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          pointerEvents: 'none',
        }}>
          <h3 style={{ color: '#06b6d4', marginBottom: 12, fontSize: 18, fontWeight: 600 }}>
            FERAL Glass Brain
          </h3>
          <p style={{ fontSize: 13, marginBottom: 16, lineHeight: 1.5 }}>
            Real-time visualization of the AI&apos;s cognition.
          </p>
          <div style={{ fontSize: 12, textAlign: 'left', lineHeight: 1.8 }}>
            <div><span style={{ color: '#06b6d4' }}>&#9679;</span> Brain flashes cyan on LLM calls</div>
            <div><span style={{ color: '#f59e0b' }}>&#9679;</span> Ring pulses amber on tool execution</div>
            <div><span style={{ color: '#8b5cf6' }}>&#9679;</span> Particles bloom on memory writes</div>
            <div><span style={{ color: '#10b981' }}>&#9679;</span> Octahedrons orbit for devices</div>
            <div><span style={{ color: '#3b82f6' }}>&#9679;</span> Torus rings orbit for channels</div>
            <div><span style={{ color: '#ec4899' }}>&#9679;</span> Pink ring pulses during voice</div>
            <div><span style={{ color: '#a855f7' }}>&#9679;</span> Purple burst on VIP emails</div>
            <div><span style={{ color: '#14b8a6' }}>&#9679;</span> Teal arcs for device routing</div>
            <div><span style={{ color: '#ef4444' }}>&#9679;</span> Brain turns red on health alerts</div>
          </div>
          <p style={{ fontSize: 11, marginTop: 16, color: '#71717a' }}>
            Start chatting or connect a device to see the brain come alive.
          </p>
        </div>
      )}

      {/* Legend */}
      <div style={{
        position: 'absolute', bottom: 20, right: 20,
        color: '#71717a', fontSize: 11, fontFamily: 'monospace',
        background: 'rgba(5,5,16,0.7)', padding: '8px 12px', borderRadius: 6,
      }}>
        <div><span style={{ color: '#06b6d4' }}>&#9679;</span> Brain core</div>
        <div><span style={{ color: '#8b5cf6' }}>&#9679;</span> Memory particles</div>
        <div><span style={{ color: '#f59e0b' }}>&#9679;</span> Tool ring</div>
        <div><span style={{ color: '#10b981' }}>&#9679;</span> Device satellites</div>
        <div><span style={{ color: '#3b82f6' }}>&#9679;</span> Channel satellites</div>
        <div><span style={{ color: '#ec4899' }}>&#9679;</span> Voice ring</div>
        <div><span style={{ color: '#a855f7' }}>&#9679;</span> VIP email</div>
        <div><span style={{ color: '#14b8a6' }}>&#9679;</span> Device route</div>
        <div><span style={{ color: '#ef4444' }}>&#9679;</span> Proactive alert</div>
      </div>
    </div>
  );
}
