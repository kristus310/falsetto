import base64
import logging
from email.mime.base import MIMEBase
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend
import resend

logger = logging.getLogger(__name__)

class ResendEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, "RESEND_API_KEY", None)

        if not self.api_key:
            raise ImproperlyConfigured(
                "RESEND_API_KEY must be defined in Django settings to use the Resend email backend."
            )

        resend.api_key = self.api_key

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        sent_count = 0
        for message in email_messages:
            if self._send(message):
                sent_count += 1
        return sent_count

    def _send(self, message):
        if not message.recipients():
            return False

        try:
            params = {
                "from": message.from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "webmaster@localhost"),
                "to": list(message.to),
                "subject": message.subject,
                "text": message.body,
            }

            if message.cc:
                params["cc"] = list(message.cc)
            if message.bcc:
                params["bcc"] = list(message.bcc)

            if message.reply_to:
                params["reply_to"] = list(message.reply_to)

            html_content = None
            if hasattr(message, "alternatives") and message.alternatives:
                for content, mimetype in message.alternatives:
                    if mimetype == "text/html":
                        html_content = content
                        break

            if html_content:
                params["html"] = html_content

            attachments = []
            if message.attachments:
                for attachment in message.attachments:
                    if isinstance(attachment, tuple):
                        filename, content, mimetype = attachment
                        if isinstance(content, str):
                            content_bytes = content.encode("utf-8")
                        else:
                            content_bytes = content

                        encoded_content = base64.b64encode(content_bytes).decode("utf-8")
                        attachments.append({
                            "filename": filename,
                            "content": encoded_content,
                        })
                    elif isinstance(attachment, MIMEBase):
                        filename = attachment.get_filename() or "attachment"
                        content_bytes = attachment.get_payload(decode=True)
                        if content_bytes is not None:
                            encoded_content = base64.b64encode(content_bytes).decode("utf-8")
                            attachments.append({
                                "filename": filename,
                                "content": encoded_content,
                            })
                    else:
                        logger.warning(
                            f"Unsupported email attachment type: {type(attachment)}. Skipping attachment."
                        )

            if attachments:
                params["attachments"] = attachments

            response = resend.Emails.send(params)

            logger.info(f"Successfully sent email with Subject: '{message.subject}' via Resend. Email ID: {response.get('id', 'N/A')}")
            return True

        except Exception as e:
            logger.exception(f"Failed to send email with Subject: '{message.subject}' via Resend API: {e}")
            if not self.fail_silently:
                raise
            return False
