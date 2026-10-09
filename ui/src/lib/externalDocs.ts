// The API ships documentation URLs inside provider schemas and node specs. Some
// are genuine third-party docs (Azure, Inworld, Hugging Face, Google STT) and are
// worth rendering; the rest point at the upstream vendor's docs site, which this
// product does not publish. Filter here rather than in the API so an upstream sync
// that adds a tenth vendor-hosted provider URL is suppressed with no new edits.
// Our own docs host (BRAND.domain, e.g. docs.fallcha.ai) is always accepted.
import { BRAND } from "@/config/brand";

const VENDOR_DOC_HOSTS = [/(^|\.)dograh\.com$/i];

function isFirstPartyHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  return host === BRAND.domain || host.endsWith(`.${BRAND.domain}`);
}

export function publicDocsHref(url?: string | null): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    if (!/^https?:$/.test(parsed.protocol)) return undefined;
    if (isFirstPartyHost(parsed.hostname)) return url;
    return VENDOR_DOC_HOSTS.some((re) => re.test(parsed.hostname)) ? undefined : url;
  } catch {
    return undefined;
  }
}
