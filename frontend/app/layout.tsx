import type { Metadata, Viewport } from "next";
// Self-hosted fonts (npm @fontsource packages): the build needs no access to Google Fonts. Each
// @font-face is only downloaded by the browser when the active design theme uses it.
import "@fontsource-variable/manrope";
import "@fontsource-variable/sora";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/fraunces/opsz.css";
import "@fontsource-variable/fraunces/opsz-italic.css";
import "@fontsource-variable/ibm-plex-sans";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import { Providers } from "@/components/providers";
import { DESIGN_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

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
    <html lang="en" suppressHydrationWarning>
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
