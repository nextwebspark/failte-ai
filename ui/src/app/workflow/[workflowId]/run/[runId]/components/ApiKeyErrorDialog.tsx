import { AlertCircle, CreditCard, Key } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useAppConfig } from "@/context/AppConfigContext";

interface ApiKeyErrorDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    error: string | null;
    errorCode: string | null;
    onNavigateToBilling: () => void;
    onNavigateToDevelopers: () => void;
    onNavigateToModelConfig: () => void;
}

export const ApiKeyErrorDialog = ({
    open,
    onOpenChange,
    error,
    errorCode,
    onNavigateToBilling,
    onNavigateToDevelopers,
    onNavigateToModelConfig,
}: ApiKeyErrorDialogProps) => {
    const isBillingCreditsError = errorCode === 'insufficient_credits';
    const isServiceKeyOrgMismatch = errorCode === 'service_key_org_mismatch';
    const isQuotaError = isBillingCreditsError || errorCode === 'quota_exceeded';
    // On platform models customers hold no keys, so there is nothing for them
    // to fix in settings: a model-service failure is ours.
    const platformModels = Boolean(useAppConfig().config?.platformModelsEnabled);
    const isPlatformServiceError = platformModels && !isQuotaError && !isServiceKeyOrgMismatch;

    const title = isQuotaError
        ? "Insufficient Credits"
        : isServiceKeyOrgMismatch
            ? "Service Token Account Mismatch"
            : isPlatformServiceError
                ? "Voice service unavailable"
                : "API Configuration Error";
    const icon = isQuotaError ? <CreditCard className="h-5 w-5 text-orange-500" /> : <Key className="h-5 w-5 text-red-500" />;
    const buttonText = isBillingCreditsError
        ? "Go to Billing"
        : isServiceKeyOrgMismatch
            ? "Go to Developers"
            : "Go to Model Configurations";
    const onNavigate = isBillingCreditsError
        ? onNavigateToBilling
        : isServiceKeyOrgMismatch
            ? onNavigateToDevelopers
            : onNavigateToModelConfig;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        {icon}
                        {title}
                    </DialogTitle>
                    <DialogDescription className="pt-3" asChild>
                        <div className="flex items-start gap-2">
                            <AlertCircle className="h-4 w-4 text-muted-foreground mt-0.5 flex-shrink-0" />
                            <div className="text-sm space-y-1">
                                <p className="font-medium text-foreground">
                                    {isPlatformServiceError
                                        ? "We couldn't start the voice service. Please try again or contact support."
                                        : error}
                                </p>
                                {isBillingCreditsError && (
                                    <p className="text-muted-foreground">
                                        Purchase credits from Billing to continue using managed models.
                                    </p>
                                )}
                            </div>
                        </div>
                    </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        {isPlatformServiceError ? "Close" : "Cancel"}
                    </Button>
                    {!isPlatformServiceError && (
                        <Button onClick={onNavigate}>
                            {buttonText}
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
