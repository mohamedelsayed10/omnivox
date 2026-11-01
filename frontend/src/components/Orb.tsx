import { useEffect, useRef, type MutableRefObject } from "react";
import type { VoiceState } from "../state/voiceTypes";

type RGB = [number, number, number];

interface Look {
  a: RGB;
  b: RGB;
  c: RGB;
  /** base blob distortion */
  amp: number;
  /** how strongly audio level deforms the blob */
  gain: number;
  speed: number;
  /** orbiting arcs (waiting states) */
  spin: number;
  /** expanding rings (listening) */
  ripple: number;
  glow: number;
}

const LOOKS: Record<VoiceState, Look> = {
  disconnected: { a: [96, 108, 135], b: [58, 66, 92], c: [160, 170, 195], amp: 0.018, gain: 0, speed: 0.25, spin: 0, ripple: 0, glow: 0.1 },
  connecting: { a: [200, 150, 90], b: [139, 123, 255], c: [255, 222, 175], amp: 0.04, gain: 0, speed: 0.9, spin: 1, ripple: 0, glow: 0.2 },
  initializing: { a: [200, 150, 90], b: [139, 123, 255], c: [255, 222, 175], amp: 0.04, gain: 0, speed: 0.9, spin: 1, ripple: 0, glow: 0.2 },
  idle: { a: [139, 123, 255], b: [70, 120, 255], c: [190, 182, 255], amp: 0.035, gain: 0.05, speed: 0.4, spin: 0, ripple: 0, glow: 0.2 },
  listening: { a: [34, 211, 238], b: [59, 130, 246], c: [150, 232, 255], amp: 0.05, gain: 0.2, speed: 0.9, spin: 0, ripple: 1, glow: 0.26 },
  thinking: { a: [176, 132, 252], b: [240, 150, 60], c: [255, 214, 170], amp: 0.06, gain: 0, speed: 1.5, spin: 1, ripple: 0, glow: 0.24 },
  speaking: { a: [244, 114, 182], b: [139, 123, 255], c: [140, 190, 255], amp: 0.07, gain: 0.3, speed: 1.3, spin: 0, ripple: 0.35, glow: 0.34 },
  failed: { a: [248, 113, 113], b: [190, 60, 90], c: [255, 180, 180], amp: 0.03, gain: 0, speed: 0.5, spin: 0, ripple: 0, glow: 0.2 },
};

const rgba = (c: RGB, a: number) => `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${a})`;
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const lerpRGB = (a: RGB, b: RGB, k: number): RGB => [lerp(a[0], b[0], k), lerp(a[1], b[1], k), lerp(a[2], b[2], k)];

interface Anim {
  t: number;
  last: number;
  level: number;
  amp: number;
  gain: number;
  speed: number;
  spin: number;
  ripple: number;
  glow: number;
  a: RGB;
  b: RGB;
  c: RGB;
}

/**
 * Canvas orb: a layered, audio-reactive blob whose colour and motion follow the
 * agent state. Audio levels are read from refs each frame, so the component
 * never re-renders at audio rate.
 */
export function Orb({
  state,
  mic,
  agent,
  theme,
  reducedMotion,
}: {
  state: VoiceState;
  mic: MutableRefObject<number>;
  agent: MutableRefObject<number>;
  theme: "dark" | "light";
  reducedMotion: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const live = useRef({ state, theme, reducedMotion });
  live.current = { state, theme, reducedMotion };

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const look0 = LOOKS[live.current.state];
    const anim: Anim = {
      t: 0,
      last: performance.now(),
      level: 0,
      amp: look0.amp,
      gain: look0.gain,
      speed: look0.speed,
      spin: look0.spin,
      ripple: look0.ripple,
      glow: look0.glow,
      a: look0.a,
      b: look0.b,
      c: look0.c,
    };

    let w = 0;
    let h = 0;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    let raf = 0;
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const { state: st, theme: th, reducedMotion: calm } = live.current;
      const look = LOOKS[st];
      const dt = Math.min(0.05, (now - anim.last) / 1000);
      anim.last = now;

      // ease every parameter toward the current state's look
      const k = 1 - Math.exp(-dt * 5);
      anim.amp = lerp(anim.amp, look.amp * (calm ? 0.5 : 1), k);
      anim.gain = lerp(anim.gain, look.gain * (calm ? 0.6 : 1), k);
      anim.speed = lerp(anim.speed, look.speed * (calm ? 0.25 : 1), k);
      anim.spin = lerp(anim.spin, calm ? 0 : look.spin, k);
      anim.ripple = lerp(anim.ripple, calm ? 0 : look.ripple, k);
      anim.glow = lerp(anim.glow, look.glow, k);
      anim.a = lerpRGB(anim.a, look.a, k);
      anim.b = lerpRGB(anim.b, look.b, k);
      anim.c = lerpRGB(anim.c, look.c, k);
      anim.t += dt * anim.speed;

      // audio level: the mic while listening, the agent's voice while speaking
      const raw = st === "speaking" ? agent.current : st === "listening" ? mic.current : st === "idle" ? mic.current * 0.4 : 0;
      const shaped = Math.min(1, Math.pow(Math.max(0, raw) * 2.6, 0.62));
      anim.level = lerp(anim.level, shaped, 1 - Math.exp(-dt * (shaped > anim.level ? 24 : 7)));

      const S = Math.min(w, h);
      const cx = w / 2;
      const cy = h / 2;
      const lvl = anim.level;
      const R = S * 0.25 * (1 + 0.025 * Math.sin(anim.t * 1.3) + lvl * 0.1);
      const amp = anim.amp + lvl * anim.gain;
      const dark = th === "dark";

      ctx.clearRect(0, 0, w, h);

      // soft halo
      const halo = ctx.createRadialGradient(cx, cy, R * 0.5, cx, cy, R * 2.6);
      halo.addColorStop(0, rgba(anim.a, (anim.glow + lvl * 0.3) * (dark ? 1 : 0.7)));
      halo.addColorStop(0.5, rgba(anim.b, (anim.glow + lvl * 0.15) * 0.4));
      halo.addColorStop(1, rgba(anim.b, 0));
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, w, h);

      // expanding rings
      if (anim.ripple > 0.02) {
        for (let j = 0; j < 3; j++) {
          const p = (anim.t * 0.28 + j / 3) % 1;
          const rr = R * (1.12 + p * 0.9 + lvl * 0.15);
          ctx.beginPath();
          ctx.arc(cx, cy, rr, 0, Math.PI * 2);
          ctx.lineWidth = 1 + (1 - p) * 2.2;
          ctx.strokeStyle = rgba(anim.c, Math.pow(1 - p, 1.6) * anim.ripple * (0.18 + lvl * 0.6));
          ctx.stroke();
        }
      }

      // blob layers
      ctx.globalCompositeOperation = dark ? "lighter" : "source-over";
      const layers: Array<[number, number, number]> = dark
        ? [[1, 0, 0.44], [0.93, 2.1, 0.33], [0.84, 4.2, 0.26]]
        : [[1, 0, 0.92], [0.93, 2.1, 0.55], [0.84, 4.2, 0.4]];
      for (const [scale, phase, alpha] of layers) {
        const r = R * scale;
        ctx.beginPath();
        const N = 110;
        for (let i = 0; i <= N; i++) {
          const th2 = (i / N) * Math.PI * 2;
          const d =
            Math.sin(th2 * 2 + anim.t * 1.1 + phase) * amp +
            Math.sin(th2 * 3 - anim.t * 0.85 + phase * 1.7) * amp * 0.6 +
            Math.sin(th2 * 5 + anim.t * 1.7 + phase * 0.6) * amp * 0.35;
          const rr = r * (1 + d);
          const x = cx + Math.cos(th2) * rr;
          const y = cy + Math.sin(th2) * rr;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        const g = ctx.createRadialGradient(cx - r * 0.3, cy - r * 0.38, r * 0.05, cx, cy, r * 1.2);
        g.addColorStop(0, rgba(anim.c, alpha));
        g.addColorStop(0.5, rgba(anim.a, alpha));
        g.addColorStop(1, rgba(anim.b, alpha * 0.95));
        ctx.fillStyle = g;
        ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";

      // specular highlight
      const hl = ctx.createRadialGradient(cx - R * 0.32, cy - R * 0.4, 0, cx - R * 0.32, cy - R * 0.4, R * 0.6);
      hl.addColorStop(0, `rgba(255,255,255,${dark ? 0.32 : 0.55})`);
      hl.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = hl;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.02, 0, Math.PI * 2);
      ctx.fill();

      // orbiting arcs while waiting on something
      if (anim.spin > 0.02) {
        const ra = R * 1.34;
        for (let j = 0; j < 2; j++) {
          const a0 = anim.t * 1.6 + j * Math.PI;
          const len = 1.25;
          const g = ctx.createLinearGradient(
            cx + Math.cos(a0) * ra,
            cy + Math.sin(a0) * ra,
            cx + Math.cos(a0 + len) * ra,
            cy + Math.sin(a0 + len) * ra,
          );
          g.addColorStop(0, rgba(anim.c, 0));
          g.addColorStop(1, rgba(anim.c, 0.95 * anim.spin));
          ctx.beginPath();
          ctx.arc(cx, cy, ra, a0, a0 + len);
          ctx.lineWidth = 3.2;
          ctx.lineCap = "round";
          ctx.strokeStyle = g;
          ctx.stroke();
        }
      }
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [mic, agent]);

  return <canvas ref={canvasRef} className="orb-canvas" role="img" aria-label={`Voice visualizer, agent is ${state}`} />;
}
