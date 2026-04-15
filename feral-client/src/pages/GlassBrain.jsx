import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

const COLORS = {
  brain: 0x06b6d4,
  memory: 0x8b5cf6,
  tool: 0xf59e0b,
  device: 0x10b981,
  alert: 0xef4444,
  calm: 0x3b82f6,
  stress: 0xef4444,
};

export default function GlassBrain() {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const [stats, setStats] = useState(null);

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

    // Render loop
    let frame = 0;
    const animate = () => {
      frame = requestAnimationFrame(animate);
      const t = Date.now() * 0.001;

      // Brain pulse
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

      renderer.render(scene, camera);
    };
    animate();

    const handleResize = () => {
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    window.addEventListener('resize', handleResize);

    const fetchStats = async () => {
      try {
        const r = await fetch('/api/dashboard');
        if (r.ok) setStats(await r.json());
      } catch { /* backend may be offline */ }
    };
    fetchStats();
    const interval = setInterval(fetchStats, 5000);

    sceneRef.current = { scene, renderer, brain, brainMat, pointLight, satellites };

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
      </div>
    </div>
  );
}
