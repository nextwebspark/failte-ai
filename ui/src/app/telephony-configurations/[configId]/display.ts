/**
 * How a phone account's details read on its page: the provider form's own
 * labels instead of stored keys, plain names for number types, and a warning
 * for an ARI address our server can't reach.
 */

/** "ari_endpoint" -> "Ari endpoint", for keys the provider form doesn't label. */
export function humanizeKey(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

export function credentialLabel(key: string, labels: Record<string, string>): string {
  return labels[key] ?? humanizeKey(key);
}

const ADDRESS_TYPES: Record<string, string> = {
  pstn: "Phone number",
  sip_uri: "SIP address",
  sip_extension: "SIP extension",
};

export function addressTypeLabel(type: string): string {
  return ADDRESS_TYPES[type] ?? humanizeKey(type);
}

/**
 * An ARI address on "localhost" points at our own server, not the customer's
 * Asterisk, so calls never connect. (On a local Docker setup the host machine
 * is host.docker.internal.)
 */
export function pointsAtLocalhost(url: unknown): boolean {
  if (typeof url !== "string" || !url.trim()) return false;
  try {
    const host = new URL(url.trim()).hostname.toLowerCase();
    return host === "localhost" || host === "::1" || host === "[::1]" || host.startsWith("127.");
  } catch {
    return false;
  }
}

/** Providers that call us over HTTP get an inbound webhook; ARI connects over its own socket. */
export function usesInboundWebhook(provider: string): boolean {
  return provider !== "ari";
}
