import { Panel } from "@/components/ui/panel";

/**
 * What Calendly's API does and doesn't let the agent do, said once wherever
 * Calendly is connected, so nobody expects more than it can do.
 */
export function CalendlyNotes() {
    return (
        <Panel accent="sky" padding="sm">
            <p className="text-sm font-medium">Good to know</p>
            <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-ink-2">
                <li>
                    If Calendly ever refuses a booking (for example, your plan or the event doesn&apos;t allow it),
                    your agent says so and takes the caller&apos;s details for you. It never says a caller is booked
                    unless Calendly confirmed it.
                </li>
                <li>Calendly needs the caller&apos;s email address to book. Your agent asks for it and spells it back.</li>
                <li>
                    Your agent can&apos;t move or cancel Calendly bookings. Callers use the links in their Calendly
                    email, or you change them in Calendly.
                </li>
            </ul>
        </Panel>
    );
}
