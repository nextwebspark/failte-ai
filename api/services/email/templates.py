"""Transactional email bodies. Every interpolated value is HTML-escaped."""

from html import escape

from api.constants import BRAND_NAME
from api.services.email.base import EmailMessage

PRODUCT_NAME = BRAND_NAME


def _layout(heading: str, body_html: str, action_label: str, action_url: str) -> str:
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f6f7f9;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#111">
<table role="presentation" width="100%" style="max-width:520px;margin:0 auto;background:#fff;border-radius:8px;padding:32px">
<tr><td>
<h1 style="font-size:20px;margin:0 0 16px">{escape(heading)}</h1>
{body_html}
<p style="margin:24px 0"><a href="{escape(action_url, quote=True)}" style="background:#111;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;display:inline-block">{escape(action_label)}</a></p>
<p style="font-size:12px;color:#666">If the button doesn't work, paste this link into your browser:<br>{escape(action_url)}</p>
</td></tr></table></body></html>"""


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


def verify_email_message(
    *, to: str, verify_url: str, expires_in_hours: int
) -> EmailMessage:
    text = (
        f"Confirm your email address to finish setting up your {PRODUCT_NAME} account.\n\n"
        f"Verify your email: {verify_url}\n\n"
        f"This link expires in {expires_in_hours} hours. If you didn't sign up, "
        "you can ignore this email."
    )
    body = (
        "<p>Confirm your email address to finish setting up your "
        f"{PRODUCT_NAME} "
        "account.</p>"
        f'<p style="font-size:13px;color:#666">This link expires in '
        f"{expires_in_hours} hours. If you didn't sign up, you can ignore this "
        "email.</p>"
    )
    return EmailMessage(
        to=to,
        subject=f"Verify your email for {PRODUCT_NAME}",
        text=text,
        html=_layout("Verify your email", body, "Verify email", verify_url),
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
