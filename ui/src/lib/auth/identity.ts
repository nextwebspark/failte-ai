import type { AuthUser } from './types';

/** The signed-in user's address (Stack users have `primaryEmail`, local users `email`). */
export function signedInEmail(user: AuthUser | null): string | null {
  if (!user) return null;
  return 'primaryEmail' in user ? user.primaryEmail : (user.email ?? null);
}
