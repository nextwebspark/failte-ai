const ADDRESS = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * A plausible email address: something@domain.tld. The server validates
 * properly; this keeps obviously unusable values (admin@localhost) out of
 * forms and prefills.
 */
export function isEmailAddress(value: string): boolean {
    return ADDRESS.test(value);
}
