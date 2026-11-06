import type { ReactNode } from "react";

import { BrandLogo } from "@/components/BrandLogo";

/** The small branded page a report email's link opens (no app shell). */
export function ReportLinkCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="flex min-h-svh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md space-y-5 rounded-2xl border border-line bg-card p-6 shadow-panel sm:p-8">
        <BrandLogo size={26} />
        <h1 className="text-xl font-bold tracking-[-0.01em] text-foreground">{title}</h1>
        <div className="space-y-3 text-[14.5px] leading-relaxed text-ink-2">{children}</div>
      </div>
    </main>
  );
}
