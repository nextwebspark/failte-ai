"use client";

import Link from 'next/link';

import { SupportLink } from '@/components/SupportLink';
import { Button } from '@/components/ui/button';
import { Panel, PanelDescription, PanelTitle } from '@/components/ui/panel';
import { SectionHeading, SectionHint } from '@/components/ui/section-heading';
import { useAuth } from '@/lib/auth';

export default function OverviewPage() {
    const { user, provider } = useAuth();
    const isOSSMode = provider !== 'stack';

    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mx-auto max-w-4xl animate-fade-up">
                {/* Welcome */}
                <div className="mb-8">
                    <h1 className="text-2xl font-bold tracking-tight">
                        {isOSSMode ? (
                            "Welcome to Failte AI"
                        ) : (
                            `Welcome${user?.displayName ? `, ${user.displayName.split(' ')[0]}` : ''}!`
                        )}
                    </h1>
                    <p className="mt-1.5 font-mono text-[12.5px] text-ink-3">
                        Get started with building voice AI workflows
                    </p>
                </div>

                {/* Quick actions — the canvas "Get started" panels */}
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <Panel accent="sky">
                        <PanelTitle as="h2">Create and Manage your Voice Agents</PanelTitle>
                        <PanelDescription>
                            Build powerful AI Voice Agents with our visual editor
                        </PanelDescription>
                        <Button asChild size="sm" className="mt-4">
                            <Link href="/workflow">
                                Go to Agents
                            </Link>
                        </Button>
                    </Panel>

                    <Panel>
                        <PanelTitle as="h2">Configure Services</PanelTitle>
                        <PanelDescription>
                            Set up your AI services like LLM, TTS, and STT providers
                        </PanelDescription>
                        <Button asChild size="sm" variant="soft" className="mt-4">
                            <Link href="/model-configurations">
                                Configure Models
                            </Link>
                        </Button>
                    </Panel>
                </div>

                {/* Resources */}
                <SectionHeading className="mt-8" action={<SectionHint>Get help from the team</SectionHint>}>
                    Resources
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
