/**
 * Words and small rules for Settings > Reports by email. Kept apart from the
 * page so they can be tested without rendering it.
 */

export type ReportFrequency = "daily" | "weekly" | "monthly";

export const FREQUENCIES: ReportFrequency[] = ["daily", "weekly", "monthly"];

export const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** "18:00" -> "6 pm", "09:30" -> "9:30 am" (Irish/UK style). */
export function clockLabel(value: string): string {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value);
  if (!match) return value;
  const hour = Number(match[1]);
  const suffix = hour < 12 ? "am" : "pm";
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return match[2] === "00" ? `${h12} ${suffix}` : `${h12}:${match[2]} ${suffix}`;
}

/** "Europe/Dublin" -> "Dublin time"; "America/New_York" -> "New York time". */
export function zoneLabel(zone: string): string {
  const city = zone.split("/").pop()?.replace(/_/g, " ");
  return city ? `${city} time` : zone;
}

export const TITLES: Record<ReportFrequency, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

/** What the report covers and when it arrives. */
export function describe(frequency: ReportFrequency, dailyTime: string): { covers: string; arrives: string } {
  switch (frequency) {
    case "daily":
      return {
        covers: `Today's calls, from midnight to ${clockLabel(dailyTime)}.`,
        arrives: `Every day at ${clockLabel(dailyTime)}.`,
      };
    case "weekly":
      return { covers: "Last week's calls, Monday to Sunday.", arrives: "Mondays at 8 am." };
    case "monthly":
      return { covers: "Last month's calls, the whole month.", arrives: "On the 1st at 8 am." };
  }
}

/** "2026-11-06" -> "6 Nov"; "2026-W45" -> "week 45"; "2026-10" -> "Oct 2026". */
export function sentLabel(frequency: ReportFrequency, key: string | undefined): string | null {
  if (!key) return null;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  if (frequency === "daily") {
    const [, m, d] = key.split("-");
    return m && d ? `${Number(d)} ${months[Number(m) - 1]}` : key;
  }
  if (frequency === "weekly") {
    const week = key.split("-W")[1];
    return week ? `week ${Number(week)}` : key;
  }
  const [y, m] = key.split("-");
  return y && m ? `${months[Number(m) - 1]} ${y}` : key;
}

/** Why an address can't be added, or null when it can. */
export function addressProblem(address: string, existing: string[], max: number): string | null {
  const value = address.trim();
  if (!value) return "Type an email address.";
  if (!EMAIL_SHAPE.test(value)) return "That doesn't look like an email address.";
  if (existing.some((a) => a.toLowerCase() === value.toLowerCase())) return "That address is already on the list.";
  if (existing.length >= max) return `You can add up to ${max} addresses.`;
  return null;
}
