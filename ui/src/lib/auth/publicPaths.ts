/**
 * Paths reachable without a session in local (OSS) auth mode. Shared by the
 * middleware (server redirect) and the local auth provider (client redirect),
 * which must agree or one of them bounces the visitor to /auth/login.
 *
 * `/auth` covers login, signup, email verification, password reset and the
 * Google callback; `/invite` previews an invitation before the visitor has an
 * account; `/embed` serves the public website widget (e.g.
 * /embed/fallcha-widget.js, plus the legacy failte-/dograh-widget.js shims),
 * which third-party sites load without a session.
 */
export const PUBLIC_PATHS = ["/auth", "/invite", "/embed"] as const;

/**
 * Match on a path-segment boundary (exact match or a `/`-delimited subpath)
 * rather than a bare prefix, so `/embed` exempts `/embed` and `/embed/...` but
 * NOT sibling routes such as `/embed-admin`.
 */
export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
