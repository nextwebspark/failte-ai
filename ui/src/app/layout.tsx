import "./globals.css";

import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Suspense } from "react";

import AppLayout from "@/components/layout/AppLayout";
import PostHogIdentify from "@/components/PostHogIdentify";
import { SentryErrorBoundary } from "@/components/SentryErrorBoundary";
import SpinLoader from "@/components/SpinLoader";
import { ThemeProvider } from "@/components/ThemeProvider";
import { Toaster } from "@/components/ui/sonner";
import { AppConfigProvider } from "@/context/AppConfigContext";
import { OnboardingProvider } from "@/context/OnboardingContext";
import { OrgConfigProvider } from "@/context/OrgConfigContext";
import { TelephonyConfigWarningsProvider } from "@/context/TelephonyConfigWarningsContext";
import { AuthProvider } from "@/lib/auth";


// Inter for prose, JetBrains Mono for data, metadata and numerals — the type
// pairing the design canvas is built on (app-doc/claude-design/). Both are
// wired to --font-sans / --font-mono in globals.css.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Failte AI",
  description: "Build, test and deploy voice AI agents",
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode
}) {

  return (
    // The font variables must sit on <html>: Tailwind's preflight sets
    // font-family on html from :root, so variables scoped to <body> never
    // reach it and the sans stack silently falls back to system-ui.
    <html
      lang="en"
      className={`dark ${inter.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Inline script to prevent flash of light theme - runs before React hydrates.
            Dark is the locked default: only an explicit stored 'light' opts out. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var theme = localStorage.getItem('theme');
                  if (theme === 'light') {
                    document.documentElement.classList.remove('dark');
                  } else {
                    document.documentElement.classList.add('dark');
                  }
                } catch (e) {
                  document.documentElement.classList.add('dark');
                }
              })();
            `,
          }}
        />
      </head>
      <body
        className="antialiased">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
          <SentryErrorBoundary>
            <AuthProvider>
              <AppConfigProvider>
                <Suspense fallback={<SpinLoader />}>
                  <OrgConfigProvider>
                    <TelephonyConfigWarningsProvider>
                      <OnboardingProvider>
                        <PostHogIdentify />
                        <AppLayout>
                          {children}
                        </AppLayout>
                        <Toaster />
                      </OnboardingProvider>
                    </TelephonyConfigWarningsProvider>
                  </OrgConfigProvider>
                </Suspense>
              </AppConfigProvider>
            </AuthProvider>
          </SentryErrorBoundary>
        </ThemeProvider>
      </body>
    </html>
  );
}
