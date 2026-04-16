import { useEffect, useRef, useState, useCallback } from 'react';
import { useToast } from '../components/Toast';
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';

const API = import.meta.env.VITE_BRAIN_URL || `http://${location.hostname}:9090`;
const WS_URL = import.meta.env.VITE_BRAIN_WS || `ws://${location.hostname}:9090/v1/session`;

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
};

export default function GlassBrain() {
  const { addToast } = useToast();
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const eventsRef = useRef([]);
  const [stats, setStats] = useState(null);
  const [eventLog, setEventLog] = useState([]);

  const handleBrainEvent = useCallback((payload) => {
    const event = payload.event;
    const ts = new Date().toLocaleTimeString();
    eventsRef.current = [...eventsRef.current.slice(-9), { event, ts, ...payload }];
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
          sat.material.emissiveIntensity = 1.5;
          setTimeout(() => { sat.material.emissiveIntensity = 0.5; }, 500);
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
      }
    }
  }, []);

  const unmountedRef = useRef(false);

  useEffect(() => {
    unmountedRef.current = false;
    let ws;
    let reconnectTimer;

    function connect() {
      ws = new WebSocket(WS_URL);
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
      ws.onclose = () => { if (!unmountedRef.current) reconnectTimer = setTimeout(connect, 3000); };
      ws.onerror = () => { ws.close(); };
    }
    connect();

    return () => {
      unmountedRef.current = true;
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [handleBrainEvent]);

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

    // Central brain node — pulsing wireframe icosahedron
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

    // Inner glow sphere
    const glowGeo = new THREE.IcosahedronGeometry(0.6, 2);
    const glowMat = new THREE.MeshBasicMaterial({
      color: COLORS.brain,
      transparent: true,
      opacity: 0.15,
    });
    const glow = new THREE.Mesh(glowGeo, glowMat);
    scene.add(glow);

    // Memory-dust particle field
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

    // Orbiting satellite nodes (connected devices)
    const satellites = [];
    const deviceTypes = ['desktop', 'phone', 'glasses', 'wristband'];
    deviceTypes.forEach((type, i) => {
      const satGeo = new THREE.OctahedronGeometry(0.15, 0);
      const satMat = new THREE.MeshPhongMaterial({
        color: COLORS.device,
        emissive: COLORS.device,
        emissiveIntensity: 0.5,
      });
      const sat = new THREE.Mesh(satGeo, satMat);
      sat.userData = { type, angle: (i / deviceTypes.length) * Math.PI * 2, radius: 3, speed: 0.3 + i * 0.1 };
      scene.add(sat);
      satellites.push(sat);
    });

    // Lighting
    scene.add(new THREE.AmbientLight(0x111122, 0.5));
    const pointLight = new THREE.PointLight(COLORS.brain, 2, 15);
    pointLight.position.set(0, 0, 0);
    scene.add(pointLight);

    // Tool activation ring
    const ringGeo = new THREE.TorusGeometry(2, 0.02, 8, 64);
    const ringMat = new THREE.MeshBasicMaterial({ color: COLORS.tool, transparent: true, opacity: 0.2 });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = Math.PI / 2;
    scene.add(ring);

    // Bloom post-processing
    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloomPass = new UnrealBloomPass(
      new THREE.Vector2(mount.clientWidth, mount.clientHeight),
      0.8, 0.3, 0.85
    );
    composer.addPass(bloomPass);

    // Render loop
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

      camera.position.x = Math.sin(t * 0.2) * 0.5;
      camera.position.y = 2 + Math.sin(t * 0.3) * 0.3;
      camera.lookAt(0, 0, 0);

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
        const r = await fetch(`${API}/api/dashboard`);
        if (!r.ok) return;
        const data = await r.json();
        setStats(data);
        if (data?.somatic?.cognitive_load != null) {
          if (data.somatic.cognitive_load > 0.7) {
            brainMat.color.setHex(0xef4444);
          } else if (data.somatic.cognitive_load > 0.4) {
            brainMat.color.setHex(0xf59e0b);
          } else {
            brainMat.color.setHex(0x06b6d4);
          }
        }
      } catch (e) { addToast(e.message || 'Failed to load dashboard stats'); }
    };
    fetchStats();
    const interval = setInterval(fetchStats, 5000);

    sceneRef.current = { scene, renderer, composer, brain, brainMat, pointLight, satellites, ring, ringMat, particlesMat };

    return () => {
      cancelAnimationFrame(frame);
      clearInterval(interval);
      window.removeEventListener('resize', handleResize);
      mount.removeChild(renderer.domElement);
      renderer.dispose();
    };
  }, []);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100vh', background: '#050510' }}>
      <div ref={mountRef} style={{ width: '100%', height: '100%' }} />

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
            <div>Sessions: {stats.sessions || 0}</div>
            <div>Devices: {stats.devices?.length || 0}</div>
            <div>Skills: {stats.skills || 0}</div>
            <div>Memory: {stats.memory?.notes || 0} notes / {stats.memory?.episodes || 0} episodes</div>
            {stats.health?.heart_rate > 0 && <div>HR: {stats.health.heart_rate} bpm</div>}
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
          maxWidth: 360, pointerEvents: 'none',
        }}>
          <div style={{ color: '#71717a', fontSize: 10, marginBottom: 6, letterSpacing: 1 }}>BRAIN EVENTS</div>
          {[...eventLog].reverse().map((ev, i) => (
            <div key={i} style={{
              color: EVENT_COLORS[ev.event] || '#06b6d4',
              opacity: 1 - i * 0.08,
              lineHeight: 1.6,
            }}>
              [{ev.ts}] {ev.event} {ev.tool || ev.type || ev.model || ''}
            </div>
          ))}
        </div>
      )}

      {/* Legend */}
      <div style={{
        position: 'absolute', bottom: 20, right: 20,
        color: '#71717a', fontSize: 11, fontFamily: 'monospace',
        background: 'rgba(5,5,16,0.7)', padding: '8px 12px', borderRadius: 6,
      }}>
        <div><span style={{ color: '#06b6d4' }}>●</span> Brain core</div>
        <div><span style={{ color: '#8b5cf6' }}>●</span> Memory particles</div>
        <div><span style={{ color: '#f59e0b' }}>●</span> Tool ring</div>
        <div><span style={{ color: '#10b981' }}>●</span> Device satellites</div>
        <div><span style={{ color: '#ef4444' }}>●</span> Proactive alert</div>
      </div>
    </div>
  );
}
