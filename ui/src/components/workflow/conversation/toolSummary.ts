/**
 * A one-line, readable outcome for tool results the audience should be able
 * to follow in a live transcript. Only fields the tool already returned to
 * the agent are used, and nothing personal: an order lookup shows its
 * status, the status date, the courier and the last four characters of the
 * tracking number.
 */

type Json = Record<string, unknown>;

function asObject(value: unknown): Json | null {
    if (typeof value === "string") {
        try {
            return asObject(JSON.parse(value));
        } catch {
            return null;
        }
    }
    return value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : null;
}

function shortDate(value: unknown): string | null {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const [y, m, d] = value.split("-").map(Number);
    const date = new Date(Date.UTC(y, m - 1, d));
    return date.toLocaleDateString("en-IE", { day: "numeric", month: "short", timeZone: "UTC" });
}

/** "Order lookup · verified · Dispatched 7 Nov · Courier ••4F2K", or null when the result isn't an order lookup. */
export function toolResultSummary(result: unknown): string | null {
    const outer = asObject(result);
    if (!outer) return null;
    // HTTP tools wrap the response: {status, status_code, data}.
    const data = asObject(outer.data) ?? outer;
    if (data.lookup !== "order") return null;
    if (data.verified !== true) {
        return data.locked === true ? "Order lookup · couldn't verify · stopped trying" : "Order lookup · couldn't verify";
    }
    const parts = ["Order lookup", "verified"];
    const status = typeof data.status === "string" ? data.status : null;
    const when = shortDate(data.status_date);
    if (status) parts.push(when ? `${status} ${when}` : status);
    const expected = shortDate(data.expected_date);
    if (expected) parts.push(`expected ${expected}`);
    const courier = typeof data.courier === "string" ? data.courier : null;
    const ending = typeof data.tracking_ending === "string" ? data.tracking_ending : null;
    if (courier || ending) parts.push([courier, ending ? `••${ending}` : null].filter(Boolean).join(" "));
    return parts.join(" · ");
}
