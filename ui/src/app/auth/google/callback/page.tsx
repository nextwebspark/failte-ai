import { GoogleCallback } from "./GoogleCallback";

// Google redirects the browser here with ?code&state (or ?error).
export default async function GoogleCallbackPage({
  searchParams,
}: {
  searchParams: Promise<{ code?: string; state?: string; error?: string }>;
}) {
  const { code, state, error } = await searchParams;
  return <GoogleCallback code={code ?? null} state={state ?? null} providerError={error ?? null} />;
}
