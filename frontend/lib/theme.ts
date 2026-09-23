/**
 * Design themes. Two independent axes:
 *
 *  - design: "aurora" | "meridian" — the visual language (tokens, fonts, radii, shell layout,
 *    illustrations, chart palettes). Stored in localStorage + a cookie and applied as
 *    `data-design` on <html> by an inline script before first paint.
 *  - colour mode: "light" | "dark" | "system" — handled by next-themes (`.dark` class on <html>).
 *
 * CSS variables for every design × mode combination live in app/globals.css; Tailwind reads
 * them, so components never branch on the design for colours. This module is framework-free so
 * the inline script and tests can use it.
 */

export type Design = "aurora" | "meridian";
export type ColorMode = "light" | "dark";

export const DESIGNS: Design[] = ["aurora", "meridian"];
export const DEFAULT_DESIGN: Design = "aurora";

export const DESIGN_STORAGE_KEY = "nom.design";
export const DESIGN_COOKIE = "nom-design";
export const DESIGN_ATTRIBUTE = "data-design";

export interface DesignMeta {
  id: Design;
  label: string;
  tagline: string;
  /** fixed preview colours (independent of the active theme) used by the switcher swatches */
  preview: {
    light: { page: string; surface: string; border: string; ink: string; muted: string; primary: string; accent: string };
    dark: { page: string; surface: string; border: string; ink: string; muted: string; primary: string; accent: string };
  };
  /** browser UI colour (meta theme-color) */
  themeColor: Record<ColorMode, string>;
}

export const DESIGN_META: Record<Design, DesignMeta> = {
  aurora: {
    id: "aurora",
    label: "Aurora",
    tagline: "Crisp indigo, Sora headings and a left sidebar.",
    preview: {
      light: { page: "#eef0f8", surface: "#ffffff", border: "#e4e5f1", ink: "#14142b", muted: "#5d5f7a", primary: "#5b4ee6", accent: "#dc6a22" },
      dark: { page: "#15152a", surface: "#1d1d36", border: "#2c2c4a", ink: "#ebebf5", muted: "#a3a4bf", primary: "#8f85f0", accent: "#f08a4b" },
    },
    themeColor: { light: "#eef0f8", dark: "#15152a" },
  },
  meridian: {
    id: "meridian",
    label: "Meridian",
    tagline: "Warm ivory, Fraunces serif and pill navigation on top.",
    preview: {
      light: { page: "#f6f2ea", surface: "#fffdf8", border: "#e6dfd0", ink: "#1f1b16", muted: "#5f5545", primary: "#0b5f59", accent: "#c2502a" },
      dark: { page: "#17140f", surface: "#211d17", border: "#3a332a", ink: "#f1ebdf", muted: "#b5aa96", primary: "#3fb8a8", accent: "#ec8a62" },
    },
    themeColor: { light: "#f6f2ea", dark: "#17140f" },
  },
};

export function isDesign(v: unknown): v is Design {
  return v === "aurora" || v === "meridian";
}

export function otherDesign(d: Design): Design {
  return d === "aurora" ? "meridian" : "aurora";
}

/** Read the design from a Cookie header / document.cookie string. */
export function designFromCookie(cookie: string | null | undefined): Design | null {
  if (!cookie) return null;
  const m = cookie.match(new RegExp(`(?:^|;\\s*)${DESIGN_COOKIE}=([^;]+)`));
  const v = m ? decodeURIComponent(m[1]) : null;
  return isDesign(v) ? v : null;
}

/**
 * Inline script run in <head> before first paint: localStorage wins, then the cookie, then the
 * default. Kept dependency-free and tiny; it must never throw.
 */
export const DESIGN_INIT_SCRIPT = `(function(){try{var d=null;try{d=localStorage.getItem(${JSON.stringify(DESIGN_STORAGE_KEY)})}catch(e){}if(d!=="aurora"&&d!=="meridian"){var m=document.cookie.match(/(?:^|;\\s*)${DESIGN_COOKIE}=([^;]+)/);d=m?decodeURIComponent(m[1]):null}if(d!=="aurora"&&d!=="meridian")d=${JSON.stringify(DEFAULT_DESIGN)};document.documentElement.setAttribute(${JSON.stringify(DESIGN_ATTRIBUTE)},d)}catch(e){}})();`;

/** Apply + persist a design (client only). */
export function applyDesign(design: Design): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute(DESIGN_ATTRIBUTE, design);
  try {
    window.localStorage.setItem(DESIGN_STORAGE_KEY, design);
  } catch {
    /* storage unavailable (private mode) — the cookie still persists the choice */
  }
  try {
    document.cookie = `${DESIGN_COOKIE}=${design}; path=/; max-age=31536000; samesite=lax`;
  } catch {
    /* ignore */
  }
}

/** Current design from the DOM (client) — the single source of truth after the init script ran. */
export function readDesign(): Design {
  if (typeof document === "undefined") return DEFAULT_DESIGN;
  const v = document.documentElement.getAttribute(DESIGN_ATTRIBUTE);
  return isDesign(v) ? v : DEFAULT_DESIGN;
}
