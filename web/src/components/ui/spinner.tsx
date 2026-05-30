import { useEffect, useRef } from "react";

interface SpinnerProps {
  /** Outer dimension in CSS pixels. All internal geometry scales proportionally. */
  size?: number;
  /** RGB values for the trail color, e.g. "225, 223, 255". */
  color?: string;
  className?: string;
}

export function Spinner({ size = 40, color = "225, 223, 255", className }: SpinnerProps) {
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

    const scale = size / 220;
    const cx = size / 2;
    const cy = size / 2;
    const radius = 70 * scale;
    const lineWidth = Math.max(1, 10 * scale);
    const tailLength = 320;
    const speed = 0.03;
    const maxAlpha = 0.55;

    let angle = 0;
    const trailPoints: { x: number; y: number }[] = [];
    let animId: number;

    function draw() {
      ctx.clearRect(0, 0, size, size);

      const x = cx + Math.cos(angle) * radius;
      const y = cy + Math.sin(angle) * radius;
      trailPoints.push({ x, y });
      if (trailPoints.length > tailLength) trailPoints.shift();

      for (let i = 1; i < trailPoints.length; i++) {
        const t = i / trailPoints.length;
        const alpha = Math.pow(t, 2.8) * maxAlpha;
        ctx.beginPath();
        ctx.moveTo(trailPoints[i - 1].x, trailPoints[i - 1].y);
        ctx.lineTo(trailPoints[i].x, trailPoints[i].y);
        ctx.strokeStyle = `rgba(${color}, ${alpha})`;
        ctx.lineWidth = lineWidth;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.stroke();
      }

      angle += speed;
      animId = requestAnimationFrame(draw);
    }

    draw();
    return () => cancelAnimationFrame(animId);
  }, [size, color]);

  return <canvas ref={canvasRef} className={className} />;
}
