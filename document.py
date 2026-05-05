"""Render the instruction document.

We render the same Jinja2 template twice: once for email (with the QR
inlined as a `cid:` reference, attached separately) and once for PDF
(with the QR inlined as a base64 data URI, since WeasyPrint doesn't
need cid handling).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from jinja2 import Environment, FileSystemLoader, select_autoescape


@dataclass
class DocumentContext:
    full_name: str
    usernames: List[dict]   # list of {"user_name": ..., "team": ...}
    login_url: str
    initial_password: str
    secret_display: str
    totp_issuer: str
    totp_digits: int
    totp_period: int
    clinic_admin_contact: str


def _env() -> Environment:
    template_dir = Path(__file__).resolve().parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_html(ctx: DocumentContext, qr_src: str) -> str:
    """Render the HTML, with `qr_src` substituted into the <img>.

    `qr_src` is either a data: URI (for PDFs) or a `cid:xxx` reference
    (for email bodies). The template doesn't care which.
    """
    env = _env()
    tmpl = env.get_template("instructions.html")
    return tmpl.render(
        qr_src=qr_src,
        full_name=ctx.full_name,
        usernames=ctx.usernames,
        login_url=ctx.login_url,
        initial_password=ctx.initial_password,
        secret_display=ctx.secret_display,
        totp_issuer=ctx.totp_issuer,
        totp_digits=ctx.totp_digits,
        totp_period=ctx.totp_period,
        clinic_admin_contact=ctx.clinic_admin_contact,
    )


def render_pdf(html: str, output_path: Path) -> Path:
    """Render `html` to a PDF at `output_path` using WeasyPrint."""
    # Imported lazily so the rest of the module can be imported on systems
    # where WeasyPrint isn't (yet) installed — it has chunky native deps.
    from weasyprint import HTML

    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(Path(__file__).resolve().parent)).write_pdf(
        target=str(output_path)
    )
    return output_path


def render_plain_text(html: str) -> str:
    """Produce a plain-text fallback from the HTML body for email clients."""
    import html2text

    h = html2text.HTML2Text()
    h.body_width = 0  # don't wrap
    h.ignore_images = True
    h.ignore_links = False
    return h.handle(html)
