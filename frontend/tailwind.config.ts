import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";
import plugin from "tailwindcss/plugin";

const hsl = (v: string) => `hsl(var(${v}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./hooks/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1rem" },
    extend: {
      colors: {
        border: hsl("--border"),
        input: hsl("--input"),
        ring: hsl("--ring"),
        background: hsl("--background"),
        foreground: hsl("--foreground"),
        primary: { DEFAULT: hsl("--primary"), hover: hsl("--primary-hover"), foreground: hsl("--primary-foreground") },
        secondary: { DEFAULT: hsl("--secondary"), foreground: hsl("--secondary-foreground") },
        muted: { DEFAULT: hsl("--muted"), foreground: hsl("--muted-foreground") },
        accent: { DEFAULT: hsl("--accent"), foreground: hsl("--accent-foreground") },
        destructive: { DEFAULT: hsl("--destructive"), foreground: hsl("--destructive-foreground") },
        success: { DEFAULT: hsl("--success"), foreground: hsl("--success-foreground"), soft: hsl("--success-soft") },
        warning: { DEFAULT: hsl("--warning"), foreground: hsl("--warning-foreground"), soft: hsl("--warning-soft") },
        danger: { DEFAULT: hsl("--danger"), soft: hsl("--danger-soft") },
        info: { DEFAULT: hsl("--info"), foreground: hsl("--info-foreground"), soft: hsl("--info-soft") },
        card: { DEFAULT: hsl("--card"), foreground: hsl("--card-foreground") },
        popover: { DEFAULT: hsl("--popover"), foreground: hsl("--popover-foreground") },
        ink: { 2: hsl("--ink-2"), 3: hsl("--ink-3") },
        label: hsl("--label"),
        "row-hover": hsl("--row-hover"),
        "nav-hover": hsl("--nav-hover"),
        sidebar: { DEFAULT: hsl("--sidebar"), foreground: hsl("--sidebar-foreground"), border: hsl("--sidebar-border") },
        overlay: hsl("--overlay"),
        avatar: { DEFAULT: hsl("--avatar"), foreground: hsl("--avatar-foreground") },
        "hero-panel": hsl("--hero-panel"),
        pill: { active: hsl("--pill-active"), "active-foreground": hsl("--pill-active-foreground") },
        sev: { critical: hsl("--sev-critical"), high: hsl("--sev-high"), medium: hsl("--sev-medium"), low: hsl("--sev-low") },
        diff: {
          "add-bg": hsl("--diff-add-bg"),
          "add-fg": hsl("--diff-add-fg"),
          "del-bg": hsl("--diff-del-bg"),
          "del-fg": hsl("--diff-del-fg"),
          "mod-bg": hsl("--diff-mod-bg"),
          "mod-fg": hsl("--diff-mod-fg"),
        },
      },
      // radii and fonts follow the active design theme (CSS variables in app/globals.css)
      borderRadius: {
        "2xl": "var(--radius-2xl)",
        xl: "var(--radius-xl)",
        lg: "var(--radius)",
        md: "var(--radius-md)",
        sm: "var(--radius-sm)",
        btn: "var(--radius-btn)",
        pill: "var(--radius-pill)",
      },
      fontFamily: {
        sans: ["var(--font-body)"],
        display: ["var(--font-display)"],
        mono: ["var(--font-code)"],
      },
      fontWeight: {
        heading: "var(--heading-weight)",
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
      },
    },
  },
  plugins: [
    animate,
    // `meridian:` / `aurora:` variants for the few structural differences that CSS can express
    // (works before hydration, so server-rendered pages never flash the wrong layout)
    plugin(({ addVariant }) => {
      addVariant("meridian", ':is([data-design="meridian"] &)');
      addVariant("aurora", ':is(:root:not([data-design="meridian"]) &)');
    }),
  ],
};

export default config;
