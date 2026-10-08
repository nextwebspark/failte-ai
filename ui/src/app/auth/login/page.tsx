import { getLocalAuthOptions } from "@/lib/auth/config";

import { LoginForm } from "./LoginForm";

// Resolve the backend health check before rendering so the "Sign up" link and
// the Google button are correct on first paint — no client-side fetch, no
// flicker on locked-down installs. force-dynamic keeps the page off the
// build-time prerender, which would bake in the flags' build-environment value.
export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const { signupEnabled, googleAuthEnabled } = await getLocalAuthOptions();
  return <LoginForm signupEnabled={signupEnabled} googleAuthEnabled={googleAuthEnabled} />;
}
