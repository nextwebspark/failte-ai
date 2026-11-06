"""The report email: HTML for Gmail, Outlook and Apple Mail, plus a plain
text part. Pure: everything comes in through ``Report`` and the links.

Email clients need tables and inline styles. Charts are table cells with a
height and a background colour (no SVG, no scripts, no images). A
``prefers-color-scheme`` block restyles the same cells for dark mode where
the client supports it (Apple Mail, Outlook for Mac/iOS); Gmail and Outlook
on Windows apply their own dark adjustments to the light version, which the
colours below survive. Every interpolated value is HTML-escaped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape

from api.constants import BRAND_NAME
from api.services.email.base import EmailMessage
from api.services.email_reports.content import Bar, Report
from api.services.email_reports.formatting import (
    change_text,
    clock,
    day_label,
    duration_text,
    euro,
    hour_label,
    mask_phone,
    period_subtitle,
    period_title,
    plural,
    report_name,
    short_day,
)
from api.services.email_reports.periods import Frequency

# Brand (brand-kit/lightmove-brand, ui/src/app/globals.css).
BRAND = "#0e7a4b"
BRAND_FILL = "#169b62"
BRAND_WASH = "#e7f3ed"
BG = "#f3f5f4"
CARD = "#ffffff"
INK = "#0b0d12"
INK_2 = "#3a414d"
INK_3 = "#596170"
LINE = "#e3e7ea"
AMBER = "#8d5d06"
AMBER_WASH = "#fbf3e2"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

CHART_HEIGHT = 72

NOT_ANSWERING = {
    "no_credit": (
        "Your agent isn't answering calls right now: there isn't enough credit "
        "to start a call. Add credit to switch it back on."
    ),
    "no_number": "No phone number is linked to your agent yet, so it can't take calls.",
    "number_off": "Your phone number is switched off, so calls aren't reaching your agent.",
    "agent_off": "Your agent is switched off, so it isn't answering calls.",
    "no_agent": "There's no agent set up in this workspace yet.",
}

FOLLOW_UP_KIND = {
    "callback": "Asked to be called back",
    "transfer_not_answered": "Wanted a person, nobody picked up",
    "repeat_caller": "Rang more than once, reached nobody",
}

_DARK_CSS = """
:root { color-scheme: light dark; supported-color-schemes: light dark; }
@media (prefers-color-scheme: dark) {
  .lm-bg { background-color:#08090b !important; }
  .lm-card { background-color:#0e1013 !important; border-color:#23272e !important; }
  .lm-tile { background-color:#151a1f !important; border-color:#23272e !important; }
  .lm-ink { color:#f4f6f8 !important; }
  .lm-ink2 { color:#c3c9d1 !important; }
  .lm-ink3 { color:#9aa3ae !important; }
  .lm-brand { color:#3ddc97 !important; }
  .lm-bar { background-color:#3ddc97 !important; }
  .lm-track { background-color:#1b2a23 !important; }
  .lm-line { border-color:#23272e !important; }
  .lm-note { background-color:#2a2110 !important; color:#f2c46b !important; }
  .lm-button { background-color:#3ddc97 !important; color:#0a1f17 !important; }
}
@media only screen and (max-width:480px) {
  .lm-pad { padding-left:18px !important; padding-right:18px !important; }
  .lm-h1 { font-size:20px !important; }
  .lm-num { font-size:24px !important; }
}
"""


@dataclass(frozen=True, slots=True)
class Links:
    dashboard: str
    follow_ups: str
    manage: str
    unsubscribe: str
    # RFC 8058 one-click endpoint (POST), for the List-Unsubscribe header.
    one_click: str | None = None
    billing: str | None = None
    # Overrides the footer's "why you got this" (previews and tests).
    why: str | None = None


def subject(report: Report) -> str:
    when = period_title(report.period)
    if report.period.frequency == Frequency.WEEKLY:
        when = f"Week of {when}"
    if report.calls == 0:
        return f"{report.business_name} · {when}: no calls"
    return (
        f"{report.business_name} · {when}: {plural(report.calls, 'call')}, "
        f"{report.handled} handled by your agent"
    )


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _section_title(text: str) -> str:
    return (
        f'<tr><td class="lm-pad" style="padding:22px 28px 8px">'
        f'<p class="lm-ink" style="margin:0;font-family:{FONT};font-size:15px;'
        f'font-weight:700;color:{INK}">{_e(text)}</p></td></tr>'
    )


def _tile(label: str, value: str, note: str | None) -> str:
    note_html = (
        f'<p class="lm-ink3" style="margin:4px 0 0;font-size:12px;line-height:16px;'
        f'color:{INK_3}">{_e(note)}</p>'
        if note
        else ""
    )
    return (
        f'<td class="lm-tile" width="50%" valign="top" style="padding:14px 14px 12px;'
        f"background-color:#f7f8fa;border:1px solid {LINE};border-radius:10px;"
        f'font-family:{FONT}">'
        f'<p class="lm-ink2" style="margin:0;font-size:12.5px;line-height:16px;color:{INK_2}">'
        f"{_e(label)}</p>"
        f'<p class="lm-ink lm-num" style="margin:6px 0 0;font-size:28px;line-height:32px;'
        f'font-weight:700;color:{INK}">{_e(value)}</p>'
        f"{note_html}</td>"
    )


def _tiles(report: Report) -> str:
    total = report.calls
    handled_note = f"{round(report.handled * 100 / total)}% of calls" if total else None
    change = change_text(report.calls_change, report.period.frequency)
    gap = '<td width="10" style="width:10px;font-size:0;line-height:0">&nbsp;</td>'
    row_gap = '<tr><td colspan="3" height="10" style="height:10px;font-size:0;line-height:0">&nbsp;</td></tr>'
    return (
        '<tr><td class="lm-pad" style="padding:18px 28px 0">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"<tr>{_tile('Calls', str(total), change)}{gap}"
        f"{_tile('Handled by your agent', str(report.handled), handled_note)}</tr>"
        f"{row_gap}"
        f"<tr>{_tile('Passed to your team', str(report.passed_to_team), None)}{gap}"
        f"{_tile('Hung up without speaking', str(report.hung_up_silent), None)}</tr>"
        "</table></td></tr>"
    )


def _facts_row(report: Report) -> str:
    parts = [f"Bookings made: <strong>{report.bookings}</strong>"]
    average = duration_text(report.average_call_seconds)
    if average:
        parts.append(f"Average call: <strong>{_e(average)}</strong>")
    joined = " &nbsp;·&nbsp; ".join(parts)
    return (
        f'<tr><td class="lm-pad lm-ink2" style="padding:14px 28px 0;font-family:{FONT};'
        f'font-size:14px;line-height:20px;color:{INK_2}">{joined}</td></tr>'
    )


def _note(text: str) -> str:
    return (
        f'<tr><td class="lm-pad" style="padding:18px 28px 0">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td class="lm-note" style="padding:12px 14px;border-radius:8px;'
        f"background-color:{AMBER_WASH};color:{AMBER};font-family:{FONT};font-size:14px;"
        f'line-height:20px">{_e(text)}</td></tr></table></td></tr>'
    )


def _follow_ups(report: Report, links: Links) -> str:
    count = report.open_follow_ups
    if count == 0:
        body = (
            f'<p class="lm-ink2" style="margin:0;font-family:{FONT};font-size:14px;'
            f'color:{INK_2}">Nothing waiting. Every caller who needed a person has been dealt with.</p>'
        )
        return _section_title("Needs your attention") + (
            f'<tr><td class="lm-pad" style="padding:0 28px">{body}</td></tr>'
        )
    rows = []
    for item in report.follow_ups:
        who = item.caller_name or mask_phone(item.caller_number)
        number = mask_phone(item.caller_number) if item.caller_name else None
        when = item.created_at.astimezone(report.tz)
        detail = item.reason or FOLLOW_UP_KIND.get(item.kind, "Needs a call back")
        meta = " · ".join(x for x in (number, f"{short_day(when)}, {clock(when)}") if x)
        rows.append(
            f'<tr><td class="lm-line" style="padding:10px 0;border-top:1px solid {LINE};'
            f'font-family:{FONT}">'
            f'<p class="lm-ink" style="margin:0;font-size:14px;line-height:20px;'
            f'font-weight:600;color:{INK}">{_e(who)}</p>'
            f'<p class="lm-ink2" style="margin:2px 0 0;font-size:13.5px;line-height:19px;'
            f'color:{INK_2}">{_e(detail)}</p>'
            f'<p class="lm-ink3" style="margin:2px 0 0;font-size:12px;line-height:16px;'
            f'color:{INK_3}">{_e(meta)}</p></td></tr>'
        )
    more = (
        f'<p style="margin:10px 0 0;font-family:{FONT};font-size:13.5px">'
        f'<a class="lm-brand" href="{_e(links.follow_ups)}" style="color:{BRAND};'
        f'font-weight:600;text-decoration:underline">See all {count} in Follow-ups</a></p>'
    )
    intro = (
        f'<p class="lm-ink2" style="margin:0 0 8px;font-family:{FONT};font-size:14px;'
        f'color:{INK_2}">{_e(plural(count, "caller"))} still '
        f"{'needs' if count == 1 else 'need'} a call back.</p>"
    )
    return _section_title("Needs your attention") + (
        f'<tr><td class="lm-pad" style="padding:0 28px">{intro}'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"{''.join(rows)}</table>{more}</td></tr>"
    )


def _reason_bars(bars: list[Bar]) -> str:
    top = max(b.count for b in bars)
    rows = []
    for bar in bars:
        width = max(2, round(bar.count * 100 / top))
        rows.append(
            f'<tr><td style="padding:6px 0 0;font-family:{FONT}">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td class="lm-ink2" style="font-size:13.5px;line-height:18px;color:{INK_2}">{_e(bar.label)}</td>'
            f'<td class="lm-ink" align="right" style="font-size:13.5px;font-weight:700;color:{INK};'
            f'white-space:nowrap">{bar.count}</td></tr></table>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="margin-top:4px"><tr>'
            f'<td class="lm-bar" width="{width}%" height="8" style="height:8px;font-size:0;'
            f'line-height:0;background-color:{BRAND_FILL};border-radius:4px">&nbsp;</td>'
            + (
                f'<td class="lm-track" width="{100 - width}%" height="8" style="height:8px;'
                f'font-size:0;line-height:0;background-color:{BRAND_WASH};border-radius:4px">&nbsp;</td>'
                if width < 100
                else ""
            )
            + "</tr></table></td></tr>"
        )
    return (
        _section_title("What callers wanted")
        + '<tr><td class="lm-pad" style="padding:0 28px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"{''.join(rows)}</table></td></tr>"
    )


def _bar_labels(report: Report) -> list[str]:
    bars = report.when
    frequency = report.period.frequency
    if frequency == Frequency.DAILY:
        return [hour_label(int(b.label)) if int(b.label) % 3 == 0 else "" for b in bars]
    days = [date.fromisoformat(b.label) for b in bars]
    if frequency == Frequency.WEEKLY:
        return [d.strftime("%a") for d in days]
    return [str(d.day) if d.day in (1, 8, 15, 22, 29) else "" for d in days]


def _column_chart(report: Report) -> str:
    bars = report.when
    top = max([b.count for b in bars] + [1])
    width = f"{100 / len(bars):.2f}%"
    columns, labels = [], []
    for bar, label in zip(bars, _bar_labels(report), strict=True):
        height = round(bar.count * CHART_HEIGHT / top) if bar.count else 0
        fill = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td class="lm-bar" height="{height}" style="height:{height}px;font-size:0;line-height:0;'
            f'background-color:{BRAND_FILL};border-radius:3px 3px 0 0">&nbsp;</td></tr></table>'
            if height
            else ""
        )
        columns.append(
            f'<td width="{width}" valign="bottom" height="{CHART_HEIGHT}" '
            f'style="height:{CHART_HEIGHT}px;padding:0 1px">{fill}</td>'
        )
        labels.append(
            f'<td class="lm-ink3" width="{width}" align="center" style="padding-top:4px;'
            f"font-family:{FONT};font-size:10px;line-height:12px;color:{INK_3};"
            f'white-space:nowrap">{_e(label)}</td>'
        )
    busiest = max(bars, key=lambda b: b.count)
    if report.period.frequency == Frequency.DAILY:
        peak = f"Busiest hour: {hour_label(int(busiest.label))} ({plural(busiest.count, 'call')})."
    else:
        peak_day = date.fromisoformat(busiest.label)
        peak = f"Busiest day: {day_label(peak_day)} ({plural(busiest.count, 'call')})."
    return (
        _section_title("When people called")
        + '<tr><td class="lm-pad" style="padding:0 28px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'class="lm-line" style="border-bottom:1px solid {LINE}"><tr>{"".join(columns)}</tr></table>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"<tr>{''.join(labels)}</tr></table>"
        f'<p class="lm-ink3" style="margin:8px 0 0;font-family:{FONT};font-size:12.5px;'
        f'color:{INK_3}">{_e(peak)}</p></td></tr>'
    )


def _credit(report: Report, links: Links) -> str:
    credit = report.credit
    if not credit:
        return ""
    minutes = credit.get("minutes_left")
    line = f"{euro(credit['spendable_eur'])} left"
    if minutes is not None:
        line += f", about {plural(int(minutes), 'minute')} of calls"
    note = ""
    if credit.get("running_low") and links.billing:
        note = (
            f' <a class="lm-brand" href="{_e(links.billing)}" style="color:{BRAND};'
            f'font-weight:600">Add credit</a>'
        )
    return _section_title("Call credit") + (
        f'<tr><td class="lm-pad lm-ink2" style="padding:0 28px;font-family:{FONT};'
        f'font-size:14px;color:{INK_2}">{_e(line)}.{note}</td></tr>'
    )


def _no_calls(report: Report) -> str:
    frequency = report.period.frequency
    span = {
        Frequency.DAILY: f"between midnight and {clock(report.period.end.astimezone(report.tz))}",
        Frequency.WEEKLY: "this week",
        Frequency.MONTHLY: "this month",
    }[frequency]
    if report.not_answering:
        text = f"Nobody rang {span}."
    else:
        text = f"Nobody rang {span}. Your agent is switched on and answering, so it's just been quiet."
    heading = {
        Frequency.DAILY: "No calls today",
        Frequency.WEEKLY: "No calls this week",
        Frequency.MONTHLY: "No calls this month",
    }[frequency]
    if not report.period.complete:
        heading = "No calls yet today"
    return (
        f'<tr><td class="lm-pad" style="padding:20px 28px 0;font-family:{FONT}">'
        f'<p class="lm-ink" style="margin:0;font-size:18px;font-weight:700;color:{INK}">{_e(heading)}</p>'
        f'<p class="lm-ink2" style="margin:6px 0 0;font-size:14px;line-height:20px;color:{INK_2}">'
        f"{_e(text)}</p></td></tr>"
    )


def _button(label: str, url: str) -> str:
    return (
        '<tr><td class="lm-pad" align="left" style="padding:26px 28px 0">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td class="lm-button" bgcolor="{BRAND}" style="border-radius:8px;background-color:{BRAND}">'
        f'<a class="lm-button" href="{_e(url)}" style="display:inline-block;padding:12px 22px;'
        f"font-family:{FONT};font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;"
        f'border-radius:8px;background-color:{BRAND}">{_e(label)}</a></td></tr></table></td></tr>'
    )


def _footer(report: Report, to: str, links: Links) -> str:
    why = links.why or (
        f"You're getting this {report_name(report.period.frequency)} because {to} was "
        f"added to {report.business_name}'s reports on {BRAND_NAME}."
    )
    return (
        f'<tr><td class="lm-pad lm-line" style="padding:22px 28px 26px;margin-top:22px;'
        f"border-top:1px solid {LINE};font-family:{FONT};font-size:12px;line-height:18px;"
        f'color:{INK_3}"><p class="lm-ink3" style="margin:0;color:{INK_3}">{_e(why)}</p>'
        f'<p style="margin:8px 0 0"><a class="lm-brand" href="{_e(links.manage)}" '
        f'style="color:{BRAND};text-decoration:underline">Manage reports</a>'
        f'<span class="lm-ink3" style="color:{INK_3}"> &nbsp;·&nbsp; </span>'
        f'<a class="lm-brand" href="{_e(links.unsubscribe)}" '
        f'style="color:{BRAND};text-decoration:underline">Unsubscribe</a></p></td></tr>'
    )


def render_html(report: Report, *, to: str, links: Links) -> str:
    title = period_title(report.period)
    eyebrow = report_name(report.period.frequency).capitalize()
    if report.agent_name:
        eyebrow += f" · {report.agent_name}"
    sections = [
        (
            f'<tr><td class="lm-pad" style="padding:26px 28px 0;font-family:{FONT}">'
            f'<p class="lm-brand" style="margin:0;font-size:12px;font-weight:700;letter-spacing:.06em;'
            f'text-transform:uppercase;color:{BRAND}">{_e(eyebrow)}</p>'
            f'<h1 class="lm-ink lm-h1" style="margin:6px 0 0;font-size:24px;line-height:30px;'
            f'font-weight:700;color:{INK}">{_e(report.business_name)}</h1>'
            f'<p class="lm-ink2" style="margin:4px 0 0;font-size:15px;line-height:21px;color:{INK_2}">'
            f"{_e(title)} &nbsp;·&nbsp; {_e(period_subtitle(report.period))}</p></td></tr>"
        )
    ]
    if report.not_answering:
        sections.append(
            _note(
                NOT_ANSWERING.get(
                    report.not_answering, "Your agent isn't answering calls right now."
                )
            )
        )
    if report.calls == 0:
        sections.append(_no_calls(report))
    else:
        sections.append(_tiles(report))
        sections.append(_facts_row(report))
    sections.append(_follow_ups(report, links))
    if report.calls and report.callers_wanted:
        sections.append(_reason_bars(report.callers_wanted))
    if report.calls:
        sections.append(_column_chart(report))
    sections.append(_credit(report, links))
    sections.append(_button("Open your dashboard", links.dashboard))
    sections.append(
        '<tr><td height="26" style="height:26px;font-size:0;line-height:0">&nbsp;</td></tr>'
    )
    sections.append(_footer(report, to, links))
    preheader = subject(report)
    return f"""<!doctype html>
<html lang="en-IE" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{_e(preheader)}</title>
<style>{_DARK_CSS}</style>
</head>
<body class="lm-bg" style="margin:0;padding:0;background-color:{BG};-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{_e(preheader)}</div>
<table role="presentation" class="lm-bg" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{BG}">
<tr><td align="center" style="padding:24px 12px">
<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" class="lm-card" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background-color:{CARD};border:1px solid {LINE};border-radius:14px">
{"".join(sections)}
</table>
<p class="lm-ink3" style="margin:14px 0 0;font-family:{FONT};font-size:11px;color:{INK_3}">{_e(BRAND_NAME)}</p>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body></html>"""


def render_text(report: Report, *, to: str, links: Links) -> str:
    period = report.period
    lines = [
        f"{report.business_name}: {report_name(period.frequency)}",
        f"{period_title(period)} ({period_subtitle(period)})",
        "",
    ]
    if report.not_answering:
        lines += [
            NOT_ANSWERING.get(
                report.not_answering, "Your agent isn't answering calls."
            ),
            "",
        ]
    if report.calls == 0:
        lines += ["No calls in this period.", ""]
    else:
        change = change_text(report.calls_change, period.frequency)
        lines += [
            f"Calls: {report.calls}" + (f" ({change})" if change else ""),
            f"Handled by your agent: {report.handled}",
            f"Passed to your team: {report.passed_to_team}",
            f"Hung up without speaking: {report.hung_up_silent}",
            f"Bookings made: {report.bookings}",
        ]
        average = duration_text(report.average_call_seconds)
        if average:
            lines.append(f"Average call: {average}")
        lines.append("")
    lines.append("Needs your attention")
    if report.open_follow_ups == 0:
        lines.append("Nothing waiting.")
    else:
        lines.append(
            f"{plural(report.open_follow_ups, 'caller')} waiting for a call back:"
        )
        for item in report.follow_ups:
            who = item.caller_name or mask_phone(item.caller_number)
            detail = item.reason or FOLLOW_UP_KIND.get(item.kind, "Needs a call back")
            lines.append(f"- {who}: {detail}")
        lines.append(f"All follow-ups: {links.follow_ups}")
    lines.append("")
    if report.calls and report.callers_wanted:
        lines.append("What callers wanted")
        lines += [f"- {b.label}: {b.count}" for b in report.callers_wanted]
        lines.append("")
    if report.credit:
        lines.append(f"Call credit: {euro(report.credit['spendable_eur'])} left")
        lines.append("")
    lines += [
        f"Open your dashboard: {links.dashboard}",
        "",
        links.why
        or f"You're getting this because {to} was added to {report.business_name}'s reports.",
        f"Manage reports: {links.manage}",
        f"Unsubscribe: {links.unsubscribe}",
    ]
    return "\n".join(lines) + "\n"


def report_message(
    report: Report, *, to: str, links: Links, idempotency_key: str | None = None
) -> EmailMessage:
    headers: list[tuple[str, str]] = []
    if links.one_click:
        headers.append(("List-Unsubscribe", f"<{links.one_click}>"))
        headers.append(("List-Unsubscribe-Post", "List-Unsubscribe=One-Click"))
    return EmailMessage(
        to=to,
        subject=subject(report),
        text=render_text(report, to=to, links=links),
        html=render_html(report, to=to, links=links),
        idempotency_key=idempotency_key,
        headers=tuple(headers),
    )


def confirmation_message(
    *, to: str, business_name: str, added_by: str | None, confirm_url: str, hours: int
) -> EmailMessage:
    who = added_by or "Someone"
    text = (
        f"{who} would like to send {business_name}'s call reports to this address "
        f"({to}) on {BRAND_NAME}.\n\n"
        f"To start getting them, confirm here: {confirm_url}\n\n"
        f"The link works once and expires in {hours} hours. If you don't want "
        "these reports, ignore this email: nothing is sent until you confirm."
    )
    body = (
        f'<p style="margin:0 0 12px">{_e(who)} would like to send '
        f"<strong>{_e(business_name)}</strong>'s call reports to this address "
        f"({_e(to)}).</p>"
        f'<p style="margin:0 0 20px;color:{INK_2}">Nothing is sent until you confirm.</p>'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td bgcolor="{BRAND}" style="border-radius:8px;background-color:{BRAND}">'
        f'<a href="{_e(confirm_url)}" style="display:inline-block;padding:12px 22px;font-size:15px;'
        f'font-weight:700;color:#ffffff;text-decoration:none">Yes, send me reports</a></td></tr></table>'
        f'<p style="margin:20px 0 0;font-size:12px;color:{INK_3}">The link works once and expires in '
        f"{hours} hours. If you didn't expect this, ignore it.</p>"
    )
    html = f"""<!doctype html>
<html lang="en-IE"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px 12px;background-color:{BG};font-family:{FONT};color:{INK}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;margin:0 auto;background-color:{CARD};border:1px solid {LINE};border-radius:14px">
<tr><td style="padding:28px;font-size:15px;line-height:22px">
<p style="margin:0 0 6px;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{BRAND}">{_e(BRAND_NAME)}</p>
<h1 style="margin:0 0 14px;font-size:20px;line-height:26px">Confirm your email for call reports</h1>
{body}
</td></tr></table></body></html>"""
    return EmailMessage(
        to=to,
        subject=f"Confirm you'd like {business_name}'s call reports",
        text=text,
        html=html,
    )
