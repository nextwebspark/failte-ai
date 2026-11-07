"use client";

/**
 * The Help panel: a sheet from the right with three tabs.
 *
 *   Ask              the help assistant (answers from LightMove's own guides only)
 *   Guides           the main how-tos, each with the screen it's about
 *   Contact support  a ticket to the team, and your recent tickets
 *
 * The top bar's Help button and the phone's More sheet both open it through
 * useHelpPanel().
 */

import {
  ArrowRight,
  BookOpen,
  ExternalLink,
  Loader2,
  Mail,
  MessageCircleQuestion,
  Send,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  askHelpApiV1HelpAskPost,
  createHelpTicketApiV1HelpTicketsPost,
  getHelpTicketsApiV1HelpTicketsGet,
  helpFeedbackApiV1HelpFeedbackPost,
} from "@/client/sdk.gen";
import type { HelpAnswerOut, TicketSummary } from "@/client/types.gen";
import { useWorkspaceAgents } from "@/components/layout/workspaceAgents";
import { SUPPORT_MAILTO } from "@/components/SupportLink";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { BRAND } from "@/config/brand";
import { detailFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

import {
  categoryLabel,
  guideHref,
  GUIDES,
  type HelpTab,
  startersFor,
  TICKET_CATEGORIES,
  TICKET_STATUS_LABELS,
  type TicketCategoryValue,
} from "./helpContent";
import { HelpMarkdown } from "./HelpMarkdown";

export const MAX_QUESTION_CHARS = 500;
export const CONTACT_FORM_URL = `${BRAND.contactUrl}?reason=support`;

type HelpPanelApi = { openHelp: (tab?: HelpTab) => void };

const HelpPanelContext = createContext<HelpPanelApi | null>(null);

/** Null outside the app shell (e.g. a component rendered on its own in a test). */
export function useHelpPanel(): HelpPanelApi | null {
  return useContext(HelpPanelContext);
}

export function HelpPanelProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<HelpTab>("ask");
  const openHelp = useCallback((next: HelpTab = "ask") => {
    setTab(next);
    setOpen(true);
  }, []);
  const api = useMemo(() => ({ openHelp }), [openHelp]);
  return (
    <HelpPanelContext.Provider value={api}>
      {children}
      <HelpPanel open={open} onOpenChange={setOpen} tab={tab} onTabChange={setTab} />
    </HelpPanelContext.Provider>
  );
}

type Turn = {
  id: number;
  question: string;
  reply?: HelpAnswerOut;
  error?: string;
  rating?: "up" | "down";
};

export function HelpPanel({
  open,
  onOpenChange,
  tab,
  onTabChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tab: HelpTab;
  onTabChange: (tab: HelpTab) => void;
}) {
  const pathname = usePathname();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState<{ subject: string; message: string } | null>(null);
  const nextId = useRef(0);
  const close = () => onOpenChange(false);

  // Each question stands alone: no earlier turns are sent with it.
  const ask = useCallback(
    (question: string) => {
      const q = question.trim().slice(0, MAX_QUESTION_CHARS);
      if (!q) return;
      const id = nextId.current++;
      setTurns((prev) => [...prev, { id, question: q }]);
      const settle = (update: Partial<Turn>) =>
        setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...update } : t)));
      const failed = "Sorry, I couldn't answer just now. Please try again.";
      askHelpApiV1HelpAskPost({ body: { question: q, page: pathname } })
        .then((res) => settle(res.data ? { reply: res.data } : { error: detailFromError(res.error, failed) }))
        .catch(() => settle({ error: failed }));
    },
    [pathname],
  );

  const askPerson = (question?: string) => {
    if (question) setDraft({ subject: question.slice(0, 150), message: "" });
    onTabChange("contact");
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-[440px]">
        <div className="border-b border-line px-4 pb-3 pt-4">
          <SheetTitle className="text-title">Help</SheetTitle>
          <SheetDescription className="text-caption text-ink-3">
            Answers about using {BRAND.shortName}, guides, and a way to reach our team.
          </SheetDescription>
        </div>
        <Tabs value={tab} onValueChange={(v) => onTabChange(v as HelpTab)} className="min-h-0 flex-1 gap-0">
          <div className="px-4 pt-3">
            <TabsList className="grid h-10 w-full grid-cols-3">
              <TabsTrigger value="ask" className="text-caption">
                Ask
              </TabsTrigger>
              <TabsTrigger value="guides" className="text-caption">
                Guides
              </TabsTrigger>
              <TabsTrigger value="contact" className="text-caption">
                Contact support
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="ask" className="flex min-h-0 flex-col">
            <AskTab
              pathname={pathname}
              turns={turns}
              onAsk={ask}
              onRate={(id, rating) => setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, rating } : t)))}
              onNavigate={close}
              onAskPerson={askPerson}
            />
          </TabsContent>
          <TabsContent value="guides" className="min-h-0 overflow-y-auto">
            <GuidesTab
              onNavigate={close}
              onAsk={(question) => {
                onTabChange("ask");
                ask(question);
              }}
            />
          </TabsContent>
          <TabsContent value="contact" className="min-h-0 overflow-y-auto">
            <ContactTab pathname={pathname} draft={draft} onDraftUsed={() => setDraft(null)} />
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

// ------------------------------------------------------------------ Ask

function AskTab({
  pathname,
  turns,
  onAsk,
  onRate,
  onNavigate,
  onAskPerson,
}: {
  pathname: string;
  turns: Turn[];
  onAsk: (question: string) => void;
  onRate: (id: number, rating: "up" | "down") => void;
  onNavigate: () => void;
  onAskPerson: (question?: string) => void;
}) {
  const [text, setText] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const pending = turns.some((t) => !t.reply && !t.error);
  const starters = startersFor(pathname);

  useEffect(() => {
    const el = scroller.current;
    if (el && typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [turns]);

  const ask = (question: string) => {
    if (!question.trim() || pending) return;
    onAsk(question);
    setText("");
  };

  const rate = (turn: Turn, rating: "up" | "down") => {
    if (!turn.reply) return;
    onRate(turn.id, rating);
    void helpFeedbackApiV1HelpFeedbackPost({
      body: {
        answer_id: turn.reply.id,
        helpful: rating === "up",
        kind: turn.reply.kind,
        sources: turn.reply.sources,
        page: pathname,
      },
    }).catch(() => undefined);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scroller} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4" aria-live="polite">
        {turns.length === 0 && (
          <div className="space-y-3">
            <div className="flex items-start gap-2.5 rounded-xl bg-panel-2 px-3.5 py-3">
              <Sparkles className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
              <p className="text-body text-ink-2">
                Ask how to do something in {BRAND.shortName}. I answer from our own guides and can&apos;t see your calls or
                change anything for you.
              </p>
            </div>
            <p className="text-meta font-medium uppercase tracking-wide text-ink-3">Try asking</p>
            <ul className="space-y-2">
              {starters.map((question) => (
                <li key={question}>
                  <button
                    type="button"
                    onClick={() => ask(question)}
                    className="flex w-full items-center gap-2 rounded-lg border border-line px-3 py-2.5 text-left text-body text-foreground outline-none hover:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  >
                    <MessageCircleQuestion className="size-4 shrink-0 text-ink-3" aria-hidden />
                    {question}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {turns.map((turn) => (
          <div key={turn.id} className="space-y-2">
            <p className="ml-auto w-fit max-w-[85%] rounded-xl rounded-br-sm bg-brand-dim px-3 py-2 text-body text-foreground">
              {turn.question}
            </p>
            <div className="rounded-xl border border-line bg-panel px-3.5 py-3">
              {!turn.reply && !turn.error && (
                <p className="flex items-center gap-2 text-body text-ink-3">
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
                  Looking in the guides…
                </p>
              )}
              {turn.error && <p className="text-body text-ink-2">{turn.error}</p>}
              {turn.reply && <HelpMarkdown text={turn.reply.answer} onNavigate={onNavigate} />}
              {(turn.reply || turn.error) && (
                <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line-soft pt-2.5">
                  <button
                    type="button"
                    onClick={() => onAskPerson(turn.question)}
                    className="text-caption font-medium text-brand underline-offset-2 hover:underline"
                  >
                    Ask a person instead
                  </button>
                  {turn.reply?.kind === "answer" && (
                    <div className="ml-auto flex items-center gap-1">
                      <span className="text-meta text-ink-3">{turn.rating ? "Thanks!" : "Helpful?"}</span>
                      <RateButton label="Yes, helpful" active={turn.rating === "up"} onClick={() => rate(turn, "up")}>
                        <ThumbsUp className="size-4" aria-hidden />
                      </RateButton>
                      <RateButton label="Not helpful" active={turn.rating === "down"} onClick={() => rate(turn, "down")}>
                        <ThumbsDown className="size-4" aria-hidden />
                      </RateButton>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      <form
        className="border-t border-line px-4 py-3"
        onSubmit={(event) => {
          event.preventDefault();
          ask(text);
        }}
      >
        <Label htmlFor="help-question" className="sr-only">
          Your question
        </Label>
        <div className="flex items-end gap-2">
          <Textarea
            id="help-question"
            value={text}
            maxLength={MAX_QUESTION_CHARS}
            rows={2}
            placeholder="Ask a question about using LightMove"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask(text);
              }
            }}
            className="min-h-11 resize-none text-body"
          />
          <Button type="submit" size="icon" className="size-11 shrink-0" disabled={!text.trim() || pending} aria-label="Send question">
            <Send className="size-4" aria-hidden />
          </Button>
        </div>
        <p className="mt-1.5 text-meta text-ink-3">
          Answers can be wrong. Don&apos;t paste passwords, keys or callers&apos; details.
        </p>
      </form>
    </div>
  );
}

function RateButton({
  label,
  active,
  onClick,
  children,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "grid size-8 place-items-center rounded-md text-ink-3 outline-none hover:bg-panel-2 hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50",
        active && "bg-brand-dim text-brand",
      )}
    >
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ Guides

function GuidesTab({ onNavigate, onAsk }: { onNavigate: () => void; onAsk: (question: string) => void }) {
  const agents = useWorkspaceAgents();
  return (
    <div className="space-y-3 px-4 py-4">
      {GUIDES.map((guide) => (
        <section key={guide.title} className="rounded-xl border border-line px-3.5 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-body font-semibold text-foreground">{guide.title}</h3>
              <p className="text-caption text-ink-3">{guide.summary}</p>
            </div>
            <Link
              href={guideHref(guide.screen, agents)}
              onClick={onNavigate}
              className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-caption font-medium text-brand outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
            >
              Open
              <ArrowRight className="size-3.5" aria-hidden />
              <span className="sr-only">{guide.screenLabel}</span>
            </Link>
          </div>
          <ul className="mt-2 space-y-1">
            {guide.questions.map((question) => (
              <li key={question}>
                <button
                  type="button"
                  onClick={() => onAsk(question)}
                  className="w-full rounded-md px-1.5 py-1 text-left text-caption text-ink-2 outline-none hover:bg-panel-2 hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
                >
                  {question}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <a
        href={BRAND.docsUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-2 rounded-xl border border-dashed border-line px-3.5 py-3 text-body font-medium text-foreground hover:bg-panel-2"
      >
        <BookOpen className="size-4 text-ink-3" aria-hidden />
        Full documentation
        <ExternalLink className="ml-auto size-3.5 text-ink-3" aria-hidden />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
    </div>
  );
}

// ------------------------------------------------------------------ Contact

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IE", { day: "numeric", month: "short" });
}

function ContactTab({
  pathname,
  draft,
  onDraftUsed,
}: {
  pathname: string;
  draft: { subject: string; message: string } | null;
  onDraftUsed: () => void;
}) {
  const [category, setCategory] = useState<TicketCategoryValue>("setup");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [includePage, setIncludePage] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<TicketSummary | null>(null);
  const [tickets, setTickets] = useState<TicketSummary[] | null>(null);

  useEffect(() => {
    if (!draft) return;
    setSubject(draft.subject);
    setMessage(draft.message);
    setSent(null);
    onDraftUsed();
  }, [draft, onDraftUsed]);

  const load = useCallback(async () => {
    try {
      const res = await getHelpTicketsApiV1HelpTicketsGet();
      setTickets(res.data?.tickets ?? []);
    } catch {
      setTickets([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const send = async () => {
    setSending(true);
    setError(null);
    try {
      const res = await createHelpTicketApiV1HelpTicketsPost({
        body: { category, subject: subject.trim(), message: message.trim(), include_page: includePage, page: pathname },
      });
      if (!res.data) {
        setError(detailFromError(res.error, "Couldn't send your message. Please try again."));
        return;
      }
      setSent(res.data.ticket);
      setSubject("");
      setMessage("");
      void load();
    } catch {
      setError("Couldn't send your message. Please try again.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-5 px-4 py-4">
      {sent ? (
        <div role="status" className="rounded-xl border border-line bg-panel-2 px-3.5 py-3">
          <p className="text-body font-semibold text-foreground">Thanks, we&apos;ve got your message.</p>
          <p className="mt-1 text-body text-ink-2">
            Your reference is <strong className="font-mono">{sent.reference}</strong>. We&apos;ve emailed you a copy, and a
            person from our team will reply by email.
          </p>
          <Button variant="outline" size="sm" className="mt-3 h-9" onClick={() => setSent(null)}>
            Send another message
          </Button>
        </div>
      ) : (
        <form
          className="space-y-3.5"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="ticket-category" className="text-caption">
              What is it about?
            </Label>
            <Select value={category} onValueChange={(v) => setCategory(v as TicketCategoryValue)}>
              <SelectTrigger id="ticket-category" className="h-10 w-full text-body">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TICKET_CATEGORIES.map((c) => (
                  <SelectItem key={c.value} value={c.value} className="text-body">
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ticket-subject" className="text-caption">
              Subject
            </Label>
            <Input
              id="ticket-subject"
              value={subject}
              maxLength={150}
              onChange={(e) => setSubject(e.target.value)}
              className="h-10 text-body"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ticket-message" className="text-caption">
              Message
            </Label>
            <Textarea
              id="ticket-message"
              value={message}
              maxLength={4000}
              rows={5}
              placeholder="What were you trying to do, and what happened?"
              onChange={(e) => setMessage(e.target.value)}
              className="text-body"
            />
          </div>
          <label className="flex items-start gap-2.5 text-body text-ink-2">
            <Checkbox
              checked={includePage}
              onCheckedChange={(v) => setIncludePage(v === true)}
              className="mt-0.5"
              aria-describedby="ticket-page-hint"
            />
            <span>
              Include the page I&apos;m on
              <span id="ticket-page-hint" className="block text-caption text-ink-3">
                Adds this screen&apos;s address and your workspace name, so we can find it faster.
              </span>
            </span>
          </label>
          {error && (
            <p role="alert" className="text-caption text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" className="h-10 w-full gap-2" disabled={sending || !subject.trim() || !message.trim()}>
            {sending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
            Send to support
          </Button>
          <p className="text-caption text-ink-3">We&apos;ll email you a copy with your reference number.</p>
        </form>
      )}

      <section aria-labelledby="your-tickets">
        <h3 id="your-tickets" className="text-meta font-medium uppercase tracking-wide text-ink-3">
          Your recent messages
        </h3>
        {tickets === null ? (
          <p className="mt-2 text-caption text-ink-3">Loading…</p>
        ) : tickets.length === 0 ? (
          <p className="mt-2 text-caption text-ink-3">You haven&apos;t sent any messages from this workspace yet.</p>
        ) : (
          <ul className="mt-2 divide-y divide-line-soft rounded-xl border border-line">
            {tickets.map((t) => (
              <li key={t.reference} className="flex items-center gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body text-foreground">{t.subject}</p>
                  <p className="text-meta text-ink-3">
                    <span className="font-mono">{t.reference}</span> · {categoryLabel(t.category)} · {formatDate(t.created_at)}
                  </p>
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-2 py-0.5 text-meta font-medium",
                    t.status === "open" ? "bg-amber-dim text-amber" : "bg-brand-dim text-brand",
                  )}
                >
                  {TICKET_STATUS_LABELS[t.status] ?? t.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2 border-t border-line pt-4">
        <h3 className="text-meta font-medium uppercase tracking-wide text-ink-3">Other ways to reach us</h3>
        <a
          href={SUPPORT_MAILTO}
          className="flex items-center gap-2 text-body font-medium text-foreground hover:underline"
        >
          <Mail className="size-4 text-ink-3" aria-hidden />
          Email us
        </a>
        <a
          href={CONTACT_FORM_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 text-body font-medium text-foreground hover:underline"
        >
          <ExternalLink className="size-4 text-ink-3" aria-hidden />
          Contact form on our website
          <span className="sr-only">(opens in a new tab)</span>
        </a>
        <p className="text-caption text-ink-3">For questions that aren&apos;t about this workspace, such as sales or partnerships.</p>
      </section>
    </div>
  );
}
