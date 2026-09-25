import type { Metadata, Viewport } from "next";
import { Inter, Fraunces, Noto_Sans_Devanagari, Noto_Sans_Kannada, Noto_Sans_Telugu, Noto_Sans_Tamil } from "next/font/google";
import "./globals.css";
import { ServiceWorkerRegistrar } from "@/components/ServiceWorkerRegistrar";
import { LanguageProvider } from "@/contexts/LanguageContext";
import { ClassroomBrain } from "@/components/brain/ClassroomBrain";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

// Display serif for the "premium" redesigned surfaces (Command Center hero,
// Teaching page) — opted into per-element via --font-fraunces, never applied
// globally, so it has no effect on any existing ("classic") page.
const fraunces = Fraunces({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-fraunces" });

// Inter only covers Latin glyphs — a textbook uploaded in Hindi, Marathi
// (both Devanagari script), Kannada, Telugu, or Tamil would otherwise fall
// back to whatever script fonts happen to be installed on the OS, which on
// a minimal Raspberry Pi kiosk image is often nothing (renders as blank
// "tofu" boxes). These self-hosted Noto Sans variants are wired into the
// body's font-family fallback chain in globals.css so the right one is
// picked per-character automatically, with no JS needed.
const notoDevanagari = Noto_Sans_Devanagari({ subsets: ["devanagari"], weight: ["400", "600", "700"], variable: "--font-noto-devanagari" });
const notoKannada = Noto_Sans_Kannada({ subsets: ["kannada"], weight: ["400", "600", "700"], variable: "--font-noto-kannada" });
const notoTelugu = Noto_Sans_Telugu({ subsets: ["telugu"], weight: ["400", "600", "700"], variable: "--font-noto-telugu" });
const notoTamil = Noto_Sans_Tamil({ subsets: ["tamil"], weight: ["400", "600", "700"], variable: "--font-noto-tamil" });

// ── PWA + SEO metadata ─────────────────────────────────────────────────────────

export const metadata: Metadata = {
  title: "Drishti – Classroom Intelligence",
  description: "Capture classroom board content and generate AI-powered learning assets — notes, quizzes, experiments, and more.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Drishti",
  },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#4f46e5",
};

// ── Root layout ────────────────────────────────────────────────────────────────

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.variable} ${fraunces.variable} ${notoDevanagari.variable} ${notoKannada.variable} ${notoTelugu.variable} ${notoTamil.variable} h-full antialiased`}>
        <LanguageProvider>
          {children}
        </LanguageProvider>
        {/* Moved here from (dashboard)/layout.tsx (2026-09-24) so it's also
            available on /welcome, which sits outside that route group —
            needed for voice commands on the Welcome/attendance flow. It's
            self-contained (fixed-position, no dependency on the dashboard's
            Sidebar/TopBar layout), so mounting it at the root is safe and
            it now covers every page instead of just the dashboard ones. */}
        <ClassroomBrain />
        {/* Registers /sw.js — rendered client-side only, no visual output */}
        <ServiceWorkerRegistrar />
      </body>
    </html>
  );
}
