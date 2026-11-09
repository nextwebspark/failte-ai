"use client";

import { PhoneCall } from "lucide-react";
import { useEffect, useState } from "react";

import { getCallLimitApiV1OrganizationsCallLimitGet } from "@/client/sdk.gen";
import { ContactSupportLink } from "@/components/help/ContactSupportLink";
import { SettingsSection } from "@/components/settings/SettingsLayout";

/**
 * Settings > General: how many calls the business's agents can take at the
 * same time. Read only: LightMove sets it, so the owner is pointed at
 * Contact support for more.
 */
export function CallLimitCard() {
    const [limit, setLimit] = useState<number | null | undefined>(undefined);

    useEffect(() => {
        let cancelled = false;
        void (async () => {
            try {
                const res = await getCallLimitApiV1OrganizationsCallLimitGet();
                if (!cancelled) setLimit(res.data?.calls_at_once ?? null);
            } catch {
                if (!cancelled) setLimit(null);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    return (
        <SettingsSection
            id="call-limit"
            icon={PhoneCall}
            title="Calls at once"
            description="How many callers your agents can talk to at the same time."
        >
            <div className="flex flex-col gap-2 px-[18px] py-4">
                <p className="text-body text-foreground">
                    Calls at once:{" "}
                    <span className="font-display text-[20px] font-semibold tabular-nums" data-testid="calls-at-once">
                        {limit === undefined ? "…" : limit === null ? "Couldn't load" : limit}
                    </span>
                </p>
                <p className="text-caption leading-relaxed text-ink-3">
                    When every line is in use, the next caller is put through to your team, asked to leave a voicemail, or
                    told the lines are busy. You choose which for each agent under &ldquo;Pass calls to your team&rdquo;.
                    These callers show up in Follow-ups as &ldquo;Lines were busy&rdquo;.
                </p>
                <p className="text-caption">
                    <ContactSupportLink>Need more? Contact us</ContactSupportLink>
                </p>
            </div>
        </SettingsSection>
    );
}
