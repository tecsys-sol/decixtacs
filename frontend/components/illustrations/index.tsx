/**
 * Aurora line-art illustrations. Colours come from the --ill-* CSS variables so every drawing
 * follows the theme; motion classes (flow / floaty / blink / fan) are disabled under
 * prefers-reduced-motion in globals.css. All illustrations are decorative (aria-hidden).
 */
import type { LucideIcon } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

// literal class strings so Tailwind picks them up
const s = {
  brand: "stroke-[var(--ill-brand)]",
  brand2: "stroke-[var(--ill-brand-2)]",
  soft: "stroke-[var(--ill-soft)]",
  lilac: "stroke-[var(--ill-lilac)]",
  green: "stroke-[var(--ill-green)]",
  orange: "stroke-[var(--ill-orange)]",
};
const f = {
  brand: "fill-[var(--ill-brand)]",
  brand2: "fill-[var(--ill-brand-2)]",
  soft: "fill-[var(--ill-soft)]",
  softer: "fill-[var(--ill-softer)]",
  ground: "fill-[var(--ill-ground)]",
  surface: "fill-[var(--ill-surface)]",
  green: "fill-[var(--ill-green)]",
  orange: "fill-[var(--ill-orange)]",
  lilac: "fill-[var(--ill-lilac)]",
  none: "fill-none",
};

type SvgProps = { className?: string };

function Svg({ viewBox, className, children }: { viewBox: string; className?: string; children: React.ReactNode }) {
  return (
    <svg viewBox={viewBox} fill="none" aria-hidden focusable="false" className={className}>
      {children}
    </svg>
  );
}

/** Dashboard hero: devices linked by flowing connections (from the approved mockup). */
export function HeroNetwork({ className }: SvgProps) {
  return (
    <Svg viewBox="0 0 420 170" className={className}>
      <ellipse cx="210" cy="150" rx="190" ry="14" className={f.ground} />
      <path d="M60 110 150 60 250 92 350 44" strokeWidth="3" className={s.soft} />
      <path d="M60 110 150 60 250 92 350 44" strokeWidth="3" className={cn(s.brand, "flow")} />
      <path d="M150 60 190 130M250 92 300 130" strokeWidth="3" className={s.soft} />
      <path d="M150 60 190 130M250 92 300 130" strokeWidth="3" className={cn(s.green, "flow")} />
      <g className="floaty">
        <rect x="30" y="92" width="60" height="36" rx="9" strokeWidth="2" className={cn(f.surface, s.brand)} />
        <path d="M42 104h36M42 116h20" strokeWidth="2" strokeLinecap="round" className={s.brand} />
      </g>
      <g className="floaty" style={{ animationDelay: ".6s" }}>
        <rect x="118" y="40" width="64" height="40" rx="10" className={f.brand} />
        <circle cx="134" cy="60" r="4" className="fill-white" />
        <circle cx="150" cy="60" r="4" className="fill-[#c9c3fb]" />
        <circle cx="166" cy="60" r="4" className="fill-white" />
      </g>
      <g className="floaty" style={{ animationDelay: "1.1s" }}>
        <rect x="220" y="74" width="60" height="36" rx="9" strokeWidth="2" className={cn(f.surface, s.green)} />
        <path d="m236 92 7 7 13-13" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className={s.green} />
      </g>
      <g className="floaty" style={{ animationDelay: "1.7s" }}>
        <rect x="318" y="24" width="64" height="40" rx="10" strokeWidth="2" className={cn(f.surface, s.orange)} />
        <path d="M334 44h32" strokeWidth="2" strokeLinecap="round" className={s.orange} />
        <circle cx="372" cy="34" r="4" className={cn(f.orange, "blink")} />
      </g>
      <rect x="170" y="120" width="40" height="24" rx="6" strokeWidth="2" className={cn(f.surface, s.lilac)} />
      <rect x="282" y="120" width="40" height="24" rx="6" strokeWidth="2" className={cn(f.surface, s.lilac)} />
    </Svg>
  );
}

/** Sidebar status card: a small chain of nodes with a flowing link. */
export function MiniNetwork({ className, degraded }: SvgProps & { degraded?: boolean }) {
  return (
    <Svg viewBox="0 0 200 70" className={cn("floaty", className)}>
      <path d="M20 50 60 22 100 44 140 16 180 38" strokeWidth="2" className={s.lilac} />
      <path d="M20 50 60 22 100 44 140 16 180 38" strokeWidth="2" className={cn(degraded ? s.orange : s.brand, "flow")} />
      {[
        [20, 50],
        [60, 22],
        [140, 16],
        [180, 38],
      ].map(([x, y]) => (
        <circle key={`${x}`} cx={x} cy={y} r="6" strokeWidth="2" className={cn(f.surface, s.brand)} />
      ))}
      <circle cx="100" cy="44" r="6" className={cn(degraded ? f.orange : f.brand, degraded && "blink")} />
    </Svg>
  );
}

/** Device page: chassis with port LEDs and a spinning fan. */
export function DeviceChassis({ className, ports }: SvgProps & { ports?: ("up" | "down" | "idle")[] }) {
  const p = ports ?? ["up", "up", "up", "idle", "up", "down", "up", "idle"];
  const color = (v: string) => (v === "up" ? f.green : v === "down" ? f.orange : f.lilac);
  return (
    <Svg viewBox="0 0 132 84" className={className}>
      <rect x="6" y="18" width="120" height="48" rx="10" strokeWidth="2" className={cn(f.softer, s.brand)} />
      {p.slice(0, 8).map((v, i) => (
        <rect key={i} x={18 + (i % 4) * 12} y={i < 4 ? 30 : 44} width="8" height="8" rx="2" className={color(v)} />
      ))}
      <g className="fan">
        <circle cx="102" cy="42" r="13" strokeWidth="2" className={s.brand} />
        <path d="M102 29v26M89 42h26" strokeWidth="2" className={s.brand2} />
      </g>
    </Svg>
  );
}

// --- page header art ---------------------------------------------------------------------------

export type HeaderArt =
  | "network"
  | "devices"
  | "backups"
  | "compliance"
  | "changes"
  | "tacacs"
  | "accounting"
  | "sessions"
  | "audit"
  | "ixp"
  | "alerts"
  | "reports"
  | "integrations"
  | "users"
  | "settings";

function Ground() {
  return <ellipse cx="110" cy="92" rx="100" ry="8" className={f.ground} />;
}

const ART: Record<HeaderArt, () => React.ReactElement> = {
  network: () => (
    <>
      <Ground />
      <path d="M30 60 80 28 140 52 190 22M80 28 110 78M140 52 170 78" strokeWidth="2.5" className={s.soft} />
      <path d="M30 60 80 28 140 52 190 22M80 28 110 78M140 52 170 78" strokeWidth="2.5" className={cn(s.brand, "flow")} />
      {[
        [30, 60],
        [140, 52],
        [110, 78],
        [170, 78],
      ].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="7" strokeWidth="2" className={cn(f.surface, s.brand, "floaty")} style={{ animationDelay: `${i * 0.4}s` }} />
      ))}
      <circle cx="80" cy="28" r="9" className={f.brand} />
      <circle cx="190" cy="22" r="7" strokeWidth="2" className={cn(f.surface, s.green)} />
    </>
  ),
  devices: () => (
    <>
      <Ground />
      <g className="floaty">
        <rect x="50" y="14" width="120" height="26" rx="7" strokeWidth="2" className={cn(f.surface, s.brand)} />
        <circle cx="64" cy="27" r="3" className={f.green} />
        <circle cx="74" cy="27" r="3" className={f.green} />
        <path d="M120 27h36" strokeWidth="2" strokeLinecap="round" className={s.lilac} />
      </g>
      <g className="floaty" style={{ animationDelay: ".8s" }}>
        <rect x="50" y="46" width="120" height="26" rx="7" className={f.brand} />
        <circle cx="64" cy="59" r="3" className="fill-white" />
        <circle cx="74" cy="59" r="3" className="fill-[#c9c3fb]" />
        <path d="M120 59h36" strokeWidth="2" strokeLinecap="round" className="stroke-white" />
      </g>
      <path d="M170 27h22v32h-22" strokeWidth="2" className={cn(s.green, "flow")} />
    </>
  ),
  backups: () => (
    <>
      <Ground />
      <g className="floaty">
        <ellipse cx="84" cy="24" rx="30" ry="9" strokeWidth="2" className={cn(f.softer, s.brand)} />
        <path d="M54 24v40c0 5 13 9 30 9s30-4 30-9V24" strokeWidth="2" className={cn(f.surface, s.brand)} />
        <path d="M54 44c0 5 13 9 30 9s30-4 30-9" strokeWidth="2" className={s.brand} />
      </g>
      <path d="M124 48h40" strokeWidth="2.5" className={s.soft} />
      <path d="M124 48h40" strokeWidth="2.5" className={cn(s.green, "flow")} />
      <g className="floaty" style={{ animationDelay: ".7s" }}>
        <rect x="166" y="30" width="36" height="36" rx="9" strokeWidth="2" className={cn(f.surface, s.green)} />
        <path d="m176 48 6 6 11-11" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className={s.green} />
      </g>
    </>
  ),
  compliance: () => (
    <>
      <Ground />
      <g className="floaty">
        <path d="M110 10 78 22v22c0 18 14 32 32 36 18-4 32-18 32-36V22Z" strokeWidth="2.5" className={cn(f.softer, s.brand)} />
        <path d="m96 46 10 10 18-20" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className={s.green} />
      </g>
      <path d="M30 70h36M154 70h36" strokeWidth="2.5" className={cn(s.brand2, "flow")} />
      <circle cx="30" cy="70" r="5" className={f.brand} />
      <circle cx="190" cy="70" r="5" className={cn(f.orange, "blink")} />
    </>
  ),
  changes: () => (
    <>
      <Ground />
      <path d="M40 76V20M40 48c0-16 40-10 40-28M40 48c30 0 60 0 60 28" strokeWidth="2.5" className={s.soft} />
      <path d="M40 76V20M40 48c0-16 40-10 40-28M40 48c30 0 60 0 60 28" strokeWidth="2.5" className={cn(s.brand, "flow")} />
      <circle cx="40" cy="20" r="7" strokeWidth="2" className={cn(f.surface, s.brand)} />
      <circle cx="80" cy="20" r="7" className={f.brand} />
      <circle cx="100" cy="76" r="7" strokeWidth="2" className={cn(f.surface, s.green)} />
      <g className="floaty">
        <rect x="126" y="22" width="76" height="46" rx="10" strokeWidth="2" className={cn(f.surface, s.brand)} />
        <path d="M138 36h40M138 46h26M138 56h34" strokeWidth="2" strokeLinecap="round" className={s.lilac} />
        <circle cx="190" cy="34" r="4" className={cn(f.green, "blink")} />
      </g>
    </>
  ),
  tacacs: () => (
    <>
      <Ground />
      <path d="M26 60h50M144 60h50" strokeWidth="2.5" className={s.soft} />
      <path d="M26 60h50M144 60h50" strokeWidth="2.5" className={cn(s.brand, "flow")} />
      <g className="floaty">
        <rect x="80" y="36" width="60" height="44" rx="10" className={f.brand} />
        <path d="M94 36V26a16 16 0 0 1 32 0v10" strokeWidth="3" className={s.brand} />
        <circle cx="110" cy="56" r="5" className="fill-white" />
        <path d="M110 60v8" strokeWidth="3" strokeLinecap="round" className="stroke-white" />
      </g>
      <circle cx="22" cy="60" r="7" strokeWidth="2" className={cn(f.surface, s.green)} />
      <circle cx="198" cy="60" r="7" strokeWidth="2" className={cn(f.surface, s.brand)} />
    </>
  ),
  accounting: () => (
    <>
      <Ground />
      <g className="floaty">
        <rect x="46" y="12" width="128" height="68" rx="10" strokeWidth="2" className={cn(f.surface, s.brand)} />
        <path d="M46 26h128" strokeWidth="2" className={s.brand} />
        <circle cx="56" cy="19" r="2.5" className={f.orange} />
        <circle cx="64" cy="19" r="2.5" className={f.brand2} />
        <circle cx="72" cy="19" r="2.5" className={f.green} />
        <path d="m60 40 8 6-8 6" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className={s.brand} />
        <path d="M76 52h40" strokeWidth="2.4" strokeLinecap="round" className={s.lilac} />
        <path d="M60 66h70" strokeWidth="2.4" strokeLinecap="round" className={s.soft} />
        <rect x="120" y="47" width="7" height="10" rx="1" className={cn(f.brand, "blink")} />
      </g>
    </>
  ),
  sessions: () => (
    <>
      <Ground />
      <g className="floaty">
        <rect x="52" y="12" width="116" height="66" rx="10" strokeWidth="2" className={cn(f.softer, s.brand)} />
        <path d="m100 32 22 13-22 13Z" className={f.brand} />
      </g>
      <path d="M52 86h116" strokeWidth="3" strokeLinecap="round" className={s.soft} />
      <path d="M52 86h58" strokeWidth="3" strokeLinecap="round" className={s.brand} />
      <circle cx="110" cy="86" r="4" className={cn(f.brand, "blink")} />
    </>
  ),
  audit: () => (
    <>
      <Ground />
      {[0, 1, 2].map((i) => (
        <g key={i} className="floaty" style={{ animationDelay: `${i * 0.5}s` }}>
          <rect x={30 + i * 58} y={24 + (i % 2) * 10} width="44" height="52" rx="8" strokeWidth="2" className={cn(f.surface, i === 1 ? s.green : s.brand)} />
          <path d={`M${40 + i * 58} ${40 + (i % 2) * 10}h24M${40 + i * 58} ${50 + (i % 2) * 10}h16`} strokeWidth="2" strokeLinecap="round" className={s.lilac} />
        </g>
      ))}
      <path d="M74 50h14M132 50h14" strokeWidth="2.5" className={cn(s.brand, "flow")} />
    </>
  ),
  ixp: () => (
    <>
      <Ground />
      {[
        [30, 24],
        [30, 72],
        [190, 24],
        [190, 72],
        [110, 12],
      ].map(([x, y], i) => (
        <g key={i}>
          <path d={`M110 50 ${x} ${y}`} strokeWidth="2.5" className={s.soft} />
          <path d={`M110 50 ${x} ${y}`} strokeWidth="2.5" className={cn(i % 2 ? s.green : s.brand, "flow")} />
          <circle cx={x} cy={y} r="8" strokeWidth="2" className={cn(f.surface, i % 2 ? s.green : s.brand, "floaty")} style={{ animationDelay: `${i * 0.3}s` }} />
        </g>
      ))}
      <rect x="92" y="36" width="36" height="28" rx="8" className={f.brand} />
      <path d="M100 50h20" strokeWidth="2.4" strokeLinecap="round" className="stroke-white" />
    </>
  ),
  alerts: () => (
    <>
      <Ground />
      <g className="floaty">
        <path d="M110 14c-14 0-24 10-24 24v16l-8 10h64l-8-10V38c0-14-10-24-24-24Z" strokeWidth="2.5" className={cn(f.softer, s.brand)} />
        <path d="M102 70a8 8 0 0 0 16 0" strokeWidth="2.5" className={s.brand} />
      </g>
      <circle cx="134" cy="22" r="7" className={cn(f.orange, "blink")} />
      <path d="M40 40c6-8 6-18 0-26M180 40c-6-8-6-18 0-26" strokeWidth="2.5" strokeLinecap="round" className={s.lilac} />
    </>
  ),
  reports: () => (
    <>
      <Ground />
      <g className="floaty">
        <rect x="60" y="10" width="100" height="72" rx="10" strokeWidth="2" className={cn(f.surface, s.brand)} />
        <rect x="76" y="48" width="12" height="22" rx="3" className={f.brand} />
        <rect x="94" y="36" width="12" height="34" rx="3" className={f.orange} />
        <rect x="112" y="56" width="12" height="14" rx="3" className={f.green} />
        <rect x="130" y="28" width="12" height="42" rx="3" className={f.brand2} />
        <path d="M76 24h40" strokeWidth="2" strokeLinecap="round" className={s.lilac} />
      </g>
    </>
  ),
  integrations: () => (
    <>
      <Ground />
      <path d="M86 50h48" strokeWidth="3" className={s.soft} />
      <path d="M86 50h48" strokeWidth="3" className={cn(s.green, "flow")} />
      <g className="floaty">
        <rect x="36" y="26" width="50" height="48" rx="10" className={f.brand} />
        <path d="M54 40v-10M68 40v-10" strokeWidth="3" strokeLinecap="round" className="stroke-white" />
      </g>
      <g className="floaty" style={{ animationDelay: ".8s" }}>
        <rect x="134" y="26" width="50" height="48" rx="10" strokeWidth="2" className={cn(f.surface, s.brand)} />
        <circle cx="159" cy="50" r="8" strokeWidth="2" className={s.green} />
      </g>
    </>
  ),
  users: () => (
    <>
      <Ground />
      {[
        [70, s.brand, f.softer, 0],
        [110, s.green, f.surface, 0.5],
        [150, s.brand, f.softer, 1],
      ].map(([x, st, fl, d], i) => (
        <g key={i} className="floaty" style={{ animationDelay: `${d}s` }}>
          <circle cx={x as number} cy={i === 1 ? 30 : 38} r="12" strokeWidth="2" className={cn(fl as string, st as string)} />
          <path d={`M${(x as number) - 20} ${i === 1 ? 74 : 80}c0-14 9-22 20-22s20 8 20 22`} strokeWidth="2" className={cn(fl as string, st as string)} />
        </g>
      ))}
    </>
  ),
  settings: () => (
    <>
      <Ground />
      <g className="fan" style={{ transformOrigin: "center" }}>
        <circle cx="96" cy="48" r="22" strokeWidth="2.5" strokeDasharray="8 5" className={s.brand} />
      </g>
      <circle cx="96" cy="48" r="11" className={f.brand} />
      <g className="floaty">
        <rect x="136" y="30" width="52" height="36" rx="9" strokeWidth="2" className={cn(f.surface, s.green)} />
        <path d="M148 48h20" strokeWidth="2.4" strokeLinecap="round" className={s.green} />
        <circle cx="176" cy="48" r="4" className={f.green} />
      </g>
    </>
  ),
};

export function HeaderIllustration({ art, className }: { art: HeaderArt; className?: string }) {
  const Art = ART[art];
  return (
    <Svg viewBox="0 0 220 100" className={className}>
      <Art />
    </Svg>
  );
}

/** Map a pathname to a header illustration. */
export function artForPath(pathname: string): HeaderArt | null {
  const seg = pathname.split("/")[1] ?? "";
  const map: Record<string, HeaderArt> = {
    map: "network",
    devices: "devices",
    backups: "backups",
    compliance: "compliance",
    changes: "changes",
    tacacs: "tacacs",
    accounting: "accounting",
    sessions: "sessions",
    audit: "audit",
    ixp: "ixp",
    alerts: "alerts",
    reports: "reports",
    integrations: "integrations",
    users: "users",
    settings: "settings",
  };
  return map[seg] ?? null;
}

// --- empty state scenes --------------------------------------------------------------------------

export type EmptyArt = "default" | "chart" | "search" | "success" | "network";

/** Illustrated scene for empty states: floating cards, a flowing link and the context icon in a tile. */
export function EmptyScene({ art = "default", icon: Icon, className }: { art?: EmptyArt; icon?: LucideIcon; className?: string }) {
  const accent = art === "success" ? s.green : s.brand;
  return (
    <div className={cn("relative mx-auto h-[104px] w-[200px]", className)} aria-hidden>
      <Svg viewBox="0 0 200 104" className="absolute inset-0 h-full w-full">
        <ellipse cx="100" cy="94" rx="84" ry="7" className={f.ground} />
        {art === "chart" ? (
          <>
            <path d="M28 20v58h144" strokeWidth="2" strokeLinecap="round" className={s.lilac} />
            <path d="M36 66h128" strokeWidth="2.5" className={cn(s.brand2, "flow")} />
            <path d="M40 40h20M40 52h12" strokeWidth="2" strokeLinecap="round" className={s.soft} />
          </>
        ) : art === "network" ? (
          <>
            <path d="M24 70 60 34M140 34l36 36" strokeWidth="2.5" className={s.soft} />
            <path d="M24 70 60 34M140 34l36 36" strokeWidth="2.5" className={cn(s.brand, "flow")} />
            <circle cx="24" cy="70" r="7" strokeWidth="2" className={cn(f.surface, s.brand)} />
            <circle cx="176" cy="70" r="7" strokeWidth="2" className={cn(f.surface, s.green)} />
          </>
        ) : (
          <>
            <g className="floaty">
              <rect x="14" y="34" width="46" height="32" rx="8" strokeWidth="2" className={cn(f.surface, s.lilac)} />
              <path d="M24 46h24M24 55h14" strokeWidth="2" strokeLinecap="round" className={s.soft} />
            </g>
            <g className="floaty" style={{ animationDelay: "1s" }}>
              <rect x="140" y="26" width="46" height="32" rx="8" strokeWidth="2" className={cn(f.surface, s.lilac)} />
              <path d="M150 38h24M150 47h14" strokeWidth="2" strokeLinecap="round" className={s.soft} />
            </g>
            <path d="M60 50h14M126 42h14" strokeWidth="2.5" className={cn(accent, "flow")} />
          </>
        )}
        {art === "search" ? <path d="m122 66 12 12" strokeWidth="4" strokeLinecap="round" className={s.brand} /> : null}
      </Svg>
      <div className="absolute left-1/2 top-[18px] -translate-x-1/2">
        <div
          className={cn(
            "floaty flex h-14 w-14 items-center justify-center rounded-[14px] border-2",
            art === "success" ? "border-[var(--ill-green)] bg-success-soft text-success" : "border-[var(--ill-brand)] bg-accent text-accent-foreground",
          )}
          style={{ animationDelay: ".4s" }}
        >
          {Icon ? <Icon className="h-6 w-6" aria-hidden /> : null}
        </div>
      </div>
    </div>
  );
}
