"""TOTP secret generation and otpauth:// URI construction.

The secret format matches what's already in the security table and what
oathtool / 2FA_gen.sh consume: lowercase base32, no padding, ~52 chars
(= 32 random bytes encoded).
"""

from __future__ import annotations

import base64
import secrets
from urllib.parse import quote


def generate_secret(num_bytes: int = 32) -> str:
    """Generate a fresh random base32-encoded secret.

    32 random bytes -> 52 base32 chars after stripping padding. This
    matches the secret length seen in existing rows of the security table
    and gives 256 bits of entropy, which is well above the 160-bit
    recommendation for TOTP (RFC 6238).
    """
    raw = secrets.token_bytes(num_bytes)
    encoded = base64.b32encode(raw).decode("ascii").rstrip("=")
    return encoded.lower()


def build_otpauth_uri(
    secret: str,
    account: str,
    issuer: str,
    algorithm: str = "sha256",
    digits: int = 6,
    period: int = 30,
    image_url: str = "",
) -> str:
    """Build a standards-compliant otpauth:// URI for the given secret.

    The resulting URI is what gets encoded into the QR code. Authenticator
    apps parse it to add the entry; oathtool consumes equivalent values to
    verify codes server-side.

    The Account label shown to the user inside their authenticator app
    follows the otpauth convention `Issuer:Account`. We pass the secret
    in upper-case (canonical) and otherwise URL-encode every component
    that may contain spaces, commas, or other reserved characters.
    """
    # Most authenticator apps display the secret in upper case, and RFC
    # 6238 reference implementations expect upper-case base32 in the URI
    # itself. Our DB / oathtool layer handles either case transparently.
    secret_canonical = secret.upper()

    label = f"{issuer}:{account}"
    params = [
        f"secret={secret_canonical}",
        f"issuer={quote(issuer, safe='')}",
        f"algorithm={algorithm.upper()}",
        f"digits={digits}",
        f"period={period}",
    ]
    if image_url:
        params.append(f"image={quote(image_url, safe='')}")

    return f"otpauth://totp/{quote(label, safe='')}?{'&'.join(params)}"
