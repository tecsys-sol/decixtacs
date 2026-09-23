import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

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
        diff: {
          "add-bg": hsl("--diff-add-bg"),
          "add-fg": hsl("--diff-add-fg"),
          "del-bg": hsl("--diff-del-bg"),
          "del-fg": hsl("--diff-del-fg"),
          "mod-bg": hsl("--diff-mod-bg"),
          "mod-fg": hsl("--diff-mod-fg"),
        },
      },
      borderRadius: {
        "2xl": "20px",
        xl: "16px",
        lg: "var(--radius)",
        md: "10px",
        sm: "7px",
      },
      fontFamily: {
        sans: ["var(--font-manrope)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-sora)", "var(--font-manrope)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
      },
    },
  },
  plugins: [animate],
};

export default config;
