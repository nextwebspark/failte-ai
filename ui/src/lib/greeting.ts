/** Friendly greetings for the signed-in person. Pure, so they're easy to test. */

interface NamedUser {
    displayName?: string | null;
    name?: string | null;
    email?: string | null;
}

/** "Naveen" from "Naveen Ennis", else the name before "@" ("mary.byrne" -> "Mary"), else "". */
export function firstName(user: NamedUser | null | undefined): string {
    const full = (user?.displayName || user?.name || '').trim();
    if (full) return full.split(/\s+/)[0];
    const local = (user?.email || '').split('@')[0].split(/[._+-]/)[0];
    return local ? local.charAt(0).toUpperCase() + local.slice(1) : '';
}

/** "Good morning" before 12, "Good afternoon" before 18, else "Good evening". */
export function timeOfDayGreeting(now: Date = new Date()): string {
    const hour = now.getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
}

/** "Good morning, Naveen" or just "Good morning" without a name. */
export function greetingFor(user: NamedUser | null | undefined, now: Date = new Date()): string {
    const name = firstName(user);
    return name ? `${timeOfDayGreeting(now)}, ${name}` : timeOfDayGreeting(now);
}

/** Set by sign-in, read once by the app shell to show a welcome toast. */
export const JUST_SIGNED_IN_KEY = 'lm-just-signed-in';
