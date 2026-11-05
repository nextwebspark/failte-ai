import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const TONE: Record<"brand" | "sky" | "amber" | "mute", string> = {
    brand: "bg-brand-dim text-brand",
    sky: "bg-sky-dim text-sky",
    amber: "bg-amber-dim text-amber",
    mute: "bg-panel-2 text-ink-2",
};

/** A settings card: icon, title and one-line description, then its rows. */
export function SettingsSection({
    id,
    icon: Icon,
    tone = "mute",
    title,
    description,
    action,
    children,
}: {
    id: string;
    icon: LucideIcon;
    tone?: keyof typeof TONE;
    title: string;
    description: ReactNode;
    action?: ReactNode;
    children?: ReactNode;
}) {
    return (
        <section id={id} aria-labelledby={`${id}-title`} className="@container scroll-mt-4 overflow-hidden rounded-lg border border-line bg-card">
            <div className={cn("flex items-center gap-2.5 px-[18px] py-3.5", children && "border-b border-line-soft")}>
                <span className={cn("grid size-7 shrink-0 place-items-center rounded-md", TONE[tone])}>
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                </span>
                <div className="flex min-w-0 flex-col">
                    <h2 id={`${id}-title`} className="text-[15px] font-semibold text-foreground">
                        {title}
                    </h2>
                    <p className="text-[12.5px] text-ink-3">{description}</p>
                </div>
                {action && <div className="ml-auto shrink-0">{action}</div>}
            </div>
            {children && <div className="divide-y divide-line-soft">{children}</div>}
        </section>
    );
}

/**
 * Label and hint on the left, the control on the right. Sized by the card,
 * not the window: in a narrow card a wide control drops under its label,
 * while a `compact` one (a switch, a short number) stays on the right.
 */
export function SettingRow({
    label,
    htmlFor,
    hint,
    children,
    compact = false,
}: {
    label: ReactNode;
    htmlFor?: string;
    hint?: ReactNode;
    children: ReactNode;
    compact?: boolean;
}) {
    const Label = htmlFor ? "label" : "span";
    return (
        <div
            className={cn(
                "grid items-center gap-x-4 gap-y-2 px-[18px] py-3.5",
                compact
                    ? "grid-cols-[minmax(0,1fr)_auto]"
                    : "grid-cols-1 @lg:grid-cols-[minmax(0,1fr)_minmax(0,260px)]",
            )}
        >
            <div className="flex min-w-0 flex-col gap-0.5">
                <Label {...(htmlFor ? { htmlFor } : {})} className="text-[13px] font-semibold text-foreground">
                    {label}
                </Label>
                {hint && <span className="text-xs text-ink-3">{hint}</span>}
            </div>
            <div className={cn("min-w-0", compact && "flex justify-end")}>{children}</div>
        </div>
    );
}

/** A block inside a section that isn't a single setting (an editor, a list). */
export function SettingBlock({ children }: { children: ReactNode }) {
    return <div className="space-y-3 px-[18px] py-3.5">{children}</div>;
}
