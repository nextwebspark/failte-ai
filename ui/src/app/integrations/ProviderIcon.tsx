import { CalendarDays, type LucideIcon, Mail, Plug, Sheet, ShoppingBag } from "lucide-react";

import { cn } from "@/lib/utils";

/** Catalog icon names -> lucide icons; unknown names get a generic plug. */
const ICONS: Record<string, LucideIcon> = {
    calendar: CalendarDays,
    "google-calendar": CalendarDays,
    sheet: Sheet,
    sheets: Sheet,
    spreadsheet: Sheet,
    mail: Mail,
    gmail: Mail,
    "shopping-bag": ShoppingBag,
    products: ShoppingBag,
};

export function ProviderIcon({ icon, className }: { icon: string | undefined; className?: string }) {
    const Icon = (icon && ICONS[icon]) || Plug;
    return (
        <span
            className={cn(
                "flex size-10 shrink-0 items-center justify-center rounded-lg border border-line bg-panel-2 text-brand",
                className,
            )}
            aria-hidden
        >
            <Icon className="size-5" />
        </span>
    );
}
