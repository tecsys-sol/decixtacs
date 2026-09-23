"use client";

import { useTheme } from "next-themes";
import * as React from "react";

import { chartTheme, type ChartTheme } from "@/lib/charts";
import {
  applyDesign,
  DEFAULT_DESIGN,
  DESIGN_ATTRIBUTE,
  DESIGN_STORAGE_KEY,
  isDesign,
  otherDesign,
  readDesign,
  type ColorMode,
  type Design,
} from "@/lib/theme";

/*
 * The design lives on <html data-design>, set before paint by the inline script in app/layout.tsx.
 * The DOM attribute is the store: components subscribe with useSyncExternalStore, so no provider
 * is needed and every consumer (shell, charts, illustrations) re-renders together on a switch.
 */

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: [DESIGN_ATTRIBUTE] });
  // keep tabs in sync: another tab changed the stored design
  const onStorage = (e: StorageEvent) => {
    if (e.key === DESIGN_STORAGE_KEY && isDesign(e.newValue) && e.newValue !== readDesign()) {
      document.documentElement.setAttribute(DESIGN_ATTRIBUTE, e.newValue);
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    observer.disconnect();
    window.removeEventListener("storage", onStorage);
  };
}

const serverSnapshot = () => DEFAULT_DESIGN;

export function useDesign(): {
  design: Design;
  setDesign: (d: Design) => void;
  toggleDesign: () => void;
} {
  const design = React.useSyncExternalStore(subscribe, readDesign, serverSnapshot);
  const setDesign = React.useCallback((d: Design) => {
    applyDesign(d);
  }, []);
  const toggleDesign = React.useCallback(() => {
    applyDesign(otherDesign(readDesign()));
  }, []);
  return { design, setDesign, toggleDesign };
}

/** Resolved colour mode (light / dark) following next-themes. */
export function useColorMode(): ColorMode {
  const { resolvedTheme } = useTheme();
  return resolvedTheme === "dark" ? "dark" : "light";
}

/** Chart token object for the active design × mode; charts rebuild their options when it changes. */
export function useChartTheme(): ChartTheme {
  const { design } = useDesign();
  const mode = useColorMode();
  return chartTheme(design, mode);
}
