"use client";

import { useEffect } from "react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { firstName, JUST_SIGNED_IN_KEY } from "@/lib/greeting";

/**
 * A warm "Welcome back" once, right after signing in, on whichever page the
 * person lands. Sign-in sets a flag in sessionStorage; this reads and clears it.
 */
export function WelcomeToast() {
    const { user, isAuthenticated, loading } = useAuth();

    useEffect(() => {
        if (loading || !isAuthenticated) return;
        let flagged = false;
        try {
            flagged = sessionStorage.getItem(JUST_SIGNED_IN_KEY) === "1";
            if (flagged) sessionStorage.removeItem(JUST_SIGNED_IN_KEY);
        } catch {
            return;
        }
        if (!flagged) return;
        const name = firstName(user as { displayName?: string; name?: string; email?: string });
        toast.success(name ? `Welcome back, ${name}` : "Welcome back", {
            description: "Good to see you. Your calls and bookings are up to date.",
        });
    }, [user, isAuthenticated, loading]);

    return null;
}
