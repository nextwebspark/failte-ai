import { getLocalAuthOptions } from "@/lib/auth/config";

import { SignupForm } from "./SignupForm";

export const dynamic = "force-dynamic";

export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<{ invite?: string; email?: string }>;
}) {
  const [{ googleAuthEnabled }, params] = await Promise.all([
    getLocalAuthOptions(),
    searchParams,
  ]);
  return (
    <SignupForm
      googleAuthEnabled={googleAuthEnabled}
      inviteToken={params.invite ?? null}
      invitedEmail={params.email ?? null}
    />
  );
}
