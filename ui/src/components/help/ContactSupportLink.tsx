"use client";

import type { ReactNode } from "react";

import { SUPPORT_MAILTO } from "@/components/SupportLink";
import { cn } from "@/lib/utils";

import { useHelpPanel } from "./HelpPanel";

/**
 * A link that opens Help on its "Contact support" tab (outside the app
 * shell, where there is no Help panel, it falls back to an email).
 */
export function ContactSupportLink({ children, className }: { children: ReactNode; className?: string }) {
    const help = useHelpPanel();
    const style = cn("font-semibold text-brand outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/40", className);
    if (!help) {
        return (
            <a href={SUPPORT_MAILTO} className={style}>
                {children}
            </a>
        );
    }
    return (
        <button type="button" onClick={() => help.openHelp("contact")} className={style}>
            {children}
        </button>
    );
}
