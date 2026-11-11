import type { AuthUser, LocalUser } from "@/lib/auth";

/**
 * How the signed-in person is named on screen: their display name, else their
 * email address. Empty while signed out.
 */
export function memberName(user: AuthUser | null | undefined): string {
  if (!user) return "";
  const named = user as { displayName?: string | null; name?: string | null };
  return (
    named.displayName?.trim() ||
    named.name?.trim() ||
    (user as { primaryEmail?: string | null }).primaryEmail ||
    (user as LocalUser).email ||
    ""
  );
}

/** Up to two capitals for an avatar badge: "Maria Keane" → "MK", "ann@x.ie" → "AX". */
export function initialsOf(text: string, fallback = "U"): string {
  return (
    text
      .split(/[\s@.]/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0]?.toUpperCase())
      .join("") || fallback
  );
}
