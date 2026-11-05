import { redirect } from "next/navigation";

import { getServerAccessToken,getServerAuthProvider,getServerUser } from "@/lib/auth/server";
import logger from '@/lib/logger';
import { getRedirectUrl } from "@/lib/utils";

export const dynamic = 'force-dynamic';

export default async function Home() {
  logger.debug('[HomePage] Starting Home page render');
  const authProvider = await getServerAuthProvider();
  logger.debug('[HomePage] Auth provider:', authProvider);

  // Local/OSS provider: /after-sign-in picks the landing page by role and
  // agents, so this page and the sign-in flow can't disagree.
  if (authProvider === 'local') {
    let accessToken: string | null = null;
    try {
      accessToken = await getServerAccessToken();
    } catch (error) {
      logger.error('[HomePage] Could not read the local session:', error);
    }
    redirect(accessToken ? '/after-sign-in' : '/auth/login');
  }

  logger.debug('[HomePage] Getting server user...');
  const user = await getServerUser();

  logger.debug('[HomePage] Server user result:', {
    hasUser: !!user,
    userId: user?.id,
    authProvider
  });

  if (user) {
    try {
      // For Stack provider, get the token and permissions
      if (authProvider === 'stack' && 'getAuthJson' in user) {
        logger.debug('[HomePage] Getting auth token from Stack user...');
        const token = await user.getAuthJson();
        logger.debug('[HomePage] Got auth token:', { hasToken: !!token?.accessToken });
        const permissions = 'listPermissions' in user && 'selectedTeam' in user
          ? await user.listPermissions(user.selectedTeam!) ?? []
          : [];
        logger.debug('[HomePage] Got permissions:', { count: permissions.length });
        logger.debug('[HomePage] Getting redirect URL...');
        const redirectUrl = await getRedirectUrl(token?.accessToken ?? "", permissions);
        logger.debug('[HomePage] Redirecting to:', redirectUrl);
        redirect(redirectUrl);
      }
    } catch (error) {
      // If it's a Next.js redirect, let it through
      if (error instanceof Error && 'digest' in error &&
          typeof error.digest === 'string' && error.digest.startsWith('NEXT_REDIRECT')) {
        throw error;
      }
      // Only catch actual API errors
      console.error("API unavailable, showing sign-in:", error);
      // Show sign-in page if API is unavailable
    }
  }

  logger.debug('[HomePage] Redirecting unauthenticated Stack user to /handler/sign-in');
  redirect('/handler/sign-in');
}
