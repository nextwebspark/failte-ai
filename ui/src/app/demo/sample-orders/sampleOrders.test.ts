import { describe, expect, it } from "vitest";

import { orderRows } from "./sampleOrders";

describe("orderRows", () => {
    it("shows the tracking ending only, and dates as short days", () => {
        const [row] = orderRows([
            {
                order_number: "CHM-104203",
                order_date: "2026-11-05",
                customer: "Niamh Walsh",
                delivery_town: "Galway",
                items: ["1 x Ocean Signal RescueME PLB1"],
                total: "376.90",
                status: "Dispatched",
                status_date: "2026-11-07",
                courier: "Courier",
                tracking_ending: "4F2K",
                test_email: "niamh.walsh@example.com",
                test_mobile: "+353865550203",
            },
        ]);
        expect(row.tracking).toBe("Courier ••4F2K");
        expect(row.statusDate).toBe("7 Nov");
        expect(row.total).toBe("€376.90");
    });

    it("shows a dash when nothing has been sent", () => {
        expect(orderRows([{ order_number: "CHM-104201", status: "Received" }])[0].tracking).toBe("–");
    });
});
