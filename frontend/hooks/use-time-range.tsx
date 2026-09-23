"use client";

import * as React from "react";

import type { TimeRange } from "@/lib/aggregate";

const KEY = "nom.timeRange";

interface Ctx {
  range: TimeRange;
  setRange: (r: TimeRange) => void;
}

const TimeRangeContext = React.createContext<Ctx>({ range: "24h", setRange: () => undefined });

function read(): TimeRange {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v === "24h" || v === "7d" || v === "30d") return v;
  } catch {
    /* storage unavailable */
  }
  return "24h";
}

/** App-wide time window for activity charts (top-bar pill and per-card segmented controls). */
export function TimeRangeProvider({ children }: { children: React.ReactNode }) {
  const [range, setState] = React.useState<TimeRange>(read);
  const setRange = React.useCallback((r: TimeRange) => {
    setState(r);
    try {
      window.localStorage.setItem(KEY, r);
    } catch {
      /* storage unavailable */
    }
  }, []);
  const value = React.useMemo(() => ({ range, setRange }), [range, setRange]);
  return <TimeRangeContext.Provider value={value}>{children}</TimeRangeContext.Provider>;
}

export function useTimeRange(): Ctx {
  return React.useContext(TimeRangeContext);
}
