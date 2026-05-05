"""Distribution: email the document, copy it to Nextcloud (if configured).

This module is intentionally narrow — each function does one delivery
channel and reports back what it did. Sequencing and error handling
live in main.py.
"""

from __future__ import annotations

import shutil
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional


def send_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_mode: str,            # 'ssl' | 'starttls' | 'plain'
    smtp_user: str,
    smtp_password: str,
    from_addr: str,
    from_friendly: str,
    to_addrs: List[str],
    subject: str,
    html_body: str,
    text_body: str,
    qr_png: bytes,
    qr_cid: str,
    pdf_attachment: Optional[Path] = None,
) -> None:
    """Send a multipart/alternative email with an inline QR + optional PDF."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_friendly} <{from_addr}>" if from_friendly else from_addr
    msg["To"] = ", ".join(to_addrs)

    # Plain-text part first (RFC requirement: simplest part first).
    msg.set_content(text_body)

    # HTML alternative; references the QR via cid:.
    msg.add_alternative(html_body, subtype="html")

    # Attach the QR PNG inline so the HTML <img src="cid:..."> resolves.
    # Setting it on the *html part* (not the top-level message) is what
    # makes most clients treat it as an inline embed rather than a regular
    # attachment.
    html_part = msg.get_payload()[1]
    html_part.add_related(
        qr_png, maintype="image", subtype="png", cid=f"<{qr_cid}>"
    )

    # PDF attachment: a separate, downloadable copy of the same content.
    if pdf_attachment is not None and pdf_attachment.exists():
        msg.add_attachment(
            pdf_attachment.read_bytes(),
            maintype="application",
            subtype="pdf",
            filename=pdf_attachment.name,
        )

    # Open the appropriate flavour of SMTP connection.
    if smtp_mode == "ssl":
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as s:
            if smtp_user:
                s.login(smtp_user, smtp_password)
            s.send_message(msg)
    elif smtp_mode == "starttls":
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls(context=ssl.create_default_context())
            if smtp_user:
                s.login(smtp_user, smtp_password)
            s.send_message(msg)
    else:  # plain
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            if smtp_user:
                s.login(smtp_user, smtp_password)
            s.send_message(msg)


def copy_to_nextcloud(pdf_path: Path, nextcloud_dir: str) -> Optional[Path]:
    """Copy `pdf_path` into `nextcloud_dir` if the dir is set and exists.

    Returns the destination path on success, or None if the destination
    isn't configured. Raises if it's configured but unwritable.
    """
    if not nextcloud_dir:
        return None
    dest_dir = Path(nextcloud_dir)
    if not dest_dir.exists():
        raise FileNotFoundError(
            f"NEXTCLOUD_DIR is set to {nextcloud_dir} but the directory "
            f"doesn't exist on this host."
        )
    if not dest_dir.is_dir():
        raise NotADirectoryError(f"NEXTCLOUD_DIR {nextcloud_dir} is not a directory.")
    dest = dest_dir / pdf_path.name
    shutil.copy2(pdf_path, dest)
    return dest
