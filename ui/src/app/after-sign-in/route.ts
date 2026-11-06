import {
    getCurrentOrganizationContextApiV1OrganizationsContextGet,
    getWorkflowCountApiV1WorkflowCountGet,
} from "@/client/sdk.gen";
import { getServerAccessToken, getServerAuthProvider, getServerUser } from "@/lib/auth/server";
import logger from '@/lib/logger';
import { getRedirectUrl } from "@/lib/utils";

export const dynamic = 'force-dynamic';

/** The dashboard every member with an agent starts on. */
const HOME = '/overview';

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
            // Owners (viewer role) and staff can't build agents: they always
            // start on Home, which explains a workspace with no agent yet.
            const contextResponse = await getCurrentOrganizationContextApiV1OrganizationsContextGet({ headers });
            const role = contextResponse.data?.role;
            if (role === 'viewer' || role === 'staff') {
                return HOME;
            }
            // Everyone else lands on Home once there is an agent; building
            // one is where a new workspace starts.
            const countResponse = await getWorkflowCountApiV1WorkflowCountGet({ headers });
            if (countResponse.data && countResponse.data.active > 0) {
                return HOME;
            }
        }
    } catch (error) {
        // An error answers with the default landing, never an empty 500.
        logger.error('[after-sign-in] Error choosing the landing page:', error);
    }
    return '/workflow/create';
}
