import asyncio
import smtplib
import ssl
from email.message import EmailMessage as MimeMessage

from api.services.email.base import EmailDeliveryError, EmailMessage
from api.services.email.settings import SmtpSecurity, SmtpSettings


class SmtpEmailSender:
    """Sends through any SMTP relay (Gmail/Workspace, SES, Mailpit, ...).

    Uses the standard library client in a worker thread to keep the event loop
    free without adding a dependency.
    """

    def __init__(self, settings: SmtpSettings, from_address: str) -> None:
        self._settings = settings
        self._from = from_address

    @property
    def delivers(self) -> bool:
        return True

    async def send(self, message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"] = self._from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        try:
            await asyncio.to_thread(self._deliver, mime)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(f"SMTP delivery failed: {exc}") from exc

    def _deliver(self, mime: MimeMessage) -> None:
        s = self._settings
        context = ssl.create_default_context()
        smtp: smtplib.SMTP
        if s.security is SmtpSecurity.SSL:
            smtp = smtplib.SMTP_SSL(
                s.host, s.port, timeout=s.timeout_seconds, context=context
            )
        else:
            smtp = smtplib.SMTP(s.host, s.port, timeout=s.timeout_seconds)
        with smtp:
            if s.security is SmtpSecurity.STARTTLS:
                smtp.starttls(context=context)
            if s.username and s.password:
                smtp.login(s.username, s.password.get_secret_value())
            smtp.send_message(mime)
