"""Domain logic for resolving a search input into a Person + their accounts.

A "Person" is identified by `practitionerNo` and has 1..N security rows
(one per team / office). When 2FA is provisioned, all of those rows are
updated with the same secret in a single transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sql_const import SQL_FETCH_BY_PRACTITIONER, SQL_SEARCH_BY_LASTNAME


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
    """A physical person, identified by practitionerNo. Holds 1..N accounts."""

    practitioner_no: str
    last_name: str
    first_name: str        # canonical (un-suffixed) first name
    email: str
    accounts: List[Account] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.last_name}, {self.first_name}"

    @property
    def safe_filename_stem(self) -> str:
        """File-system-safe stem for output filenames."""
        cleaned = "".join(
            ch if (ch.isalnum() or ch in "-_") else "_"
            for ch in f"{self.last_name}_{self.first_name}_{self.practitioner_no}"
        )
        return cleaned.strip("_")

    def any_2fa_enabled(self) -> bool:
        return any(a.is_2fa_enabled for a in self.accounts)

    def has_email(self) -> bool:
        return bool(self.email and "@" in self.email)


def search_by_lastname(connection, last_name_query: str) -> List[Person]:
    """Search providers by last-name substring; return a list of Persons.

    Each Person aggregates all provider+security rows that share a
    practitionerNo. People with no security rows are omitted (we have
    nothing to update for them).
    """
    cur = connection.cursor(buffered=True)
    cur.execute(SQL_SEARCH_BY_LASTNAME, (f"%{last_name_query}%",))

    # First, collect distinct practitionerNos from the search results.
    practitioner_nos: List[str] = []
    seen = set()
    for row in cur:
        prac = row[5]  # practitionerNo column
        if prac and prac not in seen:
            seen.add(prac)
            practitioner_nos.append(prac)
    cur.close()

    # For each, fetch the full picture (all teams + security rows).
    people: List[Person] = []
    for prac in practitioner_nos:
        person = _fetch_person(connection, prac)
        if person is not None and person.accounts:
            people.append(person)
    return people


def _fetch_person(connection, practitioner_no: str) -> Optional[Person]:
    """Hydrate a Person from the DB by practitionerNo."""
    cur = connection.cursor(buffered=True)
    cur.execute(SQL_FETCH_BY_PRACTITIONER, (practitioner_no,))

    person: Optional[Person] = None
    for row in cur:
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

        # Skip provider rows with no matching security row — we have nothing
        # to update for those, and showing them in the prompt would be
        # misleading.
        if security_no is None or not user_name:
            continue

        if person is None:
            # Use the first row's name/email as canonical. We strip any
            # team suffix from first_name for display, since "Sonia B"
            # in provider.first_name actually means "Sonia (Burlington)".
            canonical_first = _strip_team_suffix(first_name)
            person = Person(
                practitioner_no=prac_no,
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
    cur.close()
    return person


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
    """
    if not first_name:
        return ""
    parts = first_name.strip().split()
    if len(parts) >= 2:
        last = parts[-1]
        if 1 <= len(last) <= 4 and last.isupper() and last.isalpha():
            return " ".join(parts[:-1])
    return first_name.strip()
