# CLAUDE.md

Guidance for future Claude sessions working on this repository.

## What this project is

`oscar-2fa-provision` is an interactive Python CLI that provisions TOTP
two-factor authentication for users in **OSCAR EMR**. It's the missing
one-time-setup companion to the `Oscar_2FA` project, which does the
ongoing PIN rotation.

The workflow: search a user by last name → confirm the match →
generate a fresh secret → write it into all of that person's
`security` rows in one transaction → build a one-page HTML/PDF
instruction document → email it to the user (CC'ing clinic managers)
→ optionally copy the PDF to a Nextcloud folder → append an audit-log
row.

## Environment

- **Host**: Helium (AlmaLinux 8.10, running as root)
- **Related repos on the same host**:
  - `Oscar_Auto_Billing` — Python, provided the connection/config pattern this project mirrors
  - `Oscar_2FA` — bash rotation script that consumes the `_EYR_2FA*` columns this project populates
  - `provider-onboarding` — bash, provided the ANSI color/UX style this project mirrors in `term.py`
- **Python**: 3.12 on Helium, 3.8+ supported in principle
- **Database**: MariaDB, database name `oscar_15`, connected either directly or via SSH tunnel
- **User development**: Windows machine with local git, pushes to GitHub as `erobertus`. Prefers zip-based delivery over paste-into-chat.

## Architectural decisions (locked in — don't re-litigate without cause)

### Scope
The project touches **only three columns** on the `security` table:
`_EYR_2FAenabled`, `_EYR_2FASecret`, `_EYR_2FAtotp`. It does NOT touch
`pin` (rotation script's job), passwords, user_names, provider_nos, or
anything in the `provider` table. When adding features, resist the
temptation to expand this scope.

### Person grouping
A "Person" object represents a physical human being with 1..N accounts:
- Provider rows sharing a **non-empty `practitionerNo`** collapse to one
  Person (multi-office doctors).
- Everyone else — PAs, NPs, single-office doctors, anyone with blank
  `practitionerNo` — is a standalone Person, one per provider row.
- Two standalone rows that both have blank `practitionerNo` **MUST NOT
  be collapsed** together, even if they share a last name.

### Provider ID filter
Providers with `provider_no < 1` or `provider_no >= 100000` are filtered
out at the SQL level. These are test accounts, developer accounts, and
legacy entries migrated from old charts. The SQL uses
`CAST(p.provider_no AS SIGNED)` — **not UNSIGNED** — because
`provider_no` is stored as a varchar and negative-string values would
coerce to 0 or wrap under UNSIGNED, letting them slip through the
filter.

### DB user
Dedicated `tfa_admin@localhost` with narrowly-scoped grants (see
`sql/01_create_tfa_admin.sql`): SELECT on the provider columns needed
for search/display; SELECT + UPDATE on the three `_EYR_2FA*` columns
only. No update rights on anything else in the `security` table.

### Multi-account update
All of a Person's security rows are updated in a **single transaction**
with the **same secret**. Multi-office doctors share one authenticator
entry across all their offices — this matches manual practice and the
`Oscar_2FA` rotation script's expectation.

### PDF & email
One Jinja2 HTML template (`templates/instructions.html`) is rendered
twice: once with a `cid:` reference for the email body, once with a
base64 data URI for the PDF. Both derive from a single
`DocumentContext` dataclass. The PDF must fit on one page — margins
have been tuned carefully; don't add sections without checking the
overflow.

### Re-issuance
If `_EYR_2FAenabled=1` already for any of a Person's accounts, the
script prints a **yellow warning + bold red REPLACE** in the confirm
prompt and requires an explicit `y` (default is `N`). Same code path
otherwise. The Nextcloud copy is the intended recovery-copy channel
for "user lost their phone" cases — the tool isn't needed for that.

## Technical constraints (things that will bite you)

### WeasyPrint pinned to 52.5
AlmaLinux 8 ships Pango 1.42. WeasyPrint 53+ requires Pango 1.44
features (`pango_context_set_round_glyph_positions` et al.). Do NOT
bump `weasyprint` above 52.5 unless Helium's Pango is upgraded first.
52.5 produces visually identical output for this template.

### The `term.py` module name
It was originally named `tty.py`, which shadows Python's stdlib
`tty` module. Renamed to `term.py` to avoid the collision. If you
add functionality, keep it there. Don't rename back.

### `.env` values must be shell-quotable
The wrapper (`oscar-2fa-provision.sh`) sources `.env` via
`set -a; . "$ENV_PATH"; set +a`, i.e. shell-style parsing. Any value
containing spaces, quotes, or shell metacharacters MUST be quoted in
`.env.sample`. Current quoted values: `FROM_FRIENDLY`, `TOTP_ISSUER`,
`CLINIC_ADMIN_CONTACT`. Add quotes to any new one with spaces.

### `provider_no` is a varchar
When comparing numerically, always `CAST(p.provider_no AS SIGNED)`.
Never rely on string ordering (`"99" > "100"` would be true).

### Column alignment with ANSI colors
When printing a table with `f"{value:<14}"` and coloring `value` with
`term.bold()`, pad the value to fixed width **before** wrapping in
color codes. Python counts escape characters as visible width, so
coloring first misaligns columns by exactly the length of the escape
sequences. See `show_person()` in `main.py` for the pattern.

### mariadb.BIT(1) coercion
The `_EYR_2FAenabled` column is `BIT(1)`. The `mariadb` Python driver
returns it as `b'\x00'` / `b'\x01'` (bytes), not int. See
`_build_person_from_rows()` in `provider.py` for the coercion.

## File layout

```
oscar-2fa-provision/
├── README.md                       # user-facing docs
├── CLAUDE.md                       # this file
├── requirements.txt                # WeasyPrint pinned to 52.5
├── .env.sample                     # annotated config template
├── .gitignore                      # blocks .env, ssh/*, output/, logs/
├── oscar-2fa-provision.sh          # wrapper: env loader + python3 main.py
├── main.py                         # interactive orchestrator
├── db_config.py                    # os.getenv → module constants
├── db_connection.py                # direct + SSH tunnel connect, adapted from auto-billing
├── provider.py                     # Person/Account dataclasses, search + grouping
├── sql_const.py                    # parameterized SQL, PROVIDER_NO_MIN/MAX
├── totp.py                         # base32 secret gen + otpauth:// URI
├── qr.py                           # QR PNG rendering (bytes / data URI / file)
├── document.py                     # Jinja2 → HTML, PDF (WeasyPrint), plain text
├── distribute.py                   # SMTP send (ssl/starttls/plain) + Nextcloud copy
├── audit.py                        # tab-separated provisioning log (NO secrets)
├── term.py                         # ANSI colors, TTY-aware print helpers
├── templates/instructions.html     # single-page HTML/CSS, both PDF and email body
├── sql/01_create_tfa_admin.sql     # narrow-scope DB user grants
├── docs/sample_output.pdf          # sample rendered PDF
├── ssh/, assets/                   # empty placeholder dirs with .gitkeep
├── output/                         # generated PDFs go here (gitignored)
└── logs/                           # audit log goes here (gitignored)
```

## Conventions to preserve

- **All SQL is parameterized** (`?` placeholders). Never string-format
  user input into SQL. See `sql_const.py`.
- **`term.*` for all output** — never bare `print()` in `main.py`
  except in tables where precise column control is needed. Terminal
  colors are stripped automatically when stdout isn't a TTY, so this
  is safe for piping too.
- **Import order in modules**: stdlib, blank line, third-party, blank
  line, project modules.
- **Audit log never contains the secret.** Log the person_id, name,
  channels of distribution, actor, timestamp. Nothing that could
  reconstruct the credential.
- **`person_id` convention**: `practitionerNo` for grouped doctors,
  `p:<provider_no>` for standalones. Keeps the two namespaces
  visually distinct in logs.

## Deferred / low priority

- **Jira integration**: The clinic's Jira ingest account is
  `indexdynamic.atlassian.net`. Requests arrive as free-form emails,
  not structured tickets. When wiring this up, add a
  `distribute_to_jira()` function in `distribute.py` with a CLI flag
  `--jira <TICKET>` and env vars `JIRA_BASE_URL`, `JIRA_USER`,
  `JIRA_API_TOKEN`. The code structure already leaves a clean hook
  for this.

## When making changes

1. Read the relevant section of this file first.
2. Preserve the scope discipline — three columns on `security`, nothing
   else.
3. Preserve the person-grouping rule — practitionerNo groups only when
   non-empty and shared; standalones never collapse.
4. Preserve the ANSI/TTY output style — new prompts and messages use
   `term.*` helpers.
5. Update `.env.sample` (with quoting!) and `README.md` when adding
   configuration.
6. If the DB schema is touched, update the grants in
   `sql/01_create_tfa_admin.sql` too.
7. Test in `--dry-run` before hitting a real DB.

## Delivery preference

Deliver code changes as a zip file (via `present_files`). The user
extracts on their local Windows machine, reviews, and pushes to GitHub
themselves. Do not paste 200-line files inline unless asked; a single
zip with all changes is preferred.
