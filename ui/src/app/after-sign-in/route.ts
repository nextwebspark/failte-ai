import {
    getCurrentOrganizationContextApiV1OrganizationsContextGet,
    getWorkflowCountApiV1WorkflowCountGet,
} from "@/client/sdk.gen";
import { getServerAccessToken, getServerAuthProvider, getServerUser } from "@/lib/auth/server";
import logger from '@/lib/logger';
import { getRedirectUrl } from "@/lib/utils";

export const dynamic = 'force-dynamic';

/**
 * Where a user lands after signing in. A route handler, not a page: a page
 * streams the root loading UI (an empty screen) before its redirect, while
 * this answers with a plain 307, so the browser goes straight from the sign-in
 * screen (its button still "Signing you in...") to the destination.
 */
export async function GET(): Promise<Response> {
    return new Response(null, {
        status: 307,
        // Relative, so it stays on the public origin behind a reverse proxy.
        headers: { Location: await afterSignInPath(), 'Cache-Control': 'no-store' },
    });
}

async function afterSignInPath(): Promise<string> {
    try {
        const authProvider = await getServerAuthProvider();
        const user = await getServerUser();

        if (authProvider === 'stack' && user && 'getAuthJson' in user) {
            const token = await user.getAuthJson();
            const permissions = 'listPermissions' in user && 'selectedTeam' in user
                ? await user.listPermissions(user.selectedTeam!) ?? []
                : [];
            return await getRedirectUrl(token?.accessToken ?? "", permissions);
        }

        // Local provider (or no Stack user): pick by role and existing agents.
        const accessToken = await getServerAccessToken();
        if (accessToken) {
            const headers = { Authorization: `Bearer ${accessToken}` };
            // Clients (viewer role) can't build agents; land them on call history.
            const contextResponse = await getCurrentOrganizationContextApiV1OrganizationsContextGet({ headers });
            if (contextResponse.data?.role === 'viewer') {
                return '/usage';
            }
            const countResponse = await getWorkflowCountApiV1WorkflowCountGet({ headers });
            if (countResponse.data && countResponse.data.active > 0) {
                return '/workflow';
            }
        }
    } catch (error) {
        // An error answers with the default landing, never an empty 500.
        logger.error('[after-sign-in] Error choosing the landing page:', error);
    }
    return '/workflow/create';
}
