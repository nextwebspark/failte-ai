"use client";

import { Package } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { listSampleOrdersApiV1DemoSampleOrdersGet } from "@/client/sdk.gen";

/**
 * In a demo workspace with sample orders, a pointer to them for the
 * presenter. Renders nothing anywhere else: the API answers
 * `available: false` to every real workspace and to staff.
 */
export function SampleOrdersLink() {
    const [count, setCount] = useState<number | null>(null);

    useEffect(() => {
        let live = true;
        listSampleOrdersApiV1DemoSampleOrdersGet()
            .then((res) => {
                if (live && res.data?.available) setCount(res.data.orders?.length ?? 0);
            })
            .catch(() => undefined);
        return () => {
            live = false;
        };
    }, []);

    if (!count) return null;
    return (
        <section className="rounded-2xl border border-line bg-card p-4" aria-labelledby="sample-orders-title">
            <div className="flex items-start gap-3">
                <Package className="mt-0.5 h-4 w-4 shrink-0 text-ink-3" aria-hidden />
                <div className="min-w-0">
                    <h2 id="sample-orders-title" className="text-body font-semibold text-foreground">
                        Sample orders (demo)
                    </h2>
                    <p className="mt-1 text-caption text-ink-3">
                        {count} made-up orders your agent&apos;s order lookup reads in this demo. Pick one for a test call.
                    </p>
                    <Link href="/demo/sample-orders" className="mt-2 inline-block text-caption font-semibold text-brand hover:underline">
                        Open the sample orders
                    </Link>
                </div>
            </div>
        </section>
    );
}
