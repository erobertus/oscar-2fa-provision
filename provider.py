"""Domain logic for resolving a search input into a Person + their accounts.

A "Person" represents a physical human being and holds 1..N security rows.
Most users have a single account. Multi-office doctors share a
`practitionerNo` across their per-office provider records, and we treat
those as a single Person so that 2FA provisioning updates every account
in one transaction.

Grouping rule:
    - If two or more active provider rows share the same non-empty
      `practitionerNo`, those rows form one Person.
    - Otherwise (PAs, NPs, single-office doctors, or anyone whose
      `practitionerNo` is blank/NULL), each provider row is its own
      Person — even if multiple such rows happen to have the same
      blank practitionerNo.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sql_const import (
    SQL_FETCH_BY_PRACTITIONER,
    SQL_FETCH_BY_PROVIDER,
    SQL_SEARCH_BY_LASTNAME,
)


@dataclass
class Account:
    """One security row belonging to a Person."""

    security_no: int
    user_name: str
    provider_no: str
    team: str
    first_name: str        # the team-suffixed first name from provider, e.g. "Sonia B"
    is_2fa_enabled: bool
    current_secret: str    # may be empty
    current_algorithm: str # may be empty


@dataclass
class Person:
    """A physical person, holding 1..N accounts.

    `practitioner_no` is the canonical identifier when present and shared
    across multiple accounts. For standalone accounts it is the empty
    string and `provider_no` becomes the de-facto identifier.
    """

    practitioner_no: str   # may be "" for standalone accounts
    provider_no: str       # provider_no of the canonical (first) account
    last_name: str
    first_name: str        # canonical (un-suffixed) first name
    email: str
    accounts: List[Account] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.last_name}, {self.first_name}"

    @property
    def person_id(self) -> str:
        """Stable identifier for logs and filenames.

        Multi-office doctors with shared practitionerNos use that number
        directly; standalone accounts use their provider_no prefixed with
        "p:" to keep the two namespaces visually distinct.
        """
        if self.practitioner_no:
            return self.practitioner_no
        return f"p:{self.provider_no}"

    @property
    def safe_filename_stem(self) -> str:
        """File-system-safe stem for output filenames.

        The stem encodes the person_id so that doctor and standalone
        filenames don't collide even if they share a numeric value
        (a real practitionerNo could in theory equal someone else's
        provider_no — vanishingly unlikely but worth dodging).
        """
        ident = self.practitioner_no or f"p{self.provider_no}"
        cleaned = "".join(
            ch if (ch.isalnum() or ch in "-_") else "_"
            for ch in f"{self.last_name}_{self.first_name}_{ident}"
        )
        return cleaned.strip("_")

    def any_2fa_enabled(self) -> bool:
        return any(a.is_2fa_enabled for a in self.accounts)

    def has_email(self) -> bool:
        return bool(self.email and "@" in self.email)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search_by_lastname(connection, last_name_query: str) -> List[Person]:
    """Search providers by last-name substring; return a list of Persons.

    Active providers whose last name contains `last_name_query` are
    fetched. Results are then grouped:

        - rows sharing a non-empty practitionerNo collapse to one Person
          (this picks up the multi-office doctor case);
        - everyone else — PAs, NPs, single-office doctors, or any rows
          with a blank practitionerNo — is treated as a standalone
          Person, one per provider row, never collapsed even if two
          standalone rows happen to share a blank practitionerNo.

    People with no matching security row are dropped — there's nothing
    we could update for them.
    """
    cur = connection.cursor(buffered=True)
    cur.execute(SQL_SEARCH_BY_LASTNAME, (f"%{last_name_query}%",))
    raw_rows = list(cur)
    cur.close()

    if not raw_rows:
        return []

    # Bucket by practitionerNo. The empty-string bucket holds standalones,
    # which are NEVER grouped together — we'll iterate them individually
    # below.
    by_prac: Dict[str, List[tuple]] = defaultdict(list)
    standalones: List[tuple] = []
    for row in raw_rows:
        prac = row[5] or ""
        if prac:
            by_prac[prac].append(row)
        else:
            standalones.append(row)

    people: List[Person] = []

    # Doctors / providers with non-empty practitionerNo. Re-fetch the
    # full set of accounts globally for that number so we don't miss
    # a sibling office that didn't match the search (e.g. when only
    # part of the last name matched and one office spells it slightly
    # differently — defensive).
    for prac in by_prac:
        person = _fetch_person_by_practitioner(connection, prac)
        if person is not None:
            people.append(person)

    # Pure standalones — fetch each by provider_no.
    for row in standalones:
        provider_no = row[0]
        person = _fetch_person_by_provider(connection, str(provider_no))
        if person is not None:
            people.append(person)

    # Stable display order
    people.sort(
        key=lambda p: (p.last_name.lower(), p.first_name.lower(), p.person_id)
    )
    return people


# ---------------------------------------------------------------------------
# Hydration
# ---------------------------------------------------------------------------
def _fetch_person_by_practitioner(
    connection, practitioner_no: str
) -> Optional[Person]:
    """Hydrate a Person from the DB by practitionerNo (1..N accounts)."""
    cur = connection.cursor(buffered=True)
    cur.execute(SQL_FETCH_BY_PRACTITIONER, (practitioner_no,))
    rows = list(cur)
    cur.close()
    return _build_person_from_rows(rows)


def _fetch_person_by_provider(connection, provider_no: str) -> Optional[Person]:
    """Hydrate a single-account Person from the DB by provider_no."""
    cur = connection.cursor(buffered=True)
    cur.execute(SQL_FETCH_BY_PROVIDER, (provider_no,))
    rows = list(cur)
    cur.close()
    return _build_person_from_rows(rows)


def _build_person_from_rows(rows: List[tuple]) -> Optional[Person]:
    """Construct a Person from a list of (provider + security) join rows.

    Drops rows with no matching security record (we can't update those).
    Returns None if no usable rows remain.
    """
    person: Optional[Person] = None
    for row in rows:
        (
            provider_no,
            last_name,
            first_name,
            email,
            team,
            prac_no,
            security_no,
            user_name,
            enabled_bit,
            secret,
            totp_alg,
        ) = row

        # Skip provider rows with no matching security row.
        if security_no is None or not user_name:
            continue

        if person is None:
            canonical_first = _strip_team_suffix(first_name)
            person = Person(
                practitioner_no=prac_no or "",
                provider_no=str(provider_no),
                last_name=last_name,
                first_name=canonical_first,
                email=email or "",
            )

        # mariadb returns BIT(1) as bytes b'\x00' or b'\x01'; coerce.
        enabled = bool(enabled_bit) and enabled_bit not in (b"\x00", 0, "0")

        person.accounts.append(
            Account(
                security_no=int(security_no),
                user_name=user_name,
                provider_no=str(provider_no),
                team=team or "",
                first_name=first_name or "",
                is_2fa_enabled=enabled,
                current_secret=secret or "",
                current_algorithm=totp_alg or "",
            )
        )

    if person is None or not person.accounts:
        return None
    return person


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def _strip_team_suffix(first_name: str) -> str:
    """Heuristically strip the trailing team-code from a first name.

    Examples:
        "Sonia B"        -> "Sonia"
        "Sonia NF"       -> "Sonia"
        "Ameer WLND"     -> "Ameer"
        "John W"         -> "John"  (could be wrong, but harmless)
        "Mary"           -> "Mary"

    The provider table uses a convention of suffixing the first name with
    a short uppercase team code separated by a space. If the last token
    is 1-4 uppercase letters, we treat it as a suffix and remove it.

    For standalone accounts (PAs/NPs) this is a no-op since they don't
    use the team-suffix convention.
    """
    if not first_name:
        return ""
    parts = first_name.strip().split()
    if len(parts) >= 2:
        last = parts[-1]
        if 1 <= len(last) <= 4 and last.isupper() and last.isalpha():
            return " ".join(parts[:-1])
    return first_name.strip()
