import React, { useEffect, useId, useRef, useState } from "react";

/**
 * RedditMagnifyLoader
 * A self-contained loading animation that reveals the Reddit logo
 * only under a moving magnifying glass.
 *
 * - No external assets required (logo drawn with SVG)
 * - Mask-based reveal so only the area under the lens is visible
 * - Smooth, CPU-light animation via requestAnimationFrame
 *
 * Props
 *  - size: overall square size in px (default 340)
 *  - durationMs: time to complete one loop of the path (default 4500)
 *  - className: optional wrapper class
 *  - ariaLabel: accessible label for screen readers (default "Searching…")
 *  - paused: optionally pause the animation (default false)
 */
export default function RedditMagnifyLoader({
  size = 340,
  durationMs = 4500,
  className = "",
  ariaLabel = "Searching…",
  paused = false,
}: {
  size?: number;
  durationMs?: number;
  className?: string;
  ariaLabel?: string;
  paused?: boolean;
}) {
  const uid = useId().replace(/:/g, "");
  const [pos, setPos] = useState({ x: size * 0.5, y: size * 0.5 });
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);

  // Lens sizing & motion envelope (visuals unchanged)
  const lensR = Math.max(28, size * 0.18);
  const cx = size / 2;
  const cy = size / 2;
  const ampX = size * 0.34; // horizontal sweep
  const ampY = size * 0.34; // vertical sweep

  // --- NEW: compute a safe gutter so the handle/shadow never clip ---
  const handleLen = lensR * 1.4;
  const handleExtent = Math.cos(Math.PI / 4) * (lensR + 4 + handleLen); // reach along 45°
  const handleStrokeHalf = Math.max(4, size * 0.02) * 0.5;               // main stroke
  const dropShadowPad = 12;                                              // soft shadow slack
  const gutter = Math.ceil(handleExtent + handleStrokeHalf + dropShadowPad);

  // viewBox padding and inverse transform to keep visuals identical
  const vb = `-${gutter} -${gutter} ${size + gutter * 2} ${size + gutter * 2}`;
  const scale = (size + gutter * 2) / size;
  const masterTransform = `translate(${-gutter},${-gutter}) scale(${scale})`;
  // ------------------------------------------------------------------

  // Start/stop animation
  useEffect(() => {
    // Respect reduced motion
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    if (prefersReduced || paused) {
      setPos({ x: cx, y: cy });
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      startRef.current = null;
      return;
    }

    function tick(ts: number) {
      if (startRef.current === null) startRef.current = ts;
      const elapsed = ts - startRef.current;
      // const t = (elapsed % durationMs) / durationMs; // 0..1

      // Lissajous-ish path that stays within bounds (same motion)
      // const ang = 2 * Math.PI * t;
      const ang = (elapsed / durationMs) * 2 * Math.PI;
      const x = cx + ampX * 0.85 * Math.cos(ang) * 0.9;
      const y = cy + ampY * 0.85 * Math.sin(ang * 1.7) * 0.9;

      setPos({ x, y });
      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);

    // Pause when tab is hidden to save cycles; resume when visible
    const onVis = () => {
      if (document.hidden) {
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
        startRef.current = null;
      } else if (!rafRef.current) {
        rafRef.current = requestAnimationFrame(tick);
      }
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      document.removeEventListener("visibilitychange", onVis);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      startRef.current = null;
    };
  }, [durationMs, size, paused, cx, cy, ampX, ampY]);

  const maskId = `revealMask_${uid}`;
  const lensFilterId = `lensShadow_${uid}`;

  return (
    <div
      className={"inline-flex items-center justify-center " + className}
      style={{ width: size, height: size }}
      aria-label={ariaLabel}
      aria-busy="true"
      role="img"
    >
      {/* viewBox expanded with a gutter; inner content scaled/translated back */}
      <svg width={size} height={size} viewBox={vb} focusable="false"
      style={{ overflow: "visible" }} 
      >
        <defs>
          {/* Soft shadow for the lens */}
          <filter id={lensFilterId} x="-50%" y="-50%" width="200%" height="200%" overflow="visible">
            <feDropShadow dx="0" dy="4" stdDeviation="4" floodOpacity="0.1" />
          </filter>

          {/* Mask that reveals only the lens area (cover the full expanded viewBox) */}
          <mask
            id={maskId}
            maskUnits="userSpaceOnUse"
            maskContentUnits="userSpaceOnUse"
            x={-gutter}
            y={-gutter}
            width={size + 3 * gutter}
            height={size + 2 * gutter}
          >
            {/* Everything hidden by default */}
            <rect x={-gutter} y={-gutter} width={size + 2 * gutter} height={size + 2 * gutter} fill="black" />
            {/* The lens circle reveals the logo underneath (coords match content space) */}
            <circle cx={pos.x} cy={pos.y} r={lensR} fill="white" />
          </mask>
        </defs>

        {/* All visible content uses the original 0..size space, mapped into the padded viewBox */}
        <g transform={masterTransform}>
          {/* Background */}
          <rect x={0} y={0} width={size} height={size} fill="white" />

          {/* Logo (masked) */}
          <g mask={`url(#${maskId})`}>{renderRedditMark({ size })}</g>

          {/* Magnifying glass UI */}
          <g filter={`url(#${lensFilterId})`}>
            {/* Lens rim */}
            <circle
              cx={pos.x}
              cy={pos.y}
              r={lensR}
              fill="rgba(255,255,255,0.9)"
              stroke="#0f172a"
              strokeWidth={Math.max(2, size * 0.018)}
            />
            {/* Lens glare */}
            <ellipse
              cx={pos.x - lensR * 0.25}
              cy={pos.y - lensR * 0.25}
              rx={lensR * 0.4}
              ry={lensR * 0.22}
              fill="white"
              opacity={0.35}
            />
            {/* Handle */}
            {(() => {
              const handleLen = lensR * 1.4;
              const angle = Math.PI / 4; // 45deg
              const hx1 = pos.x + Math.cos(angle) * (lensR + 4);
              const hy1 = pos.y + Math.sin(angle) * (lensR + 4);
              const hx2 = hx1 + Math.cos(angle) * handleLen;
              const hy2 = hy1 + Math.sin(angle) * handleLen;
              return (
                <g>
                  <line
                    x1={hx1}
                    y1={hy1}
                    x2={hx2}
                    y2={hy2}
                    stroke="#0f172a"
                    strokeWidth={Math.max(4, size * 0.02)}
                    strokeLinecap="round"
                  />
                  <line
                    x1={hx1}
                    y1={hy1}
                    x2={hx2}
                    y2={hy2}
                    stroke="white"
                    strokeOpacity={0.3}
                    strokeWidth={Math.max(2, size * 0.012)}
                    strokeLinecap="round"
                  />
                </g>
              );
            })()}
          </g>
        </g>
      </svg>
    </div>
  );
}

/**
 * Minimal-but-recognizable Reddit app icon recreation (no external asset):
 *  - Orange circle (#FF4500)
 *  - White head, orange eyes, orange smile/antenna tips
 * This is a stylistic approximation for a loader, not a brand-perfect mark.
 */
function renderRedditMark({ size }: { size: number }) {
  const cx = size / 2;
  const cy = size / 2;
  const R = size * 0.36; // outer orange disc

  // Head
  const headR = R * 0.48;
  const headCx = cx;
  const headCy = cy + R * 0.02;

  // Eyes
  const eyeR = headR * 0.14;
  const eyeDx = headR * 0.33;

  // Antenna
  const antLen = headR * 0.95;
  const antAngle = -Math.PI / 6; // -30deg from horizontal
  const antStartX = headCx + headR * 0.45;
  const antStartY = headCy - headR * 0.55;
  const antEndX = antStartX + antLen * Math.cos(antAngle);
  const antEndY = antStartY + antLen * Math.sin(antAngle);

  // Smile (simple arc)
  const smileR = headR * 0.7;
  const smileY = headCy + headR * 0.2;
  const smileX1 = headCx - headR * 0.45;
  const smileX2 = headCx + headR * 0.45;

  return (
    <g>
      {/* Orange background disc */}
      <circle cx={cx} cy={cy} r={R} fill="#FF4500" />

      {/* Antenna line & tip */}
      <line
        x1={antStartX}
        y1={antStartY}
        x2={antEndX}
        y2={antEndY}
        stroke="white"
        strokeWidth={Math.max(2, size * 0.01)}
      />
      <circle
        cx={antEndX}
        cy={antEndY}
        r={Math.max(2.5, size * 0.015)}
        fill="#FF4500"
        stroke="white"
        strokeWidth={Math.max(1.5, size * 0.007)}
      />

      {/* Head */}
      <circle cx={headCx} cy={headCy} r={headR} fill="white" />

      {/* Eyes */}
      <circle cx={headCx - eyeDx} cy={headCy - headR * 0.1} r={eyeR} fill="#FF4500" />
      <circle cx={headCx + eyeDx} cy={headCy - headR * 0.1} r={eyeR} fill="#FF4500" />

      {/* Smile as an orange stroked arc */}
      <path
        d={`M ${smileX1} ${smileY} A ${smileR} ${smileR} 0 0 0 ${smileX2} ${smileY}`}
        fill="none"
        stroke="#FF4500"
        strokeWidth={Math.max(3, size * 0.014)}
        strokeLinecap="round"
      />
    </g>
  );
}
