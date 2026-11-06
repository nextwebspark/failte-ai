"use client";

import { Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { PageActions } from "@/components/layout/PageActionsSlot";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/lib/auth";

import RecordingsList from "./RecordingsList";
import { RecordingsUploadDialog } from "./RecordingsUploadDialog";
import TtsCacheList from "./TtsCacheList";

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
        return <PageSkeleton variant="list" />;
    }

    return (
        <div className="page-body">
            <PageHeader
                title="Prompt audio"
                description="Greetings and messages recorded in your own voice, for your agents to play on calls."
            />
            {/* The primary action sits in the app header — see PageActions. */}
            <PageActions>
                <Button size="toolbar" onClick={() => setIsUploadOpen(true)}>
                    <Upload className="w-4 h-4" />
                    Upload recording
                </Button>
            </PageActions>

            <Tabs defaultValue="recordings" key={`${user.id}:${"selectedTeam" in user ? user.selectedTeam?.id : user.organizationId}`}>
                <TabsList className="mb-4">
                    <TabsTrigger value="recordings">Your recordings</TabsTrigger>
                    <TabsTrigger value="tts-cache">Saved speech</TabsTrigger>
                </TabsList>
                <TabsContent value="recordings">
                    <Card>
                        <CardHeader>
                            <CardTitle as="h2">All recordings</CardTitle>
                            <CardDescription>
                                Every agent can use these. Type{" "}
                                <code className="rounded bg-panel-2 px-1 font-mono text-xs">@</code> in an agent&apos;s
                                instructions to add one, or pick one as the message a tool plays.
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            <RecordingsList refreshKey={refreshKey} onUploadClick={() => setIsUploadOpen(true)} />
                        </CardContent>
                    </Card>
                </TabsContent>
                <TabsContent value="tts-cache">
                    <Card>
                        <CardHeader>
                            <CardTitle as="h2">Saved speech</CardTitle>
                            <CardDescription>
                                Phrases your agents have already said, kept so they can be reused quickly. Remove one to have it spoken fresh next time.
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            <TtsCacheList />
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>

            <RecordingsUploadDialog
                open={isUploadOpen}
                onOpenChange={setIsUploadOpen}
                onUploadComplete={() => setRefreshKey((k) => k + 1)}
            />
        </div>
    );
}
