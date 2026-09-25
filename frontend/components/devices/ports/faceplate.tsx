"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

import { layoutFaceplate, type PlacedPort } from "./layout";
import { peerLabel, type Port } from "./types";

const LED: Record<Port["state"], string> = {
  up: "#22c55e",
  lag: "#22c55e",
  disabled: "#ef4444",
  unused: "#3b414d",
};

function Cage({ p, lagColor, selected, dimmed }: { p: PlacedPort; lagColor?: string; selected: boolean; dimmed: boolean }) {
  const { x, y, w, h } = p;
  const s = p.port.state;
  const tint = s === "unused" ? null : s === "disabled" ? "#7f1d1d" : (lagColor ?? "#047857");
  const ledY = p.ledAbove ? y - 6 : y + h + 6;
  const rj45 = p.port.form === "rj45";
  return (
    <g opacity={dimmed ? 0.3 : 1} style={{ transition: "opacity .15s" }}>
      {rj45 ? (
        <path
          d={`M${x} ${y} h${w} v${h - 4} h-${w * 0.25} v4 h-${w * 0.5} v-4 h-${w * 0.25} z`}
          fill="#0a0c10"
          stroke={selected ? "#fbbf24" : "#8b93a3"}
          strokeWidth={selected ? 2 : 1}
        />
      ) : (
        <>
          <rect x={x} y={y} width={w} height={h} rx={1.6} fill="#c7ccd6" stroke={selected ? "#fbbf24" : "#6b7280"} strokeWidth={selected ? 2 : 0.8} />
          <rect x={x + 2} y={y + 2} width={w - 4} height={h - 4} rx={1} fill="#0a0c10" />
        </>
      )}
      {tint ? <rect x={x + 3} y={y + 3} width={w - 6} height={h - 6} rx={0.8} fill={tint} opacity={0.85} /> : null}
      {s === "disabled" ? (
        <path d={`M${x + 5} ${y + 5} L${x + w - 5} ${y + h - 5} M${x + w - 5} ${y + 5} L${x + 5} ${y + h - 5}`} stroke="#fca5a5" strokeWidth={1.4} />
      ) : null}
      {p.port.peers.length && s !== "disabled" ? <circle cx={x + w - 5} cy={y + 5} r={1.8} fill="#fde68a" /> : null}
      <circle cx={x + w / 2} cy={ledY} r={2.2} fill={LED[s]} style={s === "up" || s === "lag" ? { filter: "drop-shadow(0 0 2px #22c55e)" } : undefined} />
      <text x={x + w / 2} y={p.ledAbove ? y - 11 : y + h + 15} textAnchor="middle" fontSize={7} fill="#9aa3b2" fontFamily="Menlo, Consolas, monospace">
        {p.label}
      </text>
    </g>
  );
}

export interface FaceplateProps {
  ports: Port[];
  vendor: string | null;
  model: string | null;
  uHeight?: number;
  lagColors: Map<string, string>;
  selected: string | null;
  onSelect: (name: string) => void;
  /** only these ports at full opacity (e.g. members of a hovered LAG) */
  highlight?: Set<string> | null;
}

/**
 * Generated front panel: brushed-metal chassis with rack ears and a vent pattern, every port cage at
 * its position, a link LED (green in use, red disabled, off unused) and the port tinted by state /
 * LAG. Works for any model - the layout comes from the device type's port list.
 */
export function Faceplate({ ports, vendor, model, uHeight = 1, lagColors, selected, onSelect, highlight }: FaceplateProps) {
  const layout = React.useMemo(() => layoutFaceplate(ports, uHeight), [ports, uHeight]);
  const [hover, setHover] = React.useState<{ p: PlacedPort; x: number; y: number; w: number } | null>(null);
  const wrap = React.useRef<HTMLDivElement>(null);
  const { width: W, height: H } = layout;
  const pid = React.useId().replace(/:/g, "");

  const onMove = (e: React.MouseEvent, p: PlacedPort) => {
    const r = wrap.current?.getBoundingClientRect();
    if (r) setHover({ p, x: e.clientX - r.left, y: e.clientY - r.top, w: r.width });
  };

  return (
    <div ref={wrap} className="relative w-full overflow-x-auto scrollbar-thin" data-testid="faceplate">
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full min-w-[640px]" role="img" aria-label={`Front panel of ${vendor ?? ""} ${model ?? ""}`}>
        <defs>
          <linearGradient id={`metal-${pid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#4b5261" />
            <stop offset="0.08" stopColor="#353a45" />
            <stop offset="0.92" stopColor="#262a33" />
            <stop offset="1" stopColor="#1b1e25" />
          </linearGradient>
          <linearGradient id={`ear-${pid}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#5b6272" />
            <stop offset="1" stopColor="#3a404c" />
          </linearGradient>
          <pattern id={`vent-${pid}`} width="7" height="6" patternUnits="userSpaceOnUse">
            <circle cx="1.8" cy="1.8" r="1.25" fill="#16181d" opacity="0.75" />
            <circle cx="5.3" cy="4.8" r="1.25" fill="#16181d" opacity="0.75" />
          </pattern>
        </defs>
        {/* chassis */}
        <rect x={0} y={0} width={W} height={H} rx={4} fill={`url(#metal-${pid})`} />
        <rect x={26} y={4} width={W - 52} height={H - 8} fill={`url(#vent-${pid})`} opacity={0.55} />
        {/* ears */}
        {[0, W - 26].map((x) => (
          <g key={x}>
            <rect x={x} y={0} width={26} height={H} rx={3} fill={`url(#ear-${pid})`} />
            {[0.22, 0.78].map((f) => (
              <ellipse key={f} cx={x + 13} cy={H * f} rx={5.5} ry={3.4} fill="#111318" stroke="#737b8c" strokeWidth={0.8} />
            ))}
          </g>
        ))}
        {/* vendor / model plate */}
        <rect x={32} y={10} width={82} height={34} rx={3} fill="#1b1e25" opacity={0.85} />
        <text x={40} y={25} fontSize={11} fontWeight={700} fill="#e5e7eb" fontFamily="Inter, Helvetica, Arial, sans-serif" letterSpacing={0.6}>
          {(vendor ?? "").toUpperCase().slice(0, 12)}
        </text>
        <text x={40} y={38} fontSize={9} fill="#aeb5c2" fontFamily="Menlo, Consolas, monospace">
          {(model ?? "").slice(0, 16)}
        </text>
        {/* port blocks */}
        {layout.groups.map((g, i) => (
          <g key={i}>
            <rect x={g.x - 6} y={g.y - 22} width={g.w + 12} height={g.h + 44} rx={3} fill="#1a1d24" opacity={0.7} />
            {g.title ? (
              <text x={g.x + g.w / 2} y={g.y - 24} textAnchor="middle" fontSize={7} fill="#9aa3b2" fontFamily="Inter, Helvetica, Arial, sans-serif">
                {g.title}
              </text>
            ) : null}
          </g>
        ))}
        {layout.ports.map((p) => (
          <g
            key={p.port.name}
            role="button"
            tabIndex={0}
            aria-label={`${p.port.name}${p.port.description ? `: ${p.port.description}` : ""} (${p.port.state})`}
            aria-pressed={selected === p.port.name}
            data-port={p.port.name}
            className="cursor-pointer outline-none"
            onClick={() => onSelect(p.port.name)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(p.port.name);
              }
            }}
            onMouseMove={(e) => onMove(e, p)}
            onMouseLeave={() => setHover(null)}
          >
            <rect x={p.x - 3} y={p.y - 14} width={p.w + 6} height={p.h + 28} fill="transparent" />
            <Cage
              p={p}
              lagColor={p.port.lag ? lagColors.get(p.port.lag) : undefined}
              selected={selected === p.port.name}
              dimmed={!!highlight && !highlight.has(p.port.name)}
            />
          </g>
        ))}
      </svg>
      {hover ? (
        <div
          className="pointer-events-none absolute z-10 max-w-[320px] rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-lg"
          style={{ left: Math.max(0, Math.min(hover.x + 14, hover.w - 330)), top: hover.y + 14 }}
        >
          <p className="font-mono font-semibold">
            {hover.p.port.name}
            {hover.p.port.speed ? <span className="ml-1.5 font-sans font-normal text-muted-foreground">{hover.p.port.speed}</span> : null}
          </p>
          {hover.p.port.description ? <p className="mt-0.5">{hover.p.port.description}</p> : null}
          <p className={cn("mt-0.5", hover.p.port.state === "unused" && "text-muted-foreground")}>
            {hover.p.port.state === "unused" ? "Not configured" : hover.p.port.state === "disabled" ? "Administratively disabled" : hover.p.port.lag ? `Member of ${hover.p.port.lag}` : "In use"}
            {hover.p.port.channels.length ? ` · ${hover.p.port.channels.length} channel(s)` : ""}
          </p>
          {hover.p.port.peers.slice(0, 4).map((pe, i) => (
            <p key={i} className="truncate text-muted-foreground">
              → {peerLabel(pe)}
            </p>
          ))}
          {hover.p.port.peers.length > 4 ? <p className="text-muted-foreground">+{hover.p.port.peers.length - 4} more</p> : null}
        </div>
      ) : null}
    </div>
  );
}
