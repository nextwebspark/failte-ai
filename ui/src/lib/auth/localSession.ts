/**
 * Store a local-auth session (httpOnly cookies via the server route) and
 * leave the auth pages. Shared by every flow that ends in a logged-in user:
 * password login/signup, email verification, password reset, Google.
 *
 * Once the browser is navigating it never resolves, so the caller's button
 * keeps its busy label ("Signing you in...") until the next page paints
 * instead of flashing back to its idle label. It still rejects on failure.
 */
export async function startLocalSession(
  auth: { token: string; user: unknown },
  nextPath?: string | null,
): Promise<never> {
  const res = await fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: auth.token, user: auth.user }),
  });
  if (!res.ok) {
    throw new Error("Could not start session");
  }
  // Back from the next page restores this one from the back/forward cache,
  // busy button included: reload it instead.
  window.addEventListener(
    "pageshow",
    (event) => {
      if (event.persisted) window.location.reload();
    },
    { once: true },
  );
  window.location.href = isSafeNextPath(nextPath) ? nextPath : "/after-sign-in";
  return new Promise<never>(() => {});
}

// Browsers drop tab/CR/LF while parsing URLs ("/\t/evil.com" -> "//evil.com"),
// so any control character disqualifies a path.
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;

/** Same-origin absolute paths only, so a crafted link can't redirect offsite. */
export function isSafeNextPath(path: string | null | undefined): path is string {
  return Boolean(
    path &&
      path.startsWith("/") &&
      !path.startsWith("//") &&
      !path.includes("\\") &&
      !CONTROL_CHARACTERS.test(path),
  );
}
