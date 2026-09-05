"""
Email delivery layer. This is the SMS -> Email adaptation called for by the
spec: every place the reference product would have sent an SMS (OTP,
alerts, notifications), Reparo AI sends an email instead, through this one
function.

If SMTP_HOST is not configured (local dev), the email is logged to the
backend console instead of failing, so signup/OTP flows are testable
without setting up a real mail provider. Configure SMTP_* in .env to send
real email.
"""
import smtplib
from email.mime.text import MIMEText

from app.config import get_settings

settings = get_settings()


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        print(f"\n[reparo-ai email:dev-mode] To: {to}\nSubject: {subject}\n\n{body}\n")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = to

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.email_from, [to], msg.as_string())


def send_otp_email(to: str, code: str, purpose: str = "signup") -> None:
    subject = "Your Reparo AI verification code"
    body = (
        f"Your verification code is: {code}\n\n"
        f"This code expires in 10 minutes. If you did not request this, you can ignore this email.\n\n"
        f"— Reparo AI"
    )
    send_email(to, subject, body)


def send_notification_email(to: str, subject: str, message: str) -> None:
    send_email(to, subject, message)
