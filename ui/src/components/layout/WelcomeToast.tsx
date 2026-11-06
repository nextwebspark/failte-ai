"use client";

import { useEffect } from "react";
import { toast } from "sonner";

import { BRAND } from "@/config/brand";
import { useAuth } from "@/lib/auth";
import { firstName, JUST_SIGNED_IN_KEY, welcomeKindOf, welcomeMessage } from "@/lib/greeting";

/**
 * A warm welcome once, right after signing in, on whichever page the person
 * lands: "Welcome to LightMove" after signing up, "Welcome back" after that. Sign-in sets a flag in sessionStorage; this reads and clears it.
 */
export function WelcomeToast() {
    const { user, isAuthenticated, loading } = useAuth();

    useEffect(() => {
        if (loading || !isAuthenticated) return;
        let kind = null;
        try {
            kind = welcomeKindOf(sessionStorage.getItem(JUST_SIGNED_IN_KEY));
            if (kind) sessionStorage.removeItem(JUST_SIGNED_IN_KEY);
        } catch {
            return;
        }
        if (!kind) return;
        const name = firstName(user as { displayName?: string; name?: string; email?: string });
        const { title, description } = welcomeMessage(kind, name, BRAND.name);
        toast.success(title, { description, duration: kind === "new" ? 8000 : 5000 });
    }, [user, isAuthenticated, loading]);

    return null;
}
