"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Text that writes itself, then inks in. No dependencies.
 * Sourced from 21st.dev component catalog.
 */

const OPENTYPE_CDN = "/js/opentype.min.js";

const DEFAULT_FONT_URL = "/fonts/handwriting.ttf";

export interface HandwritingTextProps {
  /** A single phrase to write. Ignored when `words` is given. */
  text?: string;
  /** Cycle through these, rewriting on each change. */
  words?: string[];
  /** Milliseconds each word is held before the next one starts. */
  interval?: number;
  /** URL of a .ttf or .otf. Self-hosted locally to avoid CORS. */
  fontUrl?: string;
  /** Seconds for the pen to cross the whole word. */
  duration?: number;
  /** Seconds before the pen starts. */
  delay?: number;
  /** Stroke weight, in units of a 100px em. */
  strokeWidth?: number;
  /** Ink the letters in once drawn. Set false to leave them as outlines. */
  fill?: boolean;
  /** CSS height of the rendered word; width follows the glyphs. */
  height?: string;
  className?: string;
}

type Geometry = {
  full: string;
  contours: string[];
  x: number;
  y: number;
  w: number;
  h: number;
};

/* eslint-disable @typescript-eslint/no-explicit-any */

// The library, loaded once per page.
let libPromise: Promise<any> | null = null;

function loadOpentype(): Promise<any> {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  const existing = (window as any).opentype;
  if (existing) return Promise.resolve(existing);
  if (!libPromise) {
    libPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = OPENTYPE_CDN;
      script.async = true;
      script.onload = () => {
        const lib = (window as any).opentype;
        if (lib) resolve(lib);
        else reject(new Error("opentype.js loaded but exposed nothing"));
      };
      script.onerror = () => {
        // Fallback to CDN if local bundle fails
        const fallbackScript = document.createElement("script");
        fallbackScript.src = "https://cdn.jsdelivr.net/npm/opentype.js@1.3.4/dist/opentype.min.js";
        fallbackScript.async = true;
        fallbackScript.onload = () => {
          const lib = (window as any).opentype;
          if (lib) resolve(lib);
          else reject(new Error("opentype.js CDN loaded but exposed nothing"));
        };
        fallbackScript.onerror = () => reject(new Error("opentype.js failed to load"));
        document.head.appendChild(fallbackScript);
      };
      document.head.appendChild(script);
    });
  }
  return libPromise;
}

// One fetch and one parse per font URL, shared by every instance on the page.
const fontCache = new Map<string, Promise<any>>();

function loadFont(url: string): Promise<any> {
  let pending = fontCache.get(url);
  if (!pending) {
    pending = Promise.all([
      loadOpentype(),
      fetch(url)
        .then((res) => {
          if (!res.ok) throw new Error(`Font request failed: ${res.status}`);
          return res.arrayBuffer();
        })
        .catch((err) => {
          // If remote font failed or had CORS issues, gracefully fallback to local font
          if (url !== "/fonts/handwriting.ttf") {
            return fetch("/fonts/handwriting.ttf").then((r) => {
              if (!r.ok) throw err;
              return r.arrayBuffer();
            });
          }
          throw err;
        }),
    ]).then(([lib, buffer]) => lib.parse(buffer));
    fontCache.set(url, pending);
  }
  return pending;
}

const EM = 100; // arbitrary: the viewBox normalises whatever we pick

export function HandwritingText({
  text,
  words,
  interval = 3200,
  fontUrl = DEFAULT_FONT_URL,
  duration = 1.5,
  delay = 0.05,
  strokeWidth = 1.6,
  fill = true,
  height = "1.15em",
  className,
}: HandwritingTextProps) {
  const cycle = Boolean(words && words.length > 0);
  const [index, setIndex] = useState(0);
  const current = cycle ? words![index % words!.length] : text ?? "";

  const [font, setFont] = useState<any>(null);
  const [geom, setGeom] = useState<Geometry | null>(null);
  const [drawn, setDrawn] = useState(false);
  const [lengths, setLengths] = useState<number[]>([]);
  const pathRefs = useRef<(SVGPathElement | null)[]>([]);

  useEffect(() => {
    if (!cycle) return undefined;
    const id = setInterval(() => setIndex((i) => i + 1), interval);
    return () => clearInterval(id);
  }, [cycle, interval]);

  useEffect(() => {
    let cancelled = false;
    loadFont(fontUrl)
      .then((f) => { if (!cancelled) setFont(f); })
      .catch(() => { /* falls back to plain text below */ });
    return () => { cancelled = true; };
  }, [fontUrl]);

  useEffect(() => {
    if (!font || !current) return;
    const path = font.getPath(current, 0, EM, EM);
    const box = path.getBoundingBox();
    const pad = EM * 0.12; // room for the stroke and any descenders
    const full = path.toPathData(2);
    setGeom({
      full,
      // Split on the moveto that opens each contour, keeping the M with its segment.
      contours: full.split(/(?=M)/).filter((d: string) => d.trim().length > 1),
      x: box.x1 - pad,
      y: box.y1 - pad,
      w: box.x2 - box.x1 + pad * 2,
      h: box.y2 - box.y1 + pad * 2,
    });
    setDrawn(false);
    setLengths([]);
  }, [font, current]);

  useEffect(() => {
    if (!geom) return undefined;
    setLengths(
      pathRefs.current
        .slice(0, geom.contours.length)
        .map((el) => (el ? el.getTotalLength() : 0)),
    );
    // Two frames: the first commits the full-length offsets with no transition, the
    // second enables it and moves to zero. Both in one commit leaves nothing to animate.
    const id = requestAnimationFrame(() =>
      requestAnimationFrame(() => setDrawn(true)),
    );
    return () => cancelAnimationFrame(id);
  }, [geom]);

  // Before the font resolves — and if it never does — the text is still readable.
  if (!geom) {
    return <span className={className}>{current}</span>;
  }

  const count = Math.max(1, geom.contours.length);

  return (
    <svg
      key={current}
      viewBox={`${geom.x} ${geom.y} ${geom.w} ${geom.h}`}
      role="img"
      aria-label={current}
      className={["inline-block", className].filter(Boolean).join(" ")}
      style={{
        height,
        width: `calc(${height} * ${(geom.w / geom.h).toFixed(4)})`,
        overflow: "visible",
      }}
    >
      {fill && (
        <path
          d={geom.full}
          fill="currentColor"
          stroke="none"
          style={{
            opacity: drawn ? 1 : 0,
            transition: drawn
              ? `opacity 0.45s ease-out ${(delay + duration * 0.72).toFixed(3)}s`
              : "none",
          }}
        />
      )}
      {geom.contours.map((d, i) => {
        const length = lengths[i] || 0;
        // Contours overlap slightly so the stroke reads as one continuous movement
        // rather than as letters switching on in turn.
        const each = (duration / count) * 2.4;
        const start = delay + (i / count) * duration;
        return (
          <path
            key={i}
            ref={(el) => { pathRefs.current[i] = el; }}
            d={d}
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{
              strokeDasharray: length || 1,
              strokeDashoffset: drawn ? 0 : length || 1,
              transition: drawn
                ? `stroke-dashoffset ${each.toFixed(3)}s ease-out ${start.toFixed(3)}s`
                : "none",
            }}
          />
        );
      })}
    </svg>
  );
}

export default HandwritingText;
