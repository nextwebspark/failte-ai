"use client";

import { CalendarCheck, Cpu, FileText, GitBranch, type LucideIcon, Plus, TrendingUp } from 'lucide-react';
import Link from 'next/link';

import { SupportLink } from '@/components/SupportLink';
import { Panel, PanelDescription, PanelTitle } from '@/components/ui/panel';
import { SectionHeading, SectionHint } from '@/components/ui/section-heading';
import { BRAND } from "@/config/brand";
import { useOrgConfig } from '@/context/OrgConfigContext';
import { useAuth } from '@/lib/auth';
import type { Permission } from '@/lib/auth/roles';

/** One place an owner or their team goes from the Overview. */
interface Shortcut {
    title: string;
    description: string;
    href: string;
    icon: LucideIcon;
    /** Listed only for roles that can open the page. */
    requires: Permission;
}

/** What a business owner checks day to day. */
const DAILY: Shortcut[] = [
    {
        title: 'Calls',
        description: 'Listen back to calls and see how each one went.',
        href: '/usage',
        icon: TrendingUp,
        requires: 'reports:read',
    },
    {
        title: 'Bookings',
        description: 'See the bookings your agent made, by day.',
        href: '/bookings',
        icon: CalendarCheck,
        requires: 'calls:read',
    },
    {
        title: 'Reports',
        description: 'Download a list of calls for a date range.',
        href: '/reports',
        icon: FileText,
        requires: 'reports:read',
    },
    {
        title: 'Your agents',
        description: 'See the agents that answer your phone.',
        href: '/workflow',
        icon: GitBranch,
        requires: 'agents:read',
    },
];

/** Setting agents up: only for people who can change them. */
const SETUP: Shortcut[] = [
    {
        title: 'Create an agent',
        description: 'Start from a ready-made agent for your kind of business.',
        href: '/workflow/create',
        icon: Plus,
        requires: 'agents:write',
    },
    {
        title: 'Voice and language',
        description: "Choose your agent's voice and language.",
        href: '/model-configurations',
        icon: Cpu,
        requires: 'credentials:write',
    },
];

function ShortcutCard({ shortcut }: { shortcut: Shortcut }) {
    const Icon = shortcut.icon;
    return (
        <li>
            <Link
                href={shortcut.href}
                className="group block h-full rounded-lg outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40"
            >
                <Panel className="h-full transition-colors group-hover:border-brand/60">
                    <div className="flex items-start gap-3">
                        <Icon className="mt-0.5 size-5 flex-none text-ink-3" aria-hidden />
                        <div className="min-w-0">
                            <PanelTitle as="h3">{shortcut.title}</PanelTitle>
                            <PanelDescription>{shortcut.description}</PanelDescription>
                        </div>
                    </div>
                </Panel>
            </Link>
        </li>
    );
}

export default function OverviewPage() {
    const { user, provider } = useAuth();
    const { can } = useOrgConfig();
    const isOSSMode = provider !== 'stack';

    const daily = DAILY.filter((s) => can(s.requires));
    const setup = SETUP.filter((s) => can(s.requires));

    return (
        <div className="page-body">
            <div className="max-w-4xl animate-fade-up">
                {/* Welcome */}
                <div className="mb-8">
                    <h1 className="text-2xl font-bold tracking-tight">
                        {isOSSMode ? (
                            `Welcome to ${BRAND.name}`
                        ) : (
                            `Welcome${user?.displayName ? `, ${user.displayName.split(' ')[0]}` : ''}!`
                        )}
                    </h1>
                    <p className="mt-1.5 text-sm text-ink-3">
                        Your phone agent at a glance. Pick where to go next.
                    </p>
                </div>

                {daily.length > 0 && (
                    <section aria-labelledby="overview-daily">
                        <SectionHeading id="overview-daily">Day to day</SectionHeading>
                        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
                            {daily.map((s) => (
                                <ShortcutCard key={s.href} shortcut={s} />
                            ))}
                        </ul>
                    </section>
                )}

                {setup.length > 0 && (
                    <section aria-labelledby="overview-setup" className="mt-8">
                        <SectionHeading id="overview-setup">Set up</SectionHeading>
                        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
                            {setup.map((s) => (
                                <ShortcutCard key={s.href} shortcut={s} />
                            ))}
                        </ul>
                    </section>
                )}

                {/* Resources */}
                <SectionHeading className="mt-8" action={<SectionHint>Get help from the team</SectionHint>}>
                    Help
                </SectionHeading>
                <Panel>
                    <div className="flex flex-wrap gap-4">
                        {/* Upstream had a Documentation button and a "Report an Issue"
                            button here, both pointing at dograh-hq. We publish neither a
                            docs site nor a public tracker, so the card offers the one
                            thing we can honour: a reply from a human. */}
                        <SupportLink label="Email support" variant="outline" />
                    </div>
                </Panel>
            </div>
        </div>
    );
}
