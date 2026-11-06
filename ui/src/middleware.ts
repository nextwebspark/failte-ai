import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

import {
  DEFAULT_FEATURE_FLAGS,
  type FeatureFlags,
  featureForRoute,
  isSwitchedOffRoute,
  parseFeatureFlags,
} from '@/config/features';
import { getServerBackendUrl } from '@/lib/apiClient';
import { OSS_TOKEN_COOKIE } from '@/lib/auth/cookies';
import { isPublicPath } from '@/lib/auth/publicPaths';

let cachedAuthProvider: string | null = null;

// Which product areas are on for at least one organisation
// (GET /api/v1/features/public), cached briefly so a platform admin's switch
// reaches every worker within FEATURE_CACHE_MS.
const FEATURE_CACHE_MS = 30_000;
let cachedFeatures: { flags: FeatureFlags; at: number } | null = null;

async function fetchAvailableFeatures(): Promise<FeatureFlags> {
  if (cachedFeatures && Date.now() - cachedFeatures.at < FEATURE_CACHE_MS) {
    return cachedFeatures.flags;
  }
  try {
    const res = await fetch(`${getServerBackendUrl()}/api/v1/features/public`, {
      cache: 'no-store',
      // Don't hold the page for long if the backend is slow; the defaults apply.
      signal: typeof AbortSignal.timeout === 'function' ? AbortSignal.timeout(2000) : undefined,
    });
    if (res.ok) {
      const flags = parseFeatureFlags(await res.json());
      if (flags) {
        cachedFeatures = { flags, at: Date.now() };
        return flags;
      }
    }
  } catch {
    // Backend not reachable: fall through to the defaults, not cached.
  }
  return DEFAULT_FEATURE_FLAGS;
}

async function fetchAuthProvider(): Promise<string> {
  if (cachedAuthProvider) {
    return cachedAuthProvider;
  }

  try {
    const backendUrl = getServerBackendUrl();
    const res = await fetch(`${backendUrl}/api/v1/health`);
    if (res.ok) {
      const data = await res.json();
      // Only cache a DEFINITIVE answer from the backend. Never cache a failure:
      // this is a module-scoped cache with no TTL, so a single early request
      // during container startup (before the api service is reachable) would
      // otherwise poison it to 'local' for the life of the worker — redirecting
      // every Stack user to the local /auth/login form even though the backend
      // reports `stack`.
      cachedAuthProvider = (data.auth_provider as string) || 'local';
      return cachedAuthProvider;
    }
  } catch {
    // Backend not reachable — fall through without caching so we retry next request.
  }

  // Provider unknown (backend unreachable). Return a non-'local' sentinel so the
  // middleware does NOT guard/redirect: assuming 'local' here would bounce Stack
  // users to /auth/login. Deliberately not cached — the next request retries.
  return 'unknown';
}

export async function middleware(request: NextRequest) {
  // Areas switched off for every organisation (platform admin switches, or the
  // defaults in config/features.ts when the backend can't say): their pages,
  // bookmarks included, land on Overview. Only an area's own pages ask the
  // backend. An area on for some organisations only is let through here; the
  // app shell then applies the signed-in organisation's switch.
  if (
    featureForRoute(request.nextUrl.pathname) !== null &&
    isSwitchedOffRoute(request.nextUrl.pathname, await fetchAvailableFeatures())
  ) {
    return NextResponse.redirect(new URL('/overview', request.url));
  }

  const authProvider = await fetchAuthProvider();

  // Only handle OSS mode
  if (authProvider !== 'local') {
    return NextResponse.next();
  }

  const token = request.cookies.get(OSS_TOKEN_COOKIE)?.value;
  const { pathname } = request.nextUrl;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  // If no token, redirect to login
  if (!token) {
    const loginUrl = new URL('/auth/login', request.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

// Configure which routes the middleware runs on
export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - api routes
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public static assets (anything with a file extension, e.g. /brand/fallcha-mark.svg)
     */
    '/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|otf)).*)',
  ],
};
