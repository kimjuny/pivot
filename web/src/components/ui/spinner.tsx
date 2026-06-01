import { useEffect, useRef } from "react";

interface SpinnerProps {
  /** Outer dimension in CSS pixels. All internal geometry scales proportionally. */
  size?: number;
  /** RGB values for the trail color, e.g. "225, 223, 255". Defaults to current foreground color. */
  color?: string;
  className?: string;
}

/** Resolve a CSS variable to an "R, G, B" string for canvas usage. */
function resolveCssColor(cssVar: string): string {
  if (typeof window === "undefined") return "142, 142, 147";
  const el = document.documentElement;
  const raw = getComputedStyle(el).getPropertyValue(cssVar).trim();
  if (!raw) return "142, 142, 147";
  // Handle "R G B" or "R, G, B" or hex.
  if (/^\d{1,3}[\s,]+\d{1,3}[\s,]+\d{1,3}$/.test(raw)) {
    return raw.replace(/\s+/g, " ").replace(/\s*,\s*/g, " ");
  }
  if (raw.startsWith("#")) {
    const hex = raw.replace("#", "");
    const r = Number.parseInt(hex.slice(0, 2), 16);
    const g = Number.parseInt(hex.slice(2, 4), 16);
    const b = Number.parseInt(hex.slice(4, 6), 16);
    if (Number.isFinite(r) && Number.isFinite(g) && Number.isFinite(b)) {
      return `${r}, ${g}, ${b}`;
    }
  }
  return "142, 142, 147";
}

export function Spinner({ size = 40, color, className }: SpinnerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    ctx.scale(dpr, dpr);

    const trailColor = color ?? resolveCssColor("--foreground");

    const scale = size / 220;
    const cx = size / 2;
    const cy = size / 2;
    const radius = 90 * scale;
    const lineWidth = Math.max(1, 10 * scale);
    const tailLength = 320;
    const speed = 0.045;
    const maxAlpha = 0.55;

    let angle = 0;
    const trailPoints: { x: number; y: number }[] = [];
    let animId: number;

    // Pre-fill trail so the spinner looks fully-formed from the first frame
    for (let i = 0; i < tailLength; i++) {
      trailPoints.push({
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
      });
      angle += speed;
    }

    function draw() {
      ctx!.clearRect(0, 0, size, size);

      const x = cx + Math.cos(angle) * radius;
      const y = cy + Math.sin(angle) * radius;
      trailPoints.push({ x, y });
      if (trailPoints.length > tailLength) trailPoints.shift();

      for (let i = 1; i < trailPoints.length; i++) {
        const t = i / trailPoints.length;
        const alpha = Math.pow(t, 4) * maxAlpha;
        ctx!.beginPath();
        ctx!.moveTo(trailPoints[i - 1].x, trailPoints[i - 1].y);
        ctx!.lineTo(trailPoints[i].x, trailPoints[i].y);
        ctx!.strokeStyle = `rgba(${trailColor}, ${alpha})`;
        ctx!.lineWidth = lineWidth;
        ctx!.lineCap = "round";
        ctx!.lineJoin = "round";
        ctx!.stroke();
      }

      angle += speed;
      animId = requestAnimationFrame(draw);
    }

    draw();
    return () => cancelAnimationFrame(animId);
  }, [size, color]);

  return <canvas ref={canvasRef} className={className} />;
}
