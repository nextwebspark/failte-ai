/**
 * Store a local-auth session (httpOnly cookies via the server route) and
 * leave the auth pages. Shared by every flow that ends in a logged-in user:
 * password login/signup, email verification, password reset, Google.
 */
export async function startLocalSession(
  auth: { token: string; user: unknown },
  nextPath?: string | null,
): Promise<void> {
  const res = await fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: auth.token, user: auth.user }),
  });
  if (!res.ok) {
    throw new Error("Could not start session");
  }
  window.location.href = isSafeNextPath(nextPath) ? nextPath : "/after-sign-in";
}

/** Same-origin absolute paths only, so a crafted link can't redirect offsite. */
export function isSafeNextPath(path: string | null | undefined): path is string {
  return Boolean(path && path.startsWith("/") && !path.startsWith("//") && !path.includes("\\"));
}
