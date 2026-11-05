// Product areas that are built but not offered yet. Off hides the area in the
// app: its nav row and pages (middleware sends them to Overview), and the
// controls that lead to it elsewhere. The API, stored data and running calls
// are not affected, so switching an area back on is a one-line change here.

export const FEATURES = {
    /** Outbound calls in bulk to a contact list (/campaigns). */
    campaigns: false,
    /** Playbooks agents load mid-call (/skills, and the pickers on agent steps). */
    skills: false,
} as const;

export type Feature = keyof typeof FEATURES;

export function isFeatureEnabled(feature: Feature): boolean {
    return FEATURES[feature];
}

/** Where each area's pages live. */
const AREA_ROUTES: Record<Feature, string> = {
    campaigns: "/campaigns",
    skills: "/skills",
};

/** A page of an area that is switched off (the area's root or anything under it). */
export function isSwitchedOffRoute(pathname: string): boolean {
    return (Object.keys(AREA_ROUTES) as Feature[]).some((feature) => {
        const root = AREA_ROUTES[feature];
        return !FEATURES[feature] && (pathname === root || pathname.startsWith(`${root}/`));
    });
}
