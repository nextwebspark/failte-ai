'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { createWorkflowFromTemplateApiV1WorkflowCreateTemplatePost } from '@/client/sdk.gen';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useAppConfig } from "@/context/AppConfigContext";
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';

const CREATE_WORKFLOW_FALLBACK_ERROR = 'Failed to create agent. Please try again.';

export default function CreateWorkflowPage() {
    const router = useRouter();
    const platformModels = Boolean(useAppConfig().config?.platformModelsEnabled);
    const { user, getAccessToken } = useAuth();
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [showSuccessModal, setShowSuccessModal] = useState(false);
    const [workflowId, setWorkflowId] = useState<string | null>(null);

    const [callType, setCallType] = useState<'inbound' | 'outbound'>('inbound');
    const [useCase, setUseCase] = useState('');
    const [activityDescription, setActivityDescription] = useState('');

    const handleCreateWorkflow = async () => {
        if (!useCase || !activityDescription) {
            setError('Please fill in all fields');
            return;
        }

        if (!user) {
            setError('You must be logged in to create an agent');
            return;
        }

        setIsLoading(true);
        setError(null);

        try {
            const accessToken = await getAccessToken();

            // Call the API to create workflow from template
            const response = await createWorkflowFromTemplateApiV1WorkflowCreateTemplatePost({
                body: {
                    call_type: callType,
                    use_case: useCase,
                    activity_description: activityDescription,
                },
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });

            if (response.data?.id) {
                setWorkflowId(String(response.data.id));
                setShowSuccessModal(true);
            } else {
                setError(detailFromError(response.error, CREATE_WORKFLOW_FALLBACK_ERROR));
                logger.error(`Error creating workflow: ${JSON.stringify(response.error)}`);
            }
        } catch (err) {
            setError(CREATE_WORKFLOW_FALLBACK_ERROR);
            logger.error(`Error creating workflow: ${err}`);
        } finally {
            setIsLoading(false);
        }
    };

    const handleModalContinue = () => {
        if (!workflowId) return;
        router.push(`/workflow/${workflowId}?onboarding=web_call`);
    };

    return (
        <div className="page-body">
            <div className="max-w-2xl">
                {/* The screen name lives in the app header (AppTopBar). */}
                <p className="mb-6 text-sm text-ink-2">
                    Tell us about your use case and we&apos;ll create a customized voice agent for you
                </p>

                <Card>
                    <CardHeader>
                        <CardTitle>Agent details</CardTitle>
                        <CardDescription>
                            Configure your voice agent settings
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <div className="space-y-2">
                            <Label htmlFor="call-type">Call type</Label>
                            <Select value={callType} onValueChange={(value) => setCallType(value as 'inbound' | 'outbound')}>
                                <SelectTrigger id="call-type">
                                    <SelectValue placeholder="Select type" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="inbound">
                                        Inbound (Users call AI)
                                    </SelectItem>
                                    <SelectItem value="outbound">
                                        Outbound (AI calls users)
                                    </SelectItem>
                                </SelectContent>
                            </Select>
                            <p className="text-sm text-muted-foreground">
                                Choose whether users will call your AI or your AI will call users
                            </p>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="use-case">Use case</Label>
                            <Input
                                id="use-case"
                                placeholder="e.g. lead qualification, HR screening, customer support"
                                value={useCase}
                                maxLength={200}
                                onChange={(e) => setUseCase(e.target.value)}
                            />
                            <p className="text-sm text-muted-foreground">
                                Describe the primary purpose of your voice agent
                            </p>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="activity-description">What should it do?</Label>
                            <Textarea
                                id="activity-description"
                                placeholder="Describe briefly what your voice agent will do (e.g., Qualify leads for real estate, Screen candidates for roles, Handle customer support). This will be a prompt to an LLM."
                                value={activityDescription}
                                maxLength={4000}
                                onChange={(e) => setActivityDescription(e.target.value)}
                                className="min-h-[100px]"
                            />
                            <p className="text-sm text-muted-foreground">
                                This description will be used to generate the AI prompt for your voice agent
                            </p>
                        </div>

                        {error && (
                            <p className="text-sm text-danger">{error}</p>
                        )}

                        <div className="pt-4">
                            <Button
                                onClick={handleCreateWorkflow}
                                disabled={isLoading || !useCase || !activityDescription}
                                className="w-full"
                            >
                                {isLoading ? 'Creating…' : 'Create agent'}
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            </div>

            {/* Loading Overlay */}
            {isLoading && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
                    <Card className="w-full max-w-md p-8">
                        <div className="flex flex-col items-center space-y-6">
                            {/* Animated spinner */}
                            <div className="relative">
                                <div className="w-16 h-16 border-4 border-muted rounded-full"></div>
                                <div className="absolute top-0 left-0 w-16 h-16 border-4 border-transparent border-t-primary rounded-full animate-spin"></div>
                            </div>

                            <div className="text-center space-y-2">
                                <h3 className="text-lg font-semibold">
                                    Creating your agent
                                </h3>
                                <p className="text-sm text-muted-foreground max-w-xs">
                                    We&apos;re setting up your voice agent with your specifications. This will just take a moment...
                                </p>
                            </div>
                        </div>
                    </Card>
                </div>
            )}

            {/* Success Modal */}
            <Dialog open={showSuccessModal} onOpenChange={setShowSuccessModal}>
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <svg className="w-5 h-5 text-ok" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            Agent created
                        </DialogTitle>
                        <DialogDescription asChild>
                            <div className="mt-4 space-y-3">
                                <p>
                                    We drafted an agent for your use case, with some sample data and actions.
                                </p>
                                <p>
                                    The agent is set to speak English with an American accent.
                                    {platformModels && " You can change its voice and language under Models & voice."}
                                </p>
                                <p>
                                    Next, test it in the editor, then adjust it to suit your use case.
                                </p>
                            </div>
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter className="mt-6">
                        <Button
                            onClick={handleModalContinue}
                            className="w-full"
                        >
                            Open and test agent
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
