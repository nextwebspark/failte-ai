/** The sample orders as the "Sample orders (demo)" table shows them. */

type Order = Record<string, unknown>;

export interface OrderRow {
    number: string;
    customer: string;
    ordered: string;
    town: string;
    items: string[];
    total: string;
    status: string;
    statusDate: string;
    tracking: string;
    email: string;
    mobile: string;
}

function text(value: unknown): string {
    return typeof value === "string" ? value : value == null ? "" : String(value);
}

function day(value: unknown): string {
    const v = text(value);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
    const [y, m, d] = v.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-IE", { day: "numeric", month: "short", timeZone: "UTC" });
}

export function orderRows(orders: Order[]): OrderRow[] {
    return orders.map((o) => {
        const courier = text(o.courier);
        const ending = text(o.tracking_ending);
        return {
            number: text(o.order_number),
            customer: text(o.customer),
            ordered: day(o.order_date),
            town: text(o.delivery_town),
            items: Array.isArray(o.items) ? o.items.map(text) : [],
            total: o.total != null ? `€${text(o.total)}` : "",
            status: text(o.status),
            statusDate: day(o.status_date),
            tracking: [courier, ending ? `••${ending}` : ""].filter(Boolean).join(" ") || "–",
            email: text(o.test_email),
            mobile: text(o.test_mobile),
        };
    });
}
