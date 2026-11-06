"use client";

import { Plus } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';

import { getCampaignsApiV1CampaignGet } from '@/client/sdk.gen';
import type { CampaignsResponse } from '@/client/types.gen';
import { PageActions } from '@/components/layout/PageActionsSlot';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { useOrgConfig } from '@/context/OrgConfigContext';
import { useOrganizationTimezone } from '@/hooks/useOrganizationTimezone';
import { useAuth } from '@/lib/auth';
import { formatDate } from '@/lib/dateTime';
import { ROW_LINK } from '@/lib/rowLink';

const LOAD_FAILED = "Couldn't load your campaigns. Please try again.";

export default function CampaignsPage() {
    const { user, getAccessToken, redirectToLogin, loading } = useAuth();
    const organizationTimezone = useOrganizationTimezone();
    const { can } = useOrgConfig();
    const canCreate = can('campaigns:write');

    const [campaignsData, setCampaignsData] = useState<CampaignsResponse | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const hasFetched = useRef(false);

    // Redirect if not authenticated
    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    const fetchCampaigns = useCallback(async () => {
        setIsLoading(true);
        setLoadError(null);
        try {
            const accessToken = await getAccessToken();
            const response = await getCampaignsApiV1CampaignGet({
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                }
            });

            if (response.data) {
                setCampaignsData(response.data);
            } else {
                setLoadError(LOAD_FAILED);
            }
        } catch (error) {
            console.error('Failed to fetch campaigns:', error);
            setLoadError(LOAD_FAILED);
        } finally {
            setIsLoading(false);
        }
    }, [getAccessToken]);

    // Fetch campaigns once when user is ready
    useEffect(() => {
        if (loading || !user || hasFetched.current) {
            return;
        }
        hasFetched.current = true;
        void fetchCampaigns();
    }, [loading, user, fetchCampaigns]);

    const getStateBadgeVariant = (state: string) => {
        switch (state) {
            case 'created':
                return 'secondary';
            case 'running':
                return 'default';
            case 'paused':
                return 'outline';
            case 'completed':
                return 'secondary';
            case 'failed':
                return 'destructive';
            default:
                return 'secondary';
        }
    };

    return (
        <div className="page-body space-y-6">
            {/* Screen name, strapline and primary action are rendered by the
                app header (AppTopBar) — see PageActions. */}
            {canCreate && (
                <PageActions>
                    <Button asChild size="toolbar">
                        <Link href="/campaigns/new">
                            <Plus className="h-4 w-4" aria-hidden />
                            New campaign
                        </Link>
                    </Button>
                </PageActions>
            )}

            <Card>
                <CardHeader>
                    <CardTitle>All Campaigns</CardTitle>
                    <CardDescription>
                        View and manage your campaigns
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    {isLoading ? (
                        <div className="animate-pulse space-y-3">
                            {[...Array(5)].map((_, i) => (
                                <div key={i} className="h-12 bg-muted rounded"></div>
                            ))}
                        </div>
                    ) : loadError ? (
                        <div role="alert" className="flex flex-col items-start gap-3 py-4">
                            <p className="text-sm text-destructive">{loadError}</p>
                            <Button size="sm" variant="outline" onClick={() => void fetchCampaigns()}>
                                Try again
                            </Button>
                        </div>
                    ) : campaignsData && campaignsData.campaigns.length > 0 ? (
                        <div className="overflow-x-auto">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>ID</TableHead>
                                        <TableHead>Name</TableHead>
                                        <TableHead>Agent</TableHead>
                                        <TableHead>State</TableHead>
                                        <TableHead>Progress</TableHead>
                                        <TableHead>Created</TableHead>
                                        <TableHead className="text-right">Action</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {campaignsData.campaigns.map((campaign) => (
                                        <TableRow
                                            key={campaign.id}
                                            // The name is a real link stretched over the row.
                                            className="relative hover:bg-muted/50 focus-within:bg-muted/50"
                                        >
                                            <TableCell>{campaign.id}</TableCell>
                                            <TableCell className="font-medium">
                                                <Link href={`/campaigns/${campaign.id}`} className={ROW_LINK}>
                                                    {campaign.name}
                                                </Link>
                                            </TableCell>
                                            <TableCell>{campaign.workflow_name}{(campaign.traffic_split?.variants.length ?? 1) > 1 && <span className="text-muted-foreground"> +{(campaign.traffic_split?.variants.length ?? 1) - 1}</span>}</TableCell>
                                            <TableCell>
                                                <Badge variant={getStateBadgeVariant(campaign.state)}>
                                                    {campaign.state}
                                                </Badge>
                                            </TableCell>
                                            <TableCell>
                                                {campaign.executed_count} / {campaign.total_queued_count}
                                            </TableCell>
                                            <TableCell>
                                                {formatDate(campaign.created_at, organizationTimezone)}
                                            </TableCell>
                                            <TableCell className="text-right">
                                                {/* A visual cue only: the row's link opens the campaign. */}
                                                <span
                                                    aria-hidden
                                                    className="inline-flex h-8 items-center rounded-md border border-input px-3 text-sm font-medium"
                                                >
                                                    View
                                                </span>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    ) : (
                        <div className="text-center py-8">
                            <p className="mb-4">No campaigns yet</p>
                            {canCreate && (
                                <Button asChild variant="outline">
                                    <Link href="/campaigns/new">
                                        <Plus className="h-4 w-4 mr-2" aria-hidden />
                                        Create your first campaign
                                    </Link>
                                </Button>
                            )}
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}
