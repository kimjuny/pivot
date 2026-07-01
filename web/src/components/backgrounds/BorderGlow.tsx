import {
  useCallback,
  useEffect,
  useRef,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import "./BorderGlow.css";

/**
 * Pointer-tracking mesh-gradient border glow, ported to TypeScript from the
 * MIT-licensed react-bits <BorderGlow/> (https://reactbits.dev/components/border-glow).
 *
 * As the pointer moves over the card, two CSS custom properties are updated on
 * the element: `--edge-proximity` (how close the cursor is to an edge, 0–100)
 * and `--cursor-angle` (direction from the card center). Three layers
 * (`::before` border, `::after` fill, `.border-glow-edge` outer glow) are masked
 * by a conic gradient anchored at that angle and faded by that proximity, so the
 * colored bloom only appears where the pointer is, near the edge. Set
 * `animated` for a one-time sweep on mount instead of hover-only.
 */

export interface BorderGlowProps {
  children: ReactNode;
  className?: string;
  /** Lower = the glow only triggers closer to the edge (0–100). */
  edgeSensitivity?: number;
  /** Outer glow color as an "h s l" triple, e.g. "40 80 80". */
  glowColor?: string;
  /** Card background — any CSS color, including `var(--card)`. */
  backgroundColor?: string;
  borderRadius?: number;
  /** How far the outer glow reaches beyond the card, in px. */
  glowRadius?: number;
  glowIntensity?: number;
  /** Half-angle of the glow cone, in deg. */
  coneSpread?: number;
  /** Run a one-time sweep on mount instead of relying on hover. */
  animated?: boolean;
  /** Mesh-gradient colors (cycled across the seven gradient stops). */
  colors?: string[];
  fillOpacity?: number;
}

function parseHSL(hslStr: string): { h: number; s: number; l: number } {
  const match = hslStr.match(/([\d.]+)\s*([\d.]+)%?\s*([\d.]+)%?/);
  if (!match) return { h: 40, s: 80, l: 80 };
  return {
    h: parseFloat(match[1]),
    s: parseFloat(match[2]),
    l: parseFloat(match[3]),
  };
}

/** Build the `--glow-color*` opacity ramp driven by `glowIntensity`. */
function buildGlowVars(
  glowColor: string,
  intensity: number,
): Record<string, string> {
  const { h, s, l } = parseHSL(glowColor);
  const base = `${h}deg ${s}% ${l}%`;
  const opacities = [100, 60, 50, 40, 30, 20, 10];
  const keys = ["", "-60", "-50", "-40", "-30", "-20", "-10"];
  const vars: Record<string, string> = {};
  for (let i = 0; i < opacities.length; i++) {
    vars[`--glow-color${keys[i]}`] = `hsl(${base} / ${Math.min(opacities[i] * intensity, 100)}%)`;
  }
  return vars;
}

const GRADIENT_POSITIONS = [
  "80% 55%",
  "69% 34%",
  "8% 6%",
  "41% 38%",
  "86% 85%",
  "82% 18%",
  "51% 4%",
];
const GRADIENT_KEYS = [
  "--gradient-one",
  "--gradient-two",
  "--gradient-three",
  "--gradient-four",
  "--gradient-five",
  "--gradient-six",
  "--gradient-seven",
];
const COLOR_MAP = [0, 1, 2, 0, 1, 2, 1];

/** Build the seven `--gradient-*` mesh stops from the user's color palette. */
function buildGradientVars(colors: string[]): Record<string, string> {
  const vars: Record<string, string> = {};
  for (let i = 0; i < 7; i++) {
    const color = colors[Math.min(COLOR_MAP[i], colors.length - 1)];
    vars[GRADIENT_KEYS[i]] = `radial-gradient(at ${GRADIENT_POSITIONS[i]}, ${color} 0px, transparent 50%)`;
  }
  vars["--gradient-base"] = `linear-gradient(${colors[0]} 0 100%)`;
  return vars;
}

const easeOutCubic = (x: number): number => 1 - Math.pow(1 - x, 3);
const easeInCubic = (x: number): number => x * x * x;

interface AnimateOptions {
  start?: number;
  end?: number;
  duration?: number;
  delay?: number;
  ease?: (x: number) => number;
  onUpdate: (value: number) => void;
  onEnd?: () => void;
}

/**
 * Tweens a number over time with the given easing. Returns a cancel function so
 * callers can abort pending timeouts/frames on unmount — the upstream version
 * leaked both when the component unmounted mid-sweep.
 */
function animateValue(options: AnimateOptions): () => void {
  const {
    start = 0,
    end = 100,
    duration = 1000,
    delay = 0,
    ease = easeOutCubic,
    onUpdate,
    onEnd,
  } = options;

  const startTime = performance.now() + delay;
  let frameId = 0;
  let started = false;

  const tick = () => {
    const elapsed = performance.now() - startTime;
    const progress = Math.min(elapsed / duration, 1);
    onUpdate(start + (end - start) * ease(progress));
    if (progress < 1) {
      frameId = requestAnimationFrame(tick);
    } else {
      onEnd?.();
    }
  };

  const timeoutId = window.setTimeout(() => {
    started = true;
    frameId = requestAnimationFrame(tick);
  }, delay);

  return () => {
    window.clearTimeout(timeoutId);
    if (started) cancelAnimationFrame(frameId);
  };
}

const ANGLE_START = 110;
const ANGLE_END = 465;

export function BorderGlow({
  children,
  className,
  edgeSensitivity = 30,
  glowColor = "40 80 80",
  backgroundColor = "oklch(var(--card))",
  borderRadius = 28,
  glowRadius = 40,
  glowIntensity = 1.0,
  coneSpread = 25,
  animated = false,
  colors = ["#c084fc", "#f472b6", "#38bdf8"],
  fillOpacity = 0.5,
}: BorderGlowProps) {
  const cardRef = useRef<HTMLDivElement>(null);

  const getCenterOfElement = useCallback((el: HTMLElement): [number, number] => {
    const { width, height } = el.getBoundingClientRect();
    return [width / 2, height / 2];
  }, []);

  const getEdgeProximity = useCallback(
    (el: HTMLElement, x: number, y: number): number => {
      const [cx, cy] = getCenterOfElement(el);
      const dx = x - cx;
      const dy = y - cy;
      const kx = dx !== 0 ? cx / Math.abs(dx) : Infinity;
      const ky = dy !== 0 ? cy / Math.abs(dy) : Infinity;
      return Math.min(Math.max(1 / Math.min(kx, ky), 0), 1);
    },
    [getCenterOfElement],
  );

  const getCursorAngle = useCallback(
    (el: HTMLElement, x: number, y: number): number => {
      const [cx, cy] = getCenterOfElement(el);
      const dx = x - cx;
      const dy = y - cy;
      if (dx === 0 && dy === 0) return 0;
      let degrees = (Math.atan2(dy, dx) * 180) / Math.PI + 90;
      if (degrees < 0) degrees += 360;
      return degrees;
    },
    [getCenterOfElement],
  );

  const handlePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const card = cardRef.current;
      if (!card) return;
      const rect = card.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      card.style.setProperty("--edge-proximity", (getEdgeProximity(card, x, y) * 100).toFixed(3));
      card.style.setProperty("--cursor-angle", `${getCursorAngle(card, x, y).toFixed(3)}deg`);
    },
    [getEdgeProximity, getCursorAngle],
  );

  useEffect(() => {
    if (!animated) return;
    const card = cardRef.current;
    if (!card) return;

    card.classList.add("sweep-active");
    card.style.setProperty("--cursor-angle", `${ANGLE_START}deg`);

    const cancel: Array<() => void> = [];

    cancel.push(
      animateValue({
        duration: 500,
        onUpdate: (v) => card.style.setProperty("--edge-proximity", v.toFixed(3)),
      }),
    );

    cancel.push(
      animateValue({
        ease: easeInCubic,
        duration: 1500,
        end: 50,
        onUpdate: (v) =>
          card.style.setProperty(
            "--cursor-angle",
            `${(ANGLE_END - ANGLE_START) * (v / 100) + ANGLE_START}deg`,
          ),
      }),
    );

    cancel.push(
      animateValue({
        ease: easeOutCubic,
        delay: 1500,
        duration: 2250,
        start: 50,
        end: 100,
        onUpdate: (v) =>
          card.style.setProperty(
            "--cursor-angle",
            `${(ANGLE_END - ANGLE_START) * (v / 100) + ANGLE_START}deg`,
          ),
      }),
    );

    cancel.push(
      animateValue({
        ease: easeInCubic,
        delay: 2500,
        duration: 1500,
        start: 100,
        end: 0,
        onUpdate: (v) => card.style.setProperty("--edge-proximity", v.toFixed(3)),
        onEnd: () => card.classList.remove("sweep-active"),
      }),
    );

    return () => {
      for (const fn of cancel) fn();
      card.classList.remove("sweep-active");
    };
  }, [animated]);

  const style = {
    "--card-bg": backgroundColor,
    "--edge-sensitivity": edgeSensitivity,
    "--border-radius": `${borderRadius}px`,
    "--glow-padding": `${glowRadius}px`,
    "--cone-spread": coneSpread,
    "--fill-opacity": fillOpacity,
    ...buildGlowVars(glowColor, glowIntensity),
    ...buildGradientVars(colors),
  } as CSSProperties;

  return (
    <div
      ref={cardRef}
      onPointerMove={handlePointerMove}
      className={`border-glow-card ${className ?? ""}`.trim()}
      style={style}
    >
      <span className="border-glow-edge" aria-hidden="true" />
      <div className="border-glow-inner">{children}</div>
    </div>
  );
}

export default BorderGlow;
