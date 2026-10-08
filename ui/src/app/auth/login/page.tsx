import { getLocalAuthOptions } from "@/lib/auth/config";
import { isSafeNextPath } from "@/lib/auth/localSession";

import { LoginForm } from "./LoginForm";

// Resolve the backend health check before rendering so the "Sign up" link and
// the Google button are correct on first paint — no client-side fetch, no
// flicker on locked-down installs. force-dynamic keeps the page off the
// build-time prerender, which would bake in the flags' build-environment value.
export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const [{ signupEnabled, googleAuthEnabled }, { next }] = await Promise.all([
    getLocalAuthOptions(),
    searchParams,
  ]);
  return (
    <LoginForm
      signupEnabled={signupEnabled}
      googleAuthEnabled={googleAuthEnabled}
      nextPath={isSafeNextPath(next) ? next : null}
    />
  );
}
