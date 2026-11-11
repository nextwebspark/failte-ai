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

/** "new" just signed up, "back" returning, "hello" unknown (e.g. Google). */
export type WelcomeKind = 'new' | 'back' | 'hello';

/** Reads the flag sign-in left; older builds stored "1", meaning "back". */
export function welcomeKindOf(flag: string | null): WelcomeKind | null {
    if (flag === 'new' || flag === 'back' || flag === 'hello') return flag;
    return flag === '1' ? 'back' : null;
}

/** The toast after signing in, warmest for someone brand new. */
export function welcomeMessage(
    kind: WelcomeKind,
    name: string,
    brand: string,
): { title: string; description: string } {
    const to = name ? `, ${name}` : '';
    if (kind === 'new') {
        return {
            title: `Welcome to ${brand}${to}!`,
            description: "Your workspace is ready. Let's set up your phone agent: it takes about 5 minutes.",
        };
    }
    if (kind === 'hello') {
        return { title: `Welcome${to}`, description: 'Good to see you.' };
    }
    return {
        title: `Welcome back${to}`,
        description: 'Good to see you. Your calls and bookings are up to date.',
    };
}
