"""Distribution: email the document, copy it to Nextcloud (if configured).

This module is intentionally narrow — each function does one delivery
channel and reports back what it did. Sequencing and error handling
live in main.py.
"""

from __future__ import annotations

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
    pdf_bytes: Optional[bytes] = None,
    pdf_filename: str = "instructions.pdf",
    cc_addrs: Optional[List[str]] = None,
) -> None:
    """Send a multipart/alternative email with an inline QR + optional PDF.

    `cc_addrs` is an optional list of addresses to CC. They'll appear in
    the visible Cc: header (not BCC) and receive the same payload as the
    primary recipients.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_friendly} <{from_addr}>" if from_friendly else from_addr
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)

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
    # Attached from memory — the PDF need not exist anywhere on disk.
    if pdf_bytes is not None:
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=pdf_filename,
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


def save_pdf(
    pdf_bytes: bytes,
    dest_dir: str,
    filename: str,
    *,
    create_dir: bool = False,
) -> Optional[Path]:
    """Write `pdf_bytes` into `dest_dir` if the destination is configured.

    Used for both OUTPUT_DIR (create_dir=True: a local folder we own) and
    NEXTCLOUD_DIR (create_dir=False: an external mount that must already
    exist — creating it would silently write to a dead mountpoint).

    Returns the destination path on success, or None if the destination
    isn't configured. Raises if it's configured but unusable.
    """
    if not dest_dir:
        return None
    d = Path(dest_dir).expanduser()
    if create_dir:
        d.mkdir(parents=True, exist_ok=True)
    elif not d.exists():
        raise FileNotFoundError(
            f"Destination is set to {dest_dir} but the directory doesn't "
            f"exist on this host."
        )
    if not d.is_dir():
        raise NotADirectoryError(f"Destination {dest_dir} is not a directory.")
    dest = d / filename
    dest.write_bytes(pdf_bytes)
    return dest
