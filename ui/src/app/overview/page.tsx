"use client";

import { ArrowRight, CalendarCheck, Cpu, FileText, GitBranch, type LucideIcon, Plus, TrendingUp } from 'lucide-react';
import Link from 'next/link';

import { SupportLink } from '@/components/SupportLink';
import { Panel, PanelDescription, PanelTitle } from '@/components/ui/panel';
import { SectionHeading, SectionHint } from '@/components/ui/section-heading';
import { BRAND } from "@/config/brand";
import { useOrgConfig } from '@/context/OrgConfigContext';
import { useAuth } from '@/lib/auth';
import type { Permission } from '@/lib/auth/roles';
import { greetingFor } from '@/lib/greeting';

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
                <Panel className="h-full bg-panel transition-all duration-150 group-hover:-translate-y-0.5 group-hover:border-brand/50 group-hover:shadow-md motion-reduce:transition-none motion-reduce:group-hover:translate-y-0">
                    <div className="flex items-start gap-3.5">
                        <span className="grid size-10 flex-none place-items-center rounded-lg bg-brand-dim text-brand" aria-hidden>
                            <Icon className="size-5" />
                        </span>
                        <div className="min-w-0 flex-1">
                            <PanelTitle as="h3">{shortcut.title}</PanelTitle>
                            <PanelDescription>{shortcut.description}</PanelDescription>
                        </div>
                        <ArrowRight
                            className="mt-1 size-4 flex-none text-ink-3 transition-transform group-hover:translate-x-0.5 group-hover:text-brand motion-reduce:transition-none"
                            aria-hidden
                        />
                    </div>
                </Panel>
            </Link>
        </li>
    );
}

export default function OverviewPage() {
    const { user } = useAuth();
    const { can } = useOrgConfig();

    const daily = DAILY.filter((s) => can(s.requires));
    const setup = SETUP.filter((s) => can(s.requires));

    return (
        <div className="page-body">
            <div className="max-w-4xl animate-fade-up">
                {/* Welcome */}
                <div className="mb-8 rounded-xl border border-line bg-gradient-to-br from-brand-dim via-panel to-panel px-6 py-6">
                    <h1 className="text-[26px] font-bold tracking-tight">{greetingFor(user)}</h1>
                    <p className="mt-1.5 max-w-xl text-[15px] text-ink-2">
                        Welcome to {BRAND.name}. Here&apos;s everything for your phone agent in one place.
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
