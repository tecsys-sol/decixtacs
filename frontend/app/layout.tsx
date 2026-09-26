import type { Metadata, Viewport } from "next";
import { Fraunces, IBM_Plex_Mono, IBM_Plex_Sans, JetBrains_Mono, Manrope, Sora } from "next/font/google";

import { Providers } from "@/components/providers";
import { DESIGN_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

const sora = Sora({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-sora", display: "swap" });
const manrope = Manrope({ subsets: ["latin"], weight: ["400", "500", "600", "700", "800"], variable: "--font-manrope", display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-jetbrains", display: "swap" });
// Meridian: not preloaded (Aurora is the default); fetched as soon as the Meridian variables apply.
const fraunces = Fraunces({ subsets: ["latin"], style: ["normal", "italic"], axes: ["opsz"], variable: "--font-fraunces", display: "swap", preload: false });
const plexSans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-plex-sans", display: "swap", preload: false });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap", preload: false });

const FONT_VARIABLES = [sora, manrope, jetbrains, fraunces, plexSans, plexMono].map((f) => f.variable).join(" ");

export const metadata: Metadata = {
  title: { default: "DE-CIX NetworkOps Manager", template: "%s · DE-CIX NetworkOps" },
  description: "Network access and configuration management for ISPs and IXPs",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#15152a" },
    { media: "(prefers-color-scheme: light)", color: "#eef0f8" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={FONT_VARIABLES} suppressHydrationWarning>
      <head>
        {/* applies the stored design theme (localStorage / cookie) before first paint */}
        <script dangerouslySetInnerHTML={{ __html: DESIGN_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
