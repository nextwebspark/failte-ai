/**
 * Wording and forwarding codes for "How callers reach your agent".
 *
 * The codes are the standard GSM call-forwarding codes. Most mobile networks
 * accept them, but not every network or phone does, so the screen always says
 * "on most mobiles" and points landlines at their phone company instead.
 */

export type SetupMethod = "keep_existing" | "new_number" | "mobile";
export type ForwardWhen = "no_answer" | "busy" | "all" | "outside_hours";

export const SETUP_METHODS: { value: SetupMethod; title: string; body: string; badge?: string }[] = [
    {
        value: "keep_existing",
        title: "Keep my existing number",
        body: "Callers ring the number they already know. You forward it to your agent.",
        badge: "Most common",
    },
    {
        value: "new_number",
        title: "Get a new number",
        body: "A new local number just for your agent. LightMove provides it, or use your own phone provider account.",
    },
    {
        value: "mobile",
        title: "My mobile is my business number",
        body: "Forward your mobile to the agent when you’re busy or don’t answer.",
    },
];

export const FORWARD_OPTIONS: { value: ForwardWhen; title: string; body: string; code?: string }[] = [
    {
        value: "no_answer",
        title: "When we don’t answer",
        body: "Your phone rings first; after about 20 seconds your agent picks up.",
        code: "**61*",
    },
    { value: "busy", title: "When we’re busy", body: "Only when the line is engaged.", code: "**67*" },
    { value: "all", title: "All calls", body: "Your agent answers every call.", code: "**21*" },
    {
        value: "outside_hours",
        title: "Outside opening hours",
        body: "Set a timed forward with your phone company; not every provider offers it.",
    },
];

/** Cancels every forward on most mobiles. */
export const UNDO_CODE = "##002#";

/**
 * The code to dial on a mobile to forward calls to `agentNumber`, or null when
 * there is no code for it (outside opening hours is set up with the phone
 * company). `agentNumber` should be E.164, e.g. +35315550142.
 */
export function forwardingCode(agentNumber: string, when: ForwardWhen): string | null {
    const number = agentNumber.replace(/[\s()-]/g, "");
    if (!isPublicNumber(number)) return null;
    switch (when) {
        case "no_answer":
            return `**61*${number}**20#`;
        case "busy":
            return `**67*${number}#`;
        case "all":
            return `**21*${number}#`;
        case "outside_hours":
            return null;
    }
}

/**
 * A full phone number anyone can ring (E.164, e.g. +35315550142). An extension
 * on the customer's own phone system ("7000") or a SIP address is not: mobiles
 * and landlines can't forward to it.
 */
export function isPublicNumber(address: string): boolean {
    return /^\+[1-9]\d{6,14}$/.test(address.replace(/[\s()-]/g, ""));
}

/**
 * An Irish E.164 number spaced the way people write it (+353 1 555 0142,
 * +353 87 123 4567). Anything else is returned as it is.
 */
export function displayNumber(e164: string): string {
    const match = /^\+353(\d+)$/.exec(e164);
    if (!match) return e164;
    const rest = match[1];
    // Dublin is the one single-digit area code; mobiles and the rest use two.
    const areaLength = rest.startsWith("1") ? 1 : 2;
    const area = rest.slice(0, areaLength);
    const local = rest.slice(areaLength);
    const split = local.length > 4 ? local.length - 4 : local.length;
    return ["+353", area, local.slice(0, split), local.slice(split)].filter(Boolean).join(" ");
}
