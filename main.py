"""Interactive 2FA provisioning for OSCAR EMR.

Workflow:
    1. Prompt for last-name search.
    2. Show matching person(s); prompt to pick one if multiple.
    3. Show their account(s) and current 2FA status; confirm before writing.
    4. Generate a fresh secret and update all of their security rows in
       a single transaction.
    5. Render the instruction document (HTML + PDF).
    6. Email the user (if their address is on file) and copy the PDF to
       Nextcloud (if a directory is configured).
    7. Append a row to the audit log.

Exits non-zero on any error so cron / shell wrappers can detect failure.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import uuid
from pathlib import Path
from typing import List, Optional

import db_config as cfg
from audit import write_event
from db_connection import connect_to_database
from distribute import copy_to_nextcloud, send_email
from document import DocumentContext, render_html, render_pdf, render_plain_text
from provider import Person, search_by_lastname
from qr import render_qr_png_bytes
from sql_const import BEGIN_TRAN, COMMIT_TRAN, ROLLBACK_TRAN, SQL_UPDATE_2FA
from totp import build_otpauth_uri, generate_secret


# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------
def _hr() -> None:
    print("─" * 70)


def _yn(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    while True:
        ans = input(prompt + suffix).strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  Please answer 'y' or 'n'.")


def _pick_one(prompt: str, options: List[str]) -> int:
    """Prompt the user to pick one of `options` by number. Returns 0-based index."""
    for i, label in enumerate(options, 1):
        print(f"  {i}. {label}")
    while True:
        ans = input(prompt + " ").strip()
        if ans.isdigit():
            n = int(ans)
            if 1 <= n <= len(options):
                return n - 1
        print(f"  Enter a number between 1 and {len(options)}.")


# ---------------------------------------------------------------------------
# Search → pick → confirm
# ---------------------------------------------------------------------------
def search_and_select(connection) -> Optional[Person]:
    """Run the interactive search loop until the user picks a Person or quits."""
    while True:
        query = input("Search by last name (blank to quit): ").strip()
        if not query:
            return None

        people = search_by_lastname(connection, query)
        if not people:
            print(f"  No active users found matching '{query}'.")
            continue

        if len(people) == 1:
            return people[0]

        print(f"\n  {len(people)} matches for '{query}':")
        labels = []
        for p in people:
            if p.practitioner_no and len(p.accounts) > 1:
                labels.append(
                    f"{p.full_name}  —  practitionerNo {p.practitioner_no}  "
                    f"—  {len(p.accounts)} offices"
                )
            else:
                # Standalone or single-office account
                team = f" ({p.accounts[0].team})" if p.accounts and p.accounts[0].team else ""
                user = p.accounts[0].user_name if p.accounts else "?"
                labels.append(f"{p.full_name}  —  {user}{team}")
        idx = _pick_one("  Pick one:", labels)
        return people[idx]


def show_person(person: Person) -> None:
    """Print a summary of the person and all their accounts."""
    _hr()
    print(f"  {person.full_name}")
    if person.practitioner_no:
        print(f"  practitionerNo: {person.practitioner_no}")
    else:
        print(f"  provider_no:    {person.provider_no}")
    print(f"  email:          {person.email or '(none on file)'}")
    print(f"  accounts:       {len(person.accounts)}")
    _hr()
    print(f"    {'2FA':<5} {'Username':<14}  {'Display name':<18} Office")
    for a in person.accounts:
        status = "on" if a.is_2fa_enabled else "off"
        team = f"({a.team})" if a.team else ""
        print(f"    {status:<5} {a.user_name:<14}  {a.first_name:<18} {team}")
    _hr()


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------
def update_2fa_for_person(
    connection, person: Person, secret: str, algorithm: str
) -> int:
    """Update all of `person`'s security rows in a single transaction."""
    cur = connection.cursor(buffered=True)
    autocommit_was = connection.autocommit
    connection.autocommit = False

    try:
        cur.execute(BEGIN_TRAN)
        for account in person.accounts:
            cur.execute(
                SQL_UPDATE_2FA, (secret, algorithm, account.security_no)
            )
        cur.execute(COMMIT_TRAN)
        return len(person.accounts)
    except Exception:
        try:
            cur.execute(ROLLBACK_TRAN)
        except Exception:
            pass
        raise
    finally:
        connection.autocommit = autocommit_was
        cur.close()


# ---------------------------------------------------------------------------
# Document build + distribute
# ---------------------------------------------------------------------------
def build_documents(person: Person, secret: str, output_dir: Path):
    """Render the PDF and HTML/text email bodies for a person.

    Returns: (pdf_path, email_html, qr_png_bytes, email_text, qr_cid)
    """
    # Build the otpauth URI; account label is "Lastname, Firstname".
    account_label = person.full_name
    otpauth = build_otpauth_uri(
        secret=secret,
        account=account_label,
        issuer=cfg.TOTP_ISSUER,
        algorithm=cfg.TOTP_ALGORITHM,
        digits=cfg.TOTP_DIGITS,
        period=cfg.TOTP_PERIOD,
        image_url=cfg.TOTP_IMAGE_URL,
    )

    # QR is rendered once and reused: as bytes for the email cid embed,
    # and as a base64 data URI for the PDF render.
    qr_png = render_qr_png_bytes(otpauth)
    import base64
    qr_data_uri = "data:image/png;base64," + base64.b64encode(qr_png).decode("ascii")

    # Display the secret in a human-friendly way: groups of 4 for readability,
    # but the underlying string fed to the QR remains the canonical form.
    secret_display = " ".join(
        secret.upper()[i : i + 4] for i in range(0, len(secret), 4)
    )

    ctx = DocumentContext(
        full_name=person.full_name,
        usernames=[
            {"user_name": a.user_name, "team": a.team} for a in person.accounts
        ],
        login_url=cfg.OSCAR_LOGIN_URL,
        initial_password=cfg.INITIAL_PASSWORD,
        secret_display=secret_display,
        totp_issuer=cfg.TOTP_ISSUER,
        totp_digits=cfg.TOTP_DIGITS,
        totp_period=cfg.TOTP_PERIOD,
        clinic_admin_contact=cfg.CLINIC_ADMIN_CONTACT,
    )

    # PDF: QR is embedded as a data URI so WeasyPrint doesn't need access
    # to any external file.
    pdf_html = render_html(ctx, qr_src=qr_data_uri)
    pdf_path = output_dir / f"{person.safe_filename_stem}.pdf"
    render_pdf(pdf_html, pdf_path)

    # Email: QR is referenced by cid: and attached as a related part.
    qr_cid = f"qr-{uuid.uuid4().hex}"
    email_html = render_html(ctx, qr_src=f"cid:{qr_cid}")
    email_text = render_plain_text(email_html)

    return pdf_path, email_html, qr_png, email_text, qr_cid


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interactively provision OSCAR EMR 2FA for a user.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render the document but do NOT update the DB or send email.",
    )
    parser.add_argument(
        "-s", "--ssh", dest="ssh_mode",
        choices=["on", "off", "1", "0", "true", "false"],
        help="Override SSH_ENABLED for this run.",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip sending the email even if SMTP and recipient are configured.",
    )
    args = parser.parse_args()

    # Resolve effective SSH mode
    use_ssh = cfg.SSH_ENABLED
    if args.ssh_mode is not None:
        use_ssh = args.ssh_mode.lower() in ("on", "1", "true")

    # Connect
    db_config = {
        "db_user": cfg.DB_USER,
        "db_secret": cfg.DB_SECRET,
        "db_host": cfg.DB_HOST,
        "db_port": cfg.DB_PORT,
        "db_database": cfg.DB_DATABASE,
        "db_compress": cfg.DB_COMPRESS,
        "ssh_db_host": cfg.SSH_DB_HOST,
        "ssh_user": cfg.SSH_USER,
        "ssh_port": cfg.SSH_PORT,
        "pkey_file": cfg.PKEY_FILE,
        "cert_secret": cfg.CERT_SECRET,
        "verbose": cfg.VERBOSE,
    }

    connection, tunnel = connect_to_database(use_ssh, db_config)
    if connection is None:
        print("Could not connect to the database. See messages above.")
        return 2

    try:
        # Step 1: search & select
        person = search_and_select(connection)
        if person is None:
            print("Cancelled.")
            return 0

        # Step 2: show the picture
        show_person(person)

        if not person.has_email():
            print(
                "  WARNING: no email on file for this person. "
                "The PDF will be saved locally but cannot be emailed.\n"
            )

        # Step 3: confirmation
        if person.any_2fa_enabled():
            print(
                "  WARNING: 2FA is already enabled for one or more accounts.\n"
                "  Provisioning will REPLACE the existing secret. The user's\n"
                "  current authenticator entry will stop working immediately.\n"
            )
            if not _yn("  Replace the existing secret?", default=False):
                print("Cancelled.")
                return 0
        else:
            if not _yn("  Provision 2FA for this user?", default=True):
                print("Cancelled.")
                return 0

        # Step 4: generate secret + build documents
        secret = generate_secret()
        output_dir = Path(cfg.OUTPUT_DIR).expanduser()

        pdf_path, email_html, qr_png, email_text, qr_cid = build_documents(
            person, secret, output_dir
        )
        print(f"\n  PDF written: {pdf_path}")

        # Step 5: write to DB (unless dry-run)
        if args.dry_run:
            print("  DRY-RUN: skipping DB update and email.")
            updated = 0
        else:
            updated = update_2fa_for_person(
                connection, person, secret, cfg.TOTP_ALGORITHM
            )
            print(f"  Updated {updated} security row(s).")

        # Step 6a: email
        email_destination = ""
        if (
            not args.dry_run
            and not args.no_email
            and person.has_email()
            and cfg.SMTP_HOST
            and cfg.FROM_ADDR
        ):
            try:
                send_email(
                    smtp_host=cfg.SMTP_HOST,
                    smtp_port=cfg.SMTP_PORT,
                    smtp_mode=cfg.SMTP_MODE,
                    smtp_user=cfg.SMTP_USER,
                    smtp_password=cfg.SMTP_PASSWORD,
                    from_addr=cfg.FROM_ADDR,
                    from_friendly=cfg.FROM_FRIENDLY,
                    to_addrs=[person.email],
                    subject=f"OSCAR EMR access and 2FA setup for {person.full_name}",
                    html_body=email_html,
                    text_body=email_text,
                    qr_png=qr_png,
                    qr_cid=qr_cid,
                    pdf_attachment=pdf_path,
                )
                email_destination = person.email
                print(f"  Email sent to {person.email}.")
            except Exception as e:
                print(f"  ERROR: email send failed: {e}")
        elif args.no_email:
            print("  --no-email: skipping email send.")
        elif not cfg.SMTP_HOST or not cfg.FROM_ADDR:
            print("  Skipping email — SMTP_HOST or FROM_ADDR not configured.")

        # Step 6b: Nextcloud
        nextcloud_path: Optional[Path] = None
        if not args.dry_run and cfg.NEXTCLOUD_DIR:
            try:
                nextcloud_path = copy_to_nextcloud(pdf_path, cfg.NEXTCLOUD_DIR)
                if nextcloud_path:
                    print(f"  Nextcloud copy: {nextcloud_path}")
            except Exception as e:
                print(f"  ERROR: Nextcloud copy failed: {e}")

        # Step 7: audit log
        write_event(
            cfg.LOG_DIR,
            actor=os.getenv("SUDO_USER") or getpass.getuser(),
            person_id=person.person_id,
            full_name=person.full_name,
            accounts_updated=updated,
            email_sent_to=email_destination,
            nextcloud_copy=str(nextcloud_path) if nextcloud_path else "",
            dry_run=args.dry_run,
        )

        print("\nDone.")
        return 0

    finally:
        try:
            connection.close()
        except Exception:
            pass
        if tunnel is not None and tunnel.is_active:
            tunnel.close()


if __name__ == "__main__":
    sys.exit(main())
