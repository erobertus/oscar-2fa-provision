"""QR code rendering helpers.

Produces a PNG of the otpauth URI either as in-memory bytes (for
embedding into HTML/PDF as a data URI) or written to a file.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def render_qr_png_bytes(data: str, box_size: int = 8, border: int = 2) -> bytes:
    """Render `data` as a QR code PNG and return the raw bytes.

    Default error-correction level M (~15% recovery). Higher levels make
    the code denser without visible benefit for short URIs and a clean
    rendering medium.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_qr_data_uri(data: str, box_size: int = 8, border: int = 2) -> str:
    """Render a QR PNG and wrap it in a data: URI suitable for inline use."""
    png = render_qr_png_bytes(data, box_size=box_size, border=border)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def render_qr_to_file(data: str, path: Path | str, box_size: int = 8, border: int = 2) -> Path:
    """Render `data` as a QR PNG and write it to `path`. Returns Path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(render_qr_png_bytes(data, box_size=box_size, border=border))
    return p
