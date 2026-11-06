"use client";

import { Info, Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { PageActions } from "@/components/layout/PageActionsSlot";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { PageHeader } from "@/components/ui/page-header";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { useAppConfig } from "@/context/AppConfigContext";
import { useAuth } from "@/lib/auth";

import DocumentList from "./DocumentList";
import DocumentUpload from "./DocumentUpload";

export default function FilesPage() {
    const { user, redirectToLogin, loading } = useAuth();
    const [refreshKey, setRefreshKey] = useState(0);
    const [isUploadOpen, setIsUploadOpen] = useState(false);
    // Documents are parsed and chunked on the backend itself; uploads are off
    // only if the backend reports it can't process them.
    const { config } = useAppConfig();
    const processingAvailable = Boolean(config?.documentProcessingEnabled);

    // Redirect if not authenticated
    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    const handleUploadSuccess = () => {
        setRefreshKey(prev => prev + 1);
        setIsUploadOpen(false);
    };

    if (loading || !user) {
        return <PageSkeleton variant="list" />;
    }

    return (
        <div className="page-body">
            <PageHeader
                title="Files"
                description="Documents your agents can look things up in, like a menu, price list or FAQs. Every agent can use them."
            />
            {/* The primary action sits in the app header — see PageActions. */}
            {processingAvailable && (
                <PageActions>
                    <Button size="toolbar" onClick={() => setIsUploadOpen(true)}>
                        <Upload className="w-4 h-4" />
                        Upload document
                    </Button>
                </PageActions>
            )}

            {config && !processingAvailable && (
                <div className="mb-6 flex gap-3 rounded-lg border border-line bg-panel-2 p-4">
                    <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-ink-3" aria-hidden />
                    <p className="text-sm text-ink-2">
                        Document processing isn&apos;t available yet, so new documents
                        can&apos;t be uploaded.
                    </p>
                </div>
            )}

            <Card>
                <CardContent className="p-4 sm:p-6">
                    <DocumentList
                        refreshTrigger={refreshKey}
                        onUploadClick={processingAvailable ? () => setIsUploadOpen(true) : undefined}
                    />
                </CardContent>
            </Card>

            <Dialog open={processingAvailable && isUploadOpen} onOpenChange={setIsUploadOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Upload a document</DialogTitle>
                        <DialogDescription>
                            Add a PDF or document your agents can look things up in.
                        </DialogDescription>
                    </DialogHeader>
                    <DocumentUpload onUploadSuccess={handleUploadSuccess} />
                </DialogContent>
            </Dialog>
        </div>
    );
}
