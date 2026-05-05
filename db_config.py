"""Configuration loaded from environment variables (with .env support).

All settings live in environment variables so the same code runs unchanged
in development, on Helium, and under cron. Values are read once at import
time; the rest of the codebase imports them as constants.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Load .env from the script's directory (no-op if variables are already set
# in the execution environment, e.g. when launched from systemd or cron with
# explicit env entries).
load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    """Parse a truthy environment string into a bool."""
    raw = os.getenv(name, "")
    if raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}")


def _required(name: str) -> str:
    val = os.getenv(name, "")
    if val == "":
        raise RuntimeError(
            f"{name} is required but not set. Copy .env.sample to .env and "
            f"populate it, or export the variable in your shell."
        )
    return val


# --- Database ----------------------------------------------------------------
DB_USER = _required("DB_USER")
DB_SECRET = _required("DB_SECRET")
DB_HOST = _required("DB_HOST")
DB_PORT = _int("DB_PORT", 3306)
DB_DATABASE = os.getenv("DB_DATABASE", "oscar_15")
DB_COMPRESS = _bool("DB_COMPRESS", True)

# --- SSH tunnel --------------------------------------------------------------
SSH_ENABLED = _bool("SSH_ENABLED", False)
SSH_DB_HOST = os.getenv("SSH_DB_HOST", "127.0.0.1")
SSH_USER = os.getenv("SSH_USER", "root")
SSH_PORT = _int("SSH_PORT", 22)
PKEY_FILE = os.getenv("PKEY_FILE", "")
CERT_SECRET = os.getenv("CERT_SECRET", "") or None

# --- SMTP --------------------------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = _int("SMTP_PORT", 465)
SMTP_MODE = os.getenv("SMTP_MODE", "ssl").strip().lower()
if SMTP_MODE not in ("ssl", "starttls", "plain"):
    raise RuntimeError(
        f"SMTP_MODE must be one of 'ssl', 'starttls', 'plain'; got {SMTP_MODE!r}"
    )
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_ADDR = os.getenv("FROM_ADDR", "")
FROM_FRIENDLY = os.getenv("FROM_FRIENDLY", "IT Support")

# --- TOTP defaults -----------------------------------------------------------
TOTP_ISSUER = os.getenv("TOTP_ISSUER", "OSCAR EMR")
TOTP_ALGORITHM = os.getenv("TOTP_ALGORITHM", "sha256").strip().lower()
TOTP_DIGITS = _int("TOTP_DIGITS", 6)
TOTP_PERIOD = _int("TOTP_PERIOD", 30)
TOTP_IMAGE_URL = os.getenv("TOTP_IMAGE_URL", "")

# --- Document content --------------------------------------------------------
OSCAR_LOGIN_URL = os.getenv(
    "OSCAR_LOGIN_URL", "https://your-oscar-host:8443/oscar"
)
INITIAL_PASSWORD = os.getenv("INITIAL_PASSWORD", "Qwerty123")
CLINIC_ADMIN_CONTACT = os.getenv(
    "CLINIC_ADMIN_CONTACT", "your clinic administrator"
)

# --- Output destinations -----------------------------------------------------
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./output")
NEXTCLOUD_DIR = os.getenv("NEXTCLOUD_DIR", "")  # optional
LOG_DIR = os.getenv("LOG_DIR", "./logs")

# --- Misc --------------------------------------------------------------------
VERBOSE = _int("VERBOSE", 1)
