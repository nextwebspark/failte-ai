"use client";

import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { usePlatformAdmin } from "@/app/skills/useSkills";
import { AdminLoading } from "@/components/platform-admin/AdminStates";
import { cn } from "@/lib/utils";

/** The platform admin area's own navigation; nothing here is in the
 *  workspace nav. */
const ADMIN_TABS = [
    { href: "/superadmin", label: "Overview", exact: true },
    { href: "/superadmin/health", label: "Health" },
    { href: "/superadmin/features", label: "Features" },
    { href: "/superadmin/home-layout", label: "Home layout" },
    { href: "/superadmin/organizations", label: "Organisations" },
    { href: "/superadmin/users", label: "Users" },
    { href: "/superadmin/audit", label: "Audit log" },
    { href: "/superadmin/runs", label: "All runs" },
];

export default function PlatformAdminLayout({ children }: { children: ReactNode }) {
    const pathname = usePathname();
    const isAdmin = usePlatformAdmin();

    if (isAdmin === null) {
        return (
            <div className="mx-auto w-full max-w-6xl p-6">
                <AdminLoading />
            </div>
        );
    }
    if (!isAdmin) {
        // No tabs: they would only lead to more of this message.
        return (
            <div className="mx-auto w-full max-w-6xl p-6">
                <p className="text-sm text-ink-2">
                    This area is for platform admins only. Ask a platform admin to grant you access.
                </p>
            </div>
        );
    }

    return (
        <div className="mx-auto w-full max-w-6xl space-y-5 p-6">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber/40 bg-amber-dim px-4 py-2.5">
                <div className="flex items-center gap-2 text-sm">
                    <ShieldAlert className="h-4 w-4 text-amber" aria-hidden />
                    <span className="font-semibold">Platform admin</span>
                    <span className="text-ink-2">Changes here affect every workspace, and are recorded in the audit log.</span>
                </div>
            </div>
            <nav aria-label="Platform admin" className="flex flex-wrap gap-1 border-b border-line">
                {ADMIN_TABS.map((tab) => {
                    const active = tab.exact ? pathname === tab.href : pathname.startsWith(tab.href);
                    return (
                        <Link
                            key={tab.href}
                            href={tab.href}
                            aria-current={active ? "page" : undefined}
                            className={cn(
                                "-mb-px border-b-2 px-3 py-2 text-sm",
                                active
                                    ? "border-foreground font-semibold text-foreground"
                                    : "border-transparent text-ink-3 hover:text-foreground",
                            )}
                        >
                            {tab.label}
                        </Link>
                    );
                })}
            </nav>
            {children}
        </div>
    );
}
