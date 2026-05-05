# oscar-2fa-provision

Interactive provisioning of TOTP two-factor authentication for users in
OSCAR EMR.

This tool is the missing companion piece to
[`Oscar_2FA`](https://github.com/erobertus/Oscar_2FA), which rotates
PINs in OSCAR's `security` table on a schedule. `Oscar_2FA` does the
ongoing rotation; this project does the *one-time* per-user setup that
makes rotation meaningful: generating a fresh secret, writing it to all
of a user's accounts in one transaction, and producing the per-user
instruction document (PDF + email) with the QR code, setup key, and
sign-in steps.

## What it does

1. Searches OSCAR providers by last name (case-insensitive substring).
2. Groups results so each match represents a physical person:
   - Provider rows that share a non-empty `practitionerNo` collapse
     to one entry (multi-office doctors).
   - Anyone else — PAs, NPs, single-office providers, or rows with a
     blank `practitionerNo` — appears as a standalone entry, one per
     provider row.
3. Shows the matched person's accounts with their current 2FA status
   and prompts for confirmation.
4. Generates a fresh base32 secret (256 bits of entropy).
5. In a single transaction, sets `_EYR_2FAenabled = 1`,
   `_EYR_2FASecret = <new>`, and `_EYR_2FAtotp = 'sha256'` on every
   `security` row belonging to that person.
6. Renders a one-page instruction document — same content goes to:
   - the user's email (HTML body with inline QR + PDF attachment)
   - a local output directory
   - an optional Nextcloud directory mounted on the host
7. Appends an audit-log row recording who provisioned whom and where
   the document went.

## What it does *not* do

By design, this tool only touches three columns of the `security`
table. It does not create users, change passwords, modify PINs (that's
the rotation script's job), or alter the `provider` table.

## Prerequisites

- **Python 3.8+** with `pip`.
- **MariaDB / MySQL** access to the OSCAR database, ideally via a
  dedicated `tfa_admin` user (see `sql/01_create_tfa_admin.sql`).
- **An SMTP relay** the host can reach.
- (Optional) An NTP-synced clock — TOTP only works correctly when the
  server's time is right.

### System packages

WeasyPrint needs Pango, HarfBuzz, and Cairo at runtime; the `mariadb`
Python driver needs the MariaDB connector library to build.

**AlmaLinux / RHEL / Rocky / Fedora:**

```sh
sudo dnf install -y python3-pip python3-devel \
                    pango pango-devel harfbuzz \
                    cairo cairo-devel \
                    gdk-pixbuf2 libffi-devel \
                    mariadb-connector-c-devel gcc
```

**Debian / Ubuntu:**

```sh
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev \
                    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
                    libcairo2 libgdk-pixbuf-2.0-0 libffi-dev \
                    libmariadb-dev gcc
```

The `*-devel` / `*-dev` packages are only needed while installing
`mariadb` and (sometimes) `weasyprint` from pip — you can remove them
afterwards if you're tight on disk.

## Installation

```sh
git clone https://github.com/<you>/oscar-2fa-provision.git
cd oscar-2fa-provision

# Create a venv and install Python deps
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Create the dedicated DB user (edit the password first!)
sudo mysql < sql/01_create_tfa_admin.sql

# Configure
cp .env.sample .env
chmod 600 .env
$EDITOR .env       # fill in DB / SMTP / paths
```

## Configuration

All settings come from `.env` (or the process environment if running
under cron / systemd). See `.env.sample` for the full annotated list.
Important groups:

| Group | Purpose |
| --- | --- |
| `DB_*` | OSCAR database connection. Use the `tfa_admin` credentials. |
| `SSH_*`, `PKEY_FILE`, `CERT_SECRET` | Optional SSH-tunnel mode for remote DBs. |
| `SMTP_*`, `FROM_ADDR`, `FROM_FRIENDLY` | Outbound email. `SMTP_MODE=ssl\|starttls\|plain`. |
| `TOTP_*` | Algorithm/digits/period embedded in the QR. SHA-256, 6, 30 by default. |
| `OSCAR_LOGIN_URL`, `INITIAL_PASSWORD`, `CLINIC_ADMIN_CONTACT` | Strings printed in the user's document. |
| `OUTPUT_DIR` | Where PDFs are written (always). |
| `NEXTCLOUD_DIR` | Optional. If set and the directory exists, the PDF is also copied there. |
| `LOG_DIR` | Where the audit log is appended. |

## Usage

```sh
./oscar-2fa-provision.sh
```

You'll be prompted:

```
Search by last name (blank to quit): mosaad

──────────────────────────────────────────────────────────────────────
  Mosaad, Sonia
  practitionerNo: 78222
  email:          Soniamosaad@gmail.com
  accounts:       6
──────────────────────────────────────────────────────────────────────
    [disabled] smosaadb        Sonia B            (Burlington)
    [disabled] smosaadk        Sonia K            (Kitchener)
    [disabled] smosaadh        Sonia H            (Hamilton)
    [disabled] smosaadg        Sonia G            (Guelph)
    [disabled] smosaadnf       Sonia NF           (Niagara Falls)
    [disabled] smosaadsc       Sonia SC           (St. Catharines)
──────────────────────────────────────────────────────────────────────
  Provision 2FA for this user? [Y/n] y

  PDF written: ./output/Mosaad_Sonia_78222.pdf
  Updated 6 security row(s).
  Email sent to Soniamosaad@gmail.com.

Done.
```

Useful flags:

- `--dry-run` — render the PDF but skip the DB update and email.
- `--no-email` — write the PDF and update the DB, but skip email.
- `-s on|off` — override `SSH_ENABLED` for one run.

## Re-issuance (lost phone, etc.)

If a user already has 2FA enabled, the script warns prominently and
requires explicit confirmation before replacing the secret. Replacement
invalidates the old authenticator entry immediately.

For the common case where a user's phone is wiped but the secret is
known to be safe, you don't need this script — fetch the existing PDF
from your Nextcloud copy and resend it manually.

## Audit log format

`logs/provision.log` is a tab-separated append-only file with these
columns:

```
timestamp  actor  person_id  full_name  accounts_updated
email_sent_to  nextcloud_copy  dry_run  notes
```

`person_id` is the `practitionerNo` for grouped multi-office doctors,
or `p:<provider_no>` for standalone accounts — the prefix keeps the
two namespaces visually distinct.

The secret itself is **never** written to the log.

## Related projects

- [`Oscar_2FA`](https://github.com/erobertus/Oscar_2FA) — the PIN
  rotation script that consumes the `_EYR_2FA*` columns this tool
  populates.
- [`Oscar_Auto_Billing`](https://github.com/erobertus/Oscar_Auto_Billing)
  — shares the configuration and DB connection pattern this tool
  follows on Helium.
- [`provider-onboarding`](https://github.com/erobertus/provider-onboarding)
  — the bash counterpart for cloning provider records and schedules.
