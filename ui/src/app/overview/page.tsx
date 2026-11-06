"use client";

import { HomeDashboard } from '@/components/dashboard/HomeDashboard';
import { useAuth } from '@/lib/auth';
import { greetingFor } from '@/lib/greeting';

/**
 * Home: where every member lands. How the phone agent did today, what needs
 * the owner, and when people called, all counted from stored calls.
 */
export default function OverviewPage() {
    const { user } = useAuth();
    return <HomeDashboard heading={greetingFor(user)} />;
}
