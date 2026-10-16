import "./globals.css";

import type { Metadata } from "next";
import { JetBrains_Mono, Montserrat, Sora } from "next/font/google";
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


// Montserrat is the brand kit's typeface: 700 for headings and the wordmark,
// 500/400 for interface and body copy. JetBrains Mono stays for data, metadata
// and numerals. Both are wired to --font-sans / --font-mono in globals.css.
const montserrat = Montserrat({
  variable: "--font-montserrat",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

// Sora 600 is the LightMove wordmark face (brand-kit/lightmove-brand). It is
// used only by BrandLogo's live-text wordmark (`font-display`); interface copy
// stays on Montserrat.
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
      className={`dark ${montserrat.variable} ${jetbrainsMono.variable} ${sora.variable}`}
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
