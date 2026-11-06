import { JUST_SIGNED_IN_KEY, type WelcomeKind } from "@/lib/greeting";

/**
 * Store a local-auth session (httpOnly cookies via the server route) and
 * leave the auth pages. Shared by every flow that ends in a logged-in user:
 * password login/signup, email verification, password reset, Google.
 *
 * The sign-in page is replaced in history, so Back never returns to it (a
 * Google callback or email link would re-submit a spent code). Once the
 * browser is navigating it never resolves, so the caller's button keeps its
 * busy label ("Signing you in...") until the next page paints instead of
 * flashing back to its idle label. It still rejects on failure.
 *
 * *welcome* picks the greeting on the first page: "new" right after signing
 * up, "back" for a returning person, "hello" when we can't tell (Google).
 */
export async function startLocalSession(
  auth: { token: string; user: unknown },
  nextPath?: string | null,
  welcome: WelcomeKind = "back",
): Promise<never> {
  const res = await fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: auth.token, user: auth.user }),
  });
  if (!res.ok) {
    throw new Error("Could not start session");
  }
  try {
    // Read once by WelcomeToast on the first page after sign-in.
    sessionStorage.setItem(JUST_SIGNED_IN_KEY, welcome);
  } catch {
    // Storage blocked: no welcome toast, nothing else changes.
  }
  window.location.replace(isSafeNextPath(nextPath) ? nextPath : "/after-sign-in");
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
