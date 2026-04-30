import { useRef, useEffect, useCallback } from 'react';

const STATE_COLORS = {
  idle:       { r: 100, g: 116, b: 139 },
  listening:  { r:  59, g: 130, b: 246 },
  processing: { r: 255, g: 255, b: 255 },
  speaking:   { r:  34, g: 197, b:  94 },
  error:      { r: 239, g:  68, b:  68 },
};

const BASE_RADIUS_RATIO = 0.3;
const AUDIO_MODULATION = 0.12;
const GLOW_BLUR_MIN = 20;
const GLOW_BLUR_AUDIO = 30;
const ROTATION_SPEED = 0.015;
const PULSE_SPEED = 0.04;

/**
 * VoiceOrb — canvas-based animated orb for the voice agent UX.
 *
 * @param {{ state: 'idle'|'listening'|'processing'|'speaking'|'error', audioLevel: number }} props
 *   - state: current voice session state, drives color + animation style
 *   - audioLevel: 0–1 normalized RMS, drives radius modulation when listening/speaking
 */
export default function VoiceOrb({ state = 'idle', audioLevel = 0 }) {
  const canvasRef = useRef(null);
  const animRef = useRef(null);
  const phaseRef = useRef(0);
  const smoothLevelRef = useRef(0);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;

    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.scale(dpr, dpr);
    }

    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h / 2;
    const minDim = Math.min(w, h);
    const baseRadius = minDim * BASE_RADIUS_RATIO;

    const target = Math.max(0, Math.min(1, audioLevel));
    smoothLevelRef.current += (target - smoothLevelRef.current) * 0.15;
    const level = smoothLevelRef.current;

    phaseRef.current += (state === 'processing') ? ROTATION_SPEED : PULSE_SPEED;
    const phase = phaseRef.current;

    const color = STATE_COLORS[state] || STATE_COLORS.idle;
    let radius = baseRadius;
    let alpha = 1.0;

    if (state === 'idle') {
      alpha = 0.5;
      radius = baseRadius + Math.sin(phase) * 2;
    } else if (state === 'listening' || state === 'speaking') {
      radius = baseRadius + level * minDim * AUDIO_MODULATION;
      radius += Math.sin(phase * 2) * 3;
    } else if (state === 'processing') {
      radius = baseRadius + Math.sin(phase) * 4;
    } else if (state === 'error') {
      radius = baseRadius + Math.sin(phase * 3) * 2;
    }

    const blurSize = GLOW_BLUR_MIN + level * GLOW_BLUR_AUDIO;
    ctx.save();
    ctx.shadowColor = `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha * 0.6})`;
    ctx.shadowBlur = blurSize;

    const gradient = ctx.createRadialGradient(cx, cy, radius * 0.1, cx, cy, radius);
    gradient.addColorStop(0, `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`);
    gradient.addColorStop(0.7, `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha * 0.6})`);
    gradient.addColorStop(1, `rgba(${color.r}, ${color.g}, ${color.b}, 0)`);

    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fillStyle = gradient;
    ctx.fill();

    if (state === 'processing') {
      ctx.beginPath();
      const arcStart = phase % (Math.PI * 2);
      ctx.arc(cx, cy, radius * 0.85, arcStart, arcStart + Math.PI * 0.6);
      ctx.strokeStyle = `rgba(255, 255, 255, 0.4)`;
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      ctx.stroke();
    }

    ctx.restore();

    animRef.current = requestAnimationFrame(draw);
  }, [state, audioLevel]);

  useEffect(() => {
    animRef.current = requestAnimationFrame(draw);
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      data-testid="voice-orb-canvas"
      style={{ width: '100%', height: '100%', display: 'block', touchAction: 'none' }}
    />
  );
}

export { VoiceOrb };
