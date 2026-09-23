"use client";

import type { Player } from "asciinema-player";
import * as React from "react";

import "asciinema-player/dist/bundle/asciinema-player.css";

export interface CastPlayerHandle {
  seek: (seconds: number) => void;
}

/**
 * asciinema-player wrapper. `src` must be a URL the player can fetch without extra headers
 * (we pass a blob: URL created from an authenticated fetch).
 */
export const CastPlayer = React.forwardRef<
  CastPlayerHandle,
  { src: string; markers?: [number, string][]; onTime?: (t: number) => void }
>(function CastPlayer({ src, markers, onTime }, ref) {
  const container = React.useRef<HTMLDivElement>(null);
  const player = React.useRef<Player | null>(null);
  const onTimeRef = React.useRef(onTime);
  onTimeRef.current = onTime;

  React.useImperativeHandle(ref, () => ({
    seek: (seconds: number) => {
      const p = player.current;
      if (!p) return;
      void p.seek(Math.max(0, seconds - 0.05)).then(() => p.play());
    },
  }));

  React.useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    void import("asciinema-player").then((mod) => {
      if (disposed || !container.current) return;
      player.current = mod.create(src, container.current, {
        fit: "width",
        idleTimeLimit: 2,
        theme: "asciinema",
        terminalFontSize: "small",
        markers,
        controls: true,
      });
      timer = window.setInterval(() => {
        const t = player.current?.getCurrentTime();
        if (typeof t === "number") onTimeRef.current?.(t);
      }, 250);
    });
    return () => {
      disposed = true;
      if (timer) window.clearInterval(timer);
      player.current?.dispose();
      player.current = null;
    };
  }, [src, markers]);

  return <div ref={container} className="overflow-hidden rounded-lg border bg-black" />;
});
