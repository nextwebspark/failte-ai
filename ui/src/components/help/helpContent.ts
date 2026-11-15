/**
 * What the Help panel offers before anyone types: starter questions for the
 * screen you're on, and the guides list. The answers come from the help
 * assistant's guides (api/services/help_assistant/knowledge), so every
 * starter here must be one those guides answer.
 */

export type HelpTab = "ask" | "guides" | "contact";

type Starters = { match: RegExp; questions: string[] };

const STARTERS: Starters[] = [
  {
    match: /^\/workflow\/\d+\/deployment/,
    questions: [
      "How do I forward my mobile to my agent?",
      "Why does it say my number is an extension?",
      "Can I use my own phone provider account?",
    ],
  },
  {
    match: /^\/workflow\/\d+\/facts/,
    questions: [
      "How do I set my opening hours?",
      "How do I let my agent put callers through to a person?",
      "Can I use my own or a cloned voice?",
    ],
  },
  {
    match: /^\/telephony-configurations/,
    questions: [
      "How do I forward my mobile to my agent?",
      "How do I get a LightMove number?",
      "Can I use my own phone provider account?",
    ],
  },
  {
    match: /^\/usage/,
    questions: [
      "How do I search what callers said?",
      "How do I share a call recording?",
      "Where does the call summary come from?",
    ],
  },
  {
    match: /^\/follow-ups/,
    questions: [
      "What lands in Follow-ups?",
      "How do I mark a follow-up done?",
      "How do I add an answer my agent couldn't give?",
    ],
  },
  {
    match: /^\/bookings/,
    questions: [
      "Where do bookings come from?",
      "How do I turn my agent's booking on or off?",
      "Who can manage bookings?",
    ],
  },
  {
    match: /^\/reports/,
    questions: [
      "How do I customise which cards show on Reports?",
      "How do the money estimates work?",
      "How do I get the report by email?",
    ],
  },
  {
    match: /^\/settings\/reports/,
    questions: ["How do I choose who gets the email reports?", "How do I unsubscribe from the email reports?"],
  },
  {
    match: /^\/settings\/notifications/,
    questions: ["Who gets emailed after calls?", "Can callers get a text confirming their booking?"],
  },
  {
    match: /^\/settings\/compliance|^\/account/,
    questions: [
      "A caller wants their data deleted. What do I do?",
      "How do I export my data?",
      "How long are recordings kept?",
    ],
  },
  {
    match: /^\/integrations/,
    questions: ["How do I connect Google Calendar?", "How do I connect Calendly?", "How do I disconnect a calendar?"],
  },
  {
    match: /^\/team/,
    questions: ["How do I invite a team member?", "What can each role do?", "How do I let staff manage bookings?"],
  },
  {
    match: /^\/billing/,
    questions: ["How much do calls cost?", "How do I top up my credit?", "What happens when my credit runs out?"],
  },
  {
    match: /^\/workflow\/\d+/,
    questions: [
      "How do I test my agent in the browser?",
      "Why can't a browser test transfer the call?",
      "Where do my test calls show up?",
    ],
  },
];

const DEFAULT_STARTERS = [
  "What do I need to set up before my agent takes calls?",
  "How do I forward my mobile to my agent?",
  "How do I pass calls to my team?",
];

export function startersFor(pathname: string | null | undefined): string[] {
  const path = pathname ?? "";
  return STARTERS.find((s) => s.match.test(path))?.questions ?? DEFAULT_STARTERS;
}

/** A screen in the guides list. `agent` screens need the workspace's agent. */
export type GuideScreen =
  | { kind: "path"; href: string }
  | { kind: "agent"; segment: "facts" | "deployment" };

export type Guide = {
  title: string;
  summary: string;
  screen: GuideScreen;
  screenLabel: string;
  questions: string[];
};

export const GUIDES: Guide[] = [
  {
    title: "Getting started",
    summary: "What to set up before your agent takes calls.",
    screen: { kind: "path", href: "/overview" },
    screenLabel: "Home",
    questions: ["What do I need to set up before my agent takes calls?", "How do I try my agent before real callers ring?"],
  },
  {
    title: "What your agent knows",
    summary: "Business details, opening hours, answers and voice.",
    screen: { kind: "agent", segment: "facts" },
    screenLabel: "What your agent knows",
    questions: ["How do I set my opening hours?", "How do I add answers to common questions?", "How do I change my agent's voice?"],
  },
  {
    title: "Phone number",
    summary: "Forward your number or mobile, or get a new one.",
    screen: { kind: "agent", segment: "deployment" },
    screenLabel: "Phone number",
    questions: ["How do I forward my mobile to my agent?", "What are the mobile forwarding codes?", "How do I get a LightMove number?"],
  },
  {
    title: "Pass calls to your team",
    summary: "Put callers through to a person, and skip it when you're closed.",
    screen: { kind: "agent", segment: "facts" },
    screenLabel: "What your agent knows",
    questions: ["How do I let my agent put callers through to a person?", "How do I stop transfers when we're closed?", "What does \"Transfer not answered\" mean?"],
  },
  {
    title: "Calls and recordings",
    summary: "Search calls, listen, share a recording.",
    screen: { kind: "path", href: "/usage" },
    screenLabel: "Calls",
    questions: ["How do I search what callers said?", "How do I share a call recording?"],
  },
  {
    title: "Follow-ups and bookings",
    summary: "Callers who need a person, and booked appointments.",
    screen: { kind: "path", href: "/follow-ups" },
    screenLabel: "Follow-ups",
    questions: ["What lands in Follow-ups?", "Where do bookings come from?"],
  },
  {
    title: "Reports",
    summary: "Your report pack, Customise, estimates and emails.",
    screen: { kind: "path", href: "/reports" },
    screenLabel: "Reports",
    questions: ["How do I customise which cards show on Reports?", "How do I get call reports by email?"],
  },
  {
    title: "Calendars",
    summary: "Connect Google Calendar, Outlook or Calendly for bookings.",
    screen: { kind: "path", href: "/integrations" },
    screenLabel: "Integrations",
    questions: ["How do I connect Google Calendar?", "How do I connect Outlook Calendar?", "How do I connect Calendly?"],
  },
  {
    title: "Team and roles",
    summary: "Invite people and choose what they can do.",
    screen: { kind: "path", href: "/team" },
    screenLabel: "Members",
    questions: ["How do I invite a team member?", "What can each role do?"],
  },
  {
    title: "Billing",
    summary: "Price per minute, free credit and top-ups.",
    screen: { kind: "path", href: "/billing" },
    screenLabel: "Billing",
    questions: ["How much do calls cost?", "How do I top up my credit?"],
  },
  {
    title: "Privacy",
    summary: "Data requests, exporting and deleting data.",
    screen: { kind: "path", href: "/settings/compliance" },
    screenLabel: "Privacy & compliance",
    questions: ["A caller wants their data deleted. What do I do?", "How do I export my data?"],
  },
];

export function guideHref(screen: GuideScreen, agents: readonly { id: number }[] | null): string {
  if (screen.kind === "path") return screen.href;
  const only = agents?.length === 1 ? agents[0] : null;
  if (!only) return "/workflow";
  return screen.segment === "deployment" ? `/workflow/${only.id}/deployment#phone` : `/workflow/${only.id}/facts`;
}

export const TICKET_CATEGORIES = [
  { value: "setup", label: "Setup help" },
  { value: "phone", label: "Phone or transfers" },
  { value: "billing", label: "Billing" },
  { value: "bug", label: "Bug report" },
  { value: "feature", label: "Feature request" },
  { value: "privacy", label: "Privacy" },
  { value: "other", label: "Other" },
] as const;

export type TicketCategoryValue = (typeof TICKET_CATEGORIES)[number]["value"];

export function categoryLabel(value: string): string {
  return TICKET_CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

export const TICKET_STATUS_LABELS: Record<string, string> = {
  open: "Open",
  answered: "Answered",
  closed: "Closed",
};
