"""Transactional email bodies. Every interpolated value is HTML-escaped."""

from html import escape

from api.constants import BRAND_NAME
from api.services.email.base import EmailMessage

PRODUCT_NAME = BRAND_NAME


def _page(heading: str, content_html: str) -> str:
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f6f7f9;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#111">
<table role="presentation" width="100%" style="max-width:520px;margin:0 auto;background:#fff;border-radius:8px;padding:32px">
<tr><td>
<h1 style="font-size:20px;margin:0 0 16px">{escape(heading)}</h1>
{content_html}
</td></tr></table></body></html>"""


def _layout(heading: str, body_html: str, action_label: str, action_url: str) -> str:
    return _page(
        heading,
        f"""{body_html}
<p style="margin:24px 0"><a href="{escape(action_url, quote=True)}" style="background:#111;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;display:inline-block">{escape(action_label)}</a></p>
<p style="font-size:12px;color:#666">If the button doesn't work, paste this link into your browser:<br>{escape(action_url)}</p>""",
    )


def invitation_email(
    *,
    to: str,
    organization_name: str,
    inviter_name: str | None,
    role_label: str,
    accept_url: str,
    expires_in_days: int,
) -> EmailMessage:
    who = inviter_name or "A teammate"
    subject = f"{who} invited you to {organization_name} on {PRODUCT_NAME}"
    text = (
        f"{who} invited you to join {organization_name} on {PRODUCT_NAME} as {role_label}.\n\n"
        f"Accept the invitation: {accept_url}\n\n"
        f"This link expires in {expires_in_days} days. If you weren't expecting "
        "it, you can ignore this email."
    )
    body = (
        f"<p>{escape(who)} invited you to join <strong>{escape(organization_name)}"
        f"</strong> on {PRODUCT_NAME} as <strong>{escape(role_label)}</strong>.</p>"
        f'<p style="font-size:13px;color:#666">This link expires in '
        f"{expires_in_days} days. If you weren't expecting it, you can ignore "
        "this email.</p>"
    )
    return EmailMessage(
        to=to,
        subject=subject,
        text=text,
        html=_layout("You're invited", body, "Accept invitation", accept_url),
    )


def verification_code_message(
    *, to: str, code: str, expires_in_minutes: int
) -> EmailMessage:
    text = (
        f"Your {PRODUCT_NAME} verification code is {code}\n\n"
        "Enter it to finish setting up your account. "
        f"It expires in {expires_in_minutes} minutes. If you didn't sign up, "
        "you can ignore this email."
    )
    body = (
        "<p>Enter this code to finish setting up your "
        f"{PRODUCT_NAME} account:</p>"
        '<p style="margin:24px 0;font-family:ui-monospace,Menlo,Consolas,monospace;'
        'font-size:32px;font-weight:600;letter-spacing:8px">'
        f"{escape(code)}</p>"
        f'<p style="font-size:13px;color:#666">The code expires in '
        f"{expires_in_minutes} minutes. If you didn't sign up, you can ignore "
        "this email.</p>"
    )
    return EmailMessage(
        to=to,
        # Code first, so it shows in the inbox preview.
        subject=f"{code} is your {PRODUCT_NAME} verification code",
        text=text,
        html=_page("Verify your email", body),
    )


def verification_locked_message(*, to: str, reset_url: str) -> EmailMessage:
    text = (
        f"We couldn't send a new {PRODUCT_NAME} verification code: too many "
        "incorrect codes were entered for your account recently.\n\n"
        f"Reset your password to verify your email instead: {reset_url}\n\n"
        "If you didn't sign up, you can ignore this email."
    )
    body = (
        f"<p>We couldn't send a new {PRODUCT_NAME} verification code: too many "
        "incorrect codes were entered for your account recently.</p>"
        "<p>Reset your password to verify your email instead.</p>"
        '<p style="font-size:13px;color:#666">If you didn\'t sign up, you can '
        "ignore this email.</p>"
    )
    return EmailMessage(
        to=to,
        subject=f"Verify your {PRODUCT_NAME} email by resetting your password",
        text=text,
        html=_layout("Too many incorrect codes", body, "Reset password", reset_url),
    )


def password_reset_message(
    *, to: str, reset_url: str, expires_in_minutes: int
) -> EmailMessage:
    text = (
        f"Someone asked to reset the password for your {PRODUCT_NAME} account.\n\n"
        f"Choose a new password: {reset_url}\n\n"
        f"This link expires in {expires_in_minutes} minutes. If it wasn't you, "
        "ignore this email; your password stays the same."
    )
    body = (
        f"<p>Someone asked to reset the password for your {PRODUCT_NAME} account.</p>"
        f'<p style="font-size:13px;color:#666">This link expires in '
        f"{expires_in_minutes} minutes. If it wasn't you, ignore this email; "
        "your password stays the same.</p>"
    )
    return EmailMessage(
        to=to,
        subject=f"Reset your {PRODUCT_NAME} password",
        text=text,
        html=_layout("Reset your password", body, "Choose a new password", reset_url),
    )


def low_balance_message(
    *,
    to: str,
    organization_name: str,
    balance: str,
    out_of_credit: bool,
    billing_url: str,
) -> EmailMessage:
    if out_of_credit:
        subject = f"{organization_name} is out of call credit on {PRODUCT_NAME}"
        heading = "You're out of call credit"
        summary = (
            f"{organization_name} has {balance} of call credit left, which is not "
            "enough to start a call. New calls are paused until you top up."
        )
    else:
        subject = f"{organization_name} is running low on call credit"
        heading = "Call credit is running low"
        summary = (
            f"{organization_name} has {balance} of call credit left on "
            f"{PRODUCT_NAME}. Top up now to keep your agents taking calls."
        )
    text = f"{summary}\n\nAdd credit: {billing_url}\n"
    body = f"<p>{escape(summary)}</p>"
    return EmailMessage(
        to=to,
        subject=subject,
        text=text,
        html=_layout(heading, body, "Add credit", billing_url),
    )
