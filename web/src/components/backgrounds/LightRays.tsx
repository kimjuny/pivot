import { useEffect, useRef, useState } from "react";
import { Mesh, Program, Renderer, Triangle } from "ogl";

/**
 * Volumetric "god-rays" background, ported to TypeScript + Tailwind from the
 * MIT-licensed react-bits <LightRays/> (https://reactbits.dev/backgrounds/light-rays).
 *
 * Renders a single full-screen triangle driven by a GLSL fragment shader that
 * fakes light beams emanating from an anchor point. Uses `ogl` (a tiny WebGL
 * wrapper) so the cost is one draw call per frame on the GPU.
 *
 * The container is `pointer-events-none` and fills its parent — the caller is
 * responsible for sizing/positioning (e.g. wrap in a `fixed inset-0` layer).
 */

type RaysOrigin =
  | "top-center"
  | "top-left"
  | "top-right"
  | "left"
  | "right"
  | "bottom-left"
  | "bottom-center"
  | "bottom-right";

export interface LightRaysProps {
  /** Where the light source sits (just outside the viewport on the chosen edge). */
  raysOrigin?: RaysOrigin;
  /** Hex color of the rays, e.g. "#ffffff". */
  raysColor?: string;
  /** Animation speed multiplier. */
  raysSpeed?: number;
  /** Higher = wider, softer cone. */
  lightSpread?: number;
  /** How far the rays travel, as a multiple of the viewport width. */
  rayLength?: number;
  /** Subtly pulse the beam intensity over time. */
  pulsating?: boolean;
  /** Distance over which rays fade to nothing, as a multiple of viewport width. */
  fadeDistance?: number;
  /** Color saturation (1 = full, 0 = grayscale). */
  saturation?: number;
  /** Beam direction gently follows the pointer when enabled. */
  followMouse?: boolean;
  /** 0..1 — how strongly the pointer pulls the beam direction. */
  mouseInfluence?: number;
  /** 0..1 — film-grain amount layered over the beams. */
  noiseAmount?: number;
  /** 0..1 — angular wobble of the beams. */
  distortion?: number;
  /** Extra classes merged onto the root container. */
  className?: string;
}

const DEFAULT_COLOR = "#ffffff";

/** Parse `#rrggbb` into normalized [r, g, b]. Falls back to white. */
function hexToRgb(hex: string): [number, number, number] {
  const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return match
    ? [
        parseInt(match[1], 16) / 255,
        parseInt(match[2], 16) / 255,
        parseInt(match[3], 16) / 255,
      ]
    : [1, 1, 1];
}

const OUTSIDE_FACTOR = 0.2;

/** Resolve the light-source anchor (in device pixels) and beam direction. */
function getAnchorAndDir(
  origin: RaysOrigin,
  width: number,
  height: number,
): { anchor: [number, number]; dir: [number, number] } {
  switch (origin) {
    case "top-left":
      return { anchor: [0, -OUTSIDE_FACTOR * height], dir: [0, 1] };
    case "top-right":
      return { anchor: [width, -OUTSIDE_FACTOR * height], dir: [0, 1] };
    case "left":
      return { anchor: [-OUTSIDE_FACTOR * width, 0.5 * height], dir: [1, 0] };
    case "right":
      return {
        anchor: [(1 + OUTSIDE_FACTOR) * width, 0.5 * height],
        dir: [-1, 0],
      };
    case "bottom-left":
      return { anchor: [0, (1 + OUTSIDE_FACTOR) * height], dir: [0, -1] };
    case "bottom-center":
      return {
        anchor: [0.5 * width, (1 + OUTSIDE_FACTOR) * height],
        dir: [0, -1],
      };
    case "bottom-right":
      return { anchor: [width, (1 + OUTSIDE_FACTOR) * height], dir: [0, -1] };
    default:
      return { anchor: [0.5 * width, -OUTSIDE_FACTOR * height], dir: [0, 1] };
  }
}

interface Point {
  x: number;
  y: number;
}

interface Uniforms {
  iTime: { value: number };
  iResolution: { value: number[] };
  rayPos: { value: number[] };
  rayDir: { value: number[] };
  raysColor: { value: number[] };
  raysSpeed: { value: number };
  lightSpread: { value: number };
  rayLength: { value: number };
  pulsating: { value: number };
  fadeDistance: { value: number };
  saturation: { value: number };
  mousePos: { value: number[] };
  mouseInfluence: { value: number };
  noiseAmount: { value: number };
  distortion: { value: number };
}

const VERT = `
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = position * 0.5 + 0.5;
  gl_Position = vec4(position, 0.0, 1.0);
}`;

const FRAG = `
precision highp float;

uniform float iTime;
uniform vec2  iResolution;

uniform vec2  rayPos;
uniform vec2  rayDir;
uniform vec3  raysColor;
uniform float raysSpeed;
uniform float lightSpread;
uniform float rayLength;
uniform float pulsating;
uniform float fadeDistance;
uniform float saturation;
uniform vec2  mousePos;
uniform float mouseInfluence;
uniform float noiseAmount;
uniform float distortion;

varying vec2 vUv;

float noise(vec2 st) {
  return fract(sin(dot(st.xy, vec2(12.9898,78.233))) * 43758.5453123);
}

float rayStrength(vec2 raySource, vec2 rayRefDirection, vec2 coord,
                  float seedA, float seedB, float speed) {
  vec2 sourceToCoord = coord - raySource;
  vec2 dirNorm = normalize(sourceToCoord);
  float cosAngle = dot(dirNorm, rayRefDirection);

  float distortedAngle = cosAngle + distortion * sin(iTime * 2.0 + length(sourceToCoord) * 0.01) * 0.2;

  float spreadFactor = pow(max(distortedAngle, 0.0), 1.0 / max(lightSpread, 0.001));

  float distance = length(sourceToCoord);
  float maxDistance = iResolution.x * rayLength;
  float lengthFalloff = clamp((maxDistance - distance) / maxDistance, 0.0, 1.0);

  float fadeFalloff = clamp((iResolution.x * fadeDistance - distance) / (iResolution.x * fadeDistance), 0.5, 1.0);
  float pulse = pulsating > 0.5 ? (0.8 + 0.2 * sin(iTime * speed * 3.0)) : 1.0;

  float baseStrength = clamp(
    (0.45 + 0.15 * sin(distortedAngle * seedA + iTime * speed)) +
    (0.3 + 0.2 * cos(-distortedAngle * seedB + iTime * speed)),
    0.0, 1.0
  );

  return baseStrength * lengthFalloff * fadeFalloff * spreadFactor * pulse;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
  vec2 coord = vec2(fragCoord.x, iResolution.y - fragCoord.y);

  vec2 finalRayDir = rayDir;
  if (mouseInfluence > 0.0) {
    vec2 mouseScreenPos = mousePos * iResolution.xy;
    vec2 mouseDirection = normalize(mouseScreenPos - rayPos);
    finalRayDir = normalize(mix(rayDir, mouseDirection, mouseInfluence));
  }

  vec4 rays1 = vec4(1.0) *
               rayStrength(rayPos, finalRayDir, coord, 36.2214, 21.11349, 1.5 * raysSpeed);
  vec4 rays2 = vec4(1.0) *
               rayStrength(rayPos, finalRayDir, coord, 22.3991, 18.0234, 1.1 * raysSpeed);

  fragColor = rays1 * 0.5 + rays2 * 0.4;

  if (noiseAmount > 0.0) {
    float n = noise(coord * 0.01 + iTime * 0.1);
    fragColor.rgb *= (1.0 - noiseAmount + noiseAmount * n);
  }

  float brightness = 1.0 - (coord.y / iResolution.y);
  fragColor.x *= 0.1 + brightness * 0.8;
  fragColor.y *= 0.3 + brightness * 0.6;
  fragColor.z *= 0.5 + brightness * 0.5;

  if (saturation != 1.0) {
    float gray = dot(fragColor.rgb, vec3(0.299, 0.587, 0.114));
    fragColor.rgb = mix(vec3(gray), fragColor.rgb, saturation);
  }

  fragColor.rgb *= raysColor;
}

void main() {
  vec4 color;
  mainImage(color, gl_FragCoord.xy);
  gl_FragColor = color;
}`;

export function LightRays({
  raysOrigin = "top-center",
  raysColor = DEFAULT_COLOR,
  raysSpeed = 1,
  lightSpread = 1,
  rayLength = 2,
  pulsating = false,
  fadeDistance = 1.0,
  saturation = 1.0,
  followMouse = true,
  mouseInfluence = 0.1,
  noiseAmount = 0.0,
  distortion = 0.0,
  className,
}: LightRaysProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const uniformsRef = useRef<Uniforms | null>(null);
  const rendererRef = useRef<Renderer | null>(null);
  const mouseRef = useRef<Point>({ x: 0.5, y: 0.5 });
  const smoothMouseRef = useRef<Point>({ x: 0.5, y: 0.5 });
  const animationIdRef = useRef<number | null>(null);
  const meshRef = useRef<Mesh | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const [isVisible, setIsVisible] = useState(false);

  // Pause work when the layer scrolls out of view (cheap tab-switch guard).
  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => setIsVisible(entries[0]?.isIntersecting ?? false),
      { threshold: 0.1 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // (Re)initialize the WebGL renderer whenever visibility or any visual prop
  // changes. The whole program is rebuilt — shaders are cheap to recompile and
  // this keeps the prop→uniform wiring trivial rather than diffing uniforms.
  useEffect(() => {
    if (!isVisible || !containerRef.current) return;

    if (cleanupRef.current) {
      cleanupRef.current();
      cleanupRef.current = null;
    }

    const container = containerRef.current;

    const initialize = async () => {
      // Let layout settle so clientWidth/Height are non-zero on first paint.
      await new Promise((resolve) => setTimeout(resolve, 10));
      if (!containerRef.current) return;

      const renderer = new Renderer({
        dpr: Math.min(window.devicePixelRatio, 2),
        alpha: true,
      });
      rendererRef.current = renderer;

      const gl = renderer.gl;
      gl.canvas.style.width = "100%";
      gl.canvas.style.height = "100%";

      while (container.firstChild) {
        container.removeChild(container.firstChild);
      }
      container.appendChild(gl.canvas);

      const uniforms: Uniforms = {
        iTime: { value: 0 },
        iResolution: { value: [1, 1] },
        rayPos: { value: [0, 0] },
        rayDir: { value: [0, 1] },
        raysColor: { value: hexToRgb(raysColor) },
        raysSpeed: { value: raysSpeed },
        lightSpread: { value: lightSpread },
        rayLength: { value: rayLength },
        pulsating: { value: pulsating ? 1.0 : 0.0 },
        fadeDistance: { value: fadeDistance },
        saturation: { value: saturation },
        mousePos: { value: [0.5, 0.5] },
        mouseInfluence: { value: mouseInfluence },
        noiseAmount: { value: noiseAmount },
        distortion: { value: distortion },
      };
      uniformsRef.current = uniforms;

      const geometry = new Triangle(gl);
      const program = new Program(gl, {
        vertex: VERT,
        fragment: FRAG,
        uniforms,
      });
      const mesh = new Mesh(gl, { geometry, program });
      meshRef.current = mesh;

      const updatePlacement = () => {
        if (!containerRef.current || !rendererRef.current) return;
        const r = rendererRef.current;
        r.dpr = Math.min(window.devicePixelRatio, 2);

        const { clientWidth: wCss, clientHeight: hCss } = containerRef.current;
        r.setSize(wCss, hCss);

        const dpr = r.dpr;
        const w = wCss * dpr;
        const h = hCss * dpr;

        const u = uniformsRef.current;
        if (!u) return;
        u.iResolution.value = [w, h];
        const { anchor, dir } = getAnchorAndDir(raysOrigin, w, h);
        u.rayPos.value = anchor;
        u.rayDir.value = dir;
      };

      const loop = (t: number) => {
        if (!rendererRef.current || !uniformsRef.current || !meshRef.current) {
          return;
        }
        const u = uniformsRef.current;

        u.iTime.value = t * 0.001;

        if (followMouse && mouseInfluence > 0.0) {
          const smoothing = 0.92;
          smoothMouseRef.current.x =
            smoothMouseRef.current.x * smoothing +
            mouseRef.current.x * (1 - smoothing);
          smoothMouseRef.current.y =
            smoothMouseRef.current.y * smoothing +
            mouseRef.current.y * (1 - smoothing);
          u.mousePos.value = [smoothMouseRef.current.x, smoothMouseRef.current.y];
        }

        try {
          rendererRef.current.render({ scene: meshRef.current });
          animationIdRef.current = requestAnimationFrame(loop);
        } catch (error) {
          console.warn("LightRays WebGL rendering error:", error);
        }
      };

      window.addEventListener("resize", updatePlacement);
      updatePlacement();
      animationIdRef.current = requestAnimationFrame(loop);

      cleanupRef.current = () => {
        if (animationIdRef.current) {
          cancelAnimationFrame(animationIdRef.current);
          animationIdRef.current = null;
        }
        window.removeEventListener("resize", updatePlacement);

        const currentRenderer = rendererRef.current;
        if (currentRenderer) {
          try {
            const canvas = currentRenderer.gl.canvas as HTMLCanvasElement;
            const loseCtx = currentRenderer.gl.getExtension("WEBGL_lose_context");
            loseCtx?.loseContext();
            canvas.parentNode?.removeChild(canvas);
          } catch (error) {
            console.warn("LightRays cleanup error:", error);
          }
        }

        rendererRef.current = null;
        uniformsRef.current = null;
        meshRef.current = null;
      };
    };

    void initialize();

    return () => {
      if (cleanupRef.current) {
        cleanupRef.current();
        cleanupRef.current = null;
      }
    };
  }, [
    isVisible,
    raysOrigin,
    raysColor,
    raysSpeed,
    lightSpread,
    rayLength,
    pulsating,
    fadeDistance,
    saturation,
    followMouse,
    mouseInfluence,
    noiseAmount,
    distortion,
  ]);

  // Track the pointer independently of the renderer lifecycle. The render loop
  // reads mouseRef each frame and eases the beam toward it, so this only needs
  // to stay subscribed while followMouse is on.
  useEffect(() => {
    if (!followMouse) return;

    const handleMouseMove = (event: MouseEvent) => {
      const node = containerRef.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      mouseRef.current = {
        x: (event.clientX - rect.left) / rect.width,
        y: (event.clientY - rect.top) / rect.height,
      };
    };

    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, [followMouse]);

  return (
    <div
      ref={containerRef}
      className={`pointer-events-none relative h-full w-full overflow-hidden ${
        className ?? ""
      }`.trim()}
      aria-hidden="true"
    />
  );
}

export default LightRays;
