import "./globals.css";

import type { Metadata } from "next";
import { DM_Sans, JetBrains_Mono, Sora } from "next/font/google";
import { Suspense } from "react";

import AppLayout from "@/components/layout/AppLayout";
import PostHogIdentify from "@/components/PostHogIdentify";
import { SentryErrorBoundary } from "@/components/SentryErrorBoundary";
import SpinLoader from "@/components/SpinLoader";
import { ThemeProvider } from "@/components/ThemeProvider";
import { Toaster } from "@/components/ui/sonner";
import { BRAND } from "@/config/brand";
import { AppConfigProvider } from "@/context/AppConfigContext";
import { OnboardingProvider } from "@/context/OnboardingContext";
import { OrgConfigProvider } from "@/context/OrgConfigContext";
import { TelephonyConfigWarningsProvider } from "@/context/TelephonyConfigWarningsContext";
import { AuthProvider } from "@/lib/auth";


// DM Sans is the brand kit's interface and body face (brand-kit/lightmove-brand/
// BRAND.md): 400 body, 500 interface, 600 headings, 700 screen titles.
// JetBrains Mono is for data only — ids, timers, numbers, keys. Both are wired
// to --font-sans / --font-mono in globals.css.
const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

// Sora 600 is the brand kit's display face: the BrandLogo wordmark and large
// display numbers (`font-display`). Interface copy stays on DM Sans.
const sora = Sora({
  variable: "--font-sora",
  subsets: ["latin"],
  weight: ["600"],
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || BRAND.appUrl),
  applicationName: BRAND.name,
  title: { default: BRAND.name, template: `%s · ${BRAND.name}` },
  description: BRAND.tagline,
  openGraph: {
    siteName: BRAND.name,
    title: BRAND.name,
    description: BRAND.tagline,
    images: [{ ...BRAND.assets.ogImage, alt: BRAND.name }],
  },
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
      className={`${dmSans.variable} ${jetbrainsMono.variable} ${sora.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Inline script to prevent a theme flash - runs before React hydrates.
            An explicit stored choice wins; otherwise follow the OS, which is
            what the brand kit asks for (light default, dark when the OS is). */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                var dark = false;
                try {
                  var theme = localStorage.getItem('theme');
                  if (theme === 'dark') {
                    dark = true;
                  } else if (theme !== 'light') {
                    dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                  }
                } catch (e) {}
                document.documentElement.classList.toggle('dark', dark);
              })();
            `,
          }}
        />
      </head>
      <body
        className="antialiased">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
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
