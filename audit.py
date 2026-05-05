"""Append-only audit log of every provisioning action.

Each line is tab-separated to keep parsing trivial in shell. We record
who was provisioned and which delivery channels succeeded — but never
the secret itself, which would defeat the point of an audit log.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterable


_AUDIT_HEADERS = (
    "timestamp",
    "actor",
    "practitioner_no",
    "full_name",
    "accounts_updated",
    "email_sent_to",
    "nextcloud_copy",
    "dry_run",
    "notes",
)


def write_event(
    log_dir: str,
    *,
    actor: str,
    practitioner_no: str,
    full_name: str,
    accounts_updated: int,
    email_sent_to: str,
    nextcloud_copy: str,
    dry_run: bool,
    notes: str = "",
) -> Path:
    """Append a single audit row. Creates the log file with header if absent."""
    log_path = Path(log_dir) / "provision.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not log_path.exists()

    fields: Iterable[str] = (
        datetime.now().isoformat(timespec="seconds"),
        actor,
        practitioner_no,
        full_name,
        str(accounts_updated),
        email_sent_to or "-",
        nextcloud_copy or "-",
        "yes" if dry_run else "no",
        notes.replace("\t", " ").replace("\n", " "),
    )

    with log_path.open("a", encoding="utf-8") as f:
        if new_file:
            f.write("\t".join(_AUDIT_HEADERS) + "\n")
        f.write("\t".join(fields) + "\n")

    # Tighten perms once on first creation; the file may contain user names
    # and email addresses, so it's not as sensitive as the secret, but no
    # reason for it to be world-readable.
    if new_file:
        try:
            os.chmod(log_path, 0o640)
        except OSError:
            pass

    return log_path
