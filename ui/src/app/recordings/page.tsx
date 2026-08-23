"use client";

import { Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { PageActions } from "@/components/layout/PageActionsSlot";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";

import RecordingsList from "./RecordingsList";
import { RecordingsUploadDialog } from "./RecordingsUploadDialog";

export default function RecordingsPage() {
    const { user, redirectToLogin, loading } = useAuth();
    const [isUploadOpen, setIsUploadOpen] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);

    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    if (loading || !user) {
        return (
            <div className="page-body">
                <div className="space-y-4">
                    <Skeleton className="h-12 w-64" />
                    <Skeleton className="h-64 w-full" />
                </div>
            </div>
        );
    }

    return (
        <div className="page-body">
            {/* Screen name, strapline and primary action are rendered by the
                app header (AppTopBar) — see PageActions. */}
            <PageActions>
                <Button onClick={() => setIsUploadOpen(true)}>
                    <Upload className="w-4 h-4" />
                    Upload recording
                </Button>
            </PageActions>

            <Card>
                <CardHeader>
                    <CardTitle>All Recordings</CardTitle>
                    <CardDescription>
                        Shared across every agent in your organization. Use{" "}
                        <code className="rounded bg-muted px-1 text-xs">@</code> in prompt fields to
                        insert them, or as transition messages in tool calls.
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <RecordingsList refreshKey={refreshKey} />
                </CardContent>
            </Card>

            <RecordingsUploadDialog
                open={isUploadOpen}
                onOpenChange={setIsUploadOpen}
                onUploadComplete={() => setRefreshKey((k) => k + 1)}
            />
        </div>
    );
}
