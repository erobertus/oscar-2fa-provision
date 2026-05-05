"""SQL statements used by the provisioning script.

All statements use parameterised placeholders (?) — never string-format
user input into SQL. The DB user (`tfa_admin`) only has the column-level
grants needed for these specific statements.
"""

# Provider IDs outside this range are excluded from search and fetch.
# Below 1 (including negative values): legacy or migrated chart entries
# that don't represent real users. At/above 100000: test accounts,
# developer accounts, or providers migrated from old charts. provider_no
# is stored as a varchar in the OSCAR schema, so the SQL casts to SIGNED
# for the numeric comparison — UNSIGNED would coerce negatives to 0 (or
# to a large positive on some MariaDB versions) and let them slip in.
PROVIDER_NO_MIN = 1
PROVIDER_NO_MAX = 100000   # exclusive upper bound

_PROVIDER_RANGE_CLAUSE = (
    "CAST(p.provider_no AS SIGNED) >= ? "
    "AND CAST(p.provider_no AS SIGNED) < ?"
)


# Search providers by last name (case-insensitive substring match).
# Returns one row per provider account for any active provider whose last
# name matches. We later decide whether to group by practitionerNo
# (multi-office doctors) or treat each provider row as a standalone person
# (PAs, NPs, single-office doctors, anyone with a blank practitionerNo).
SQL_SEARCH_BY_LASTNAME = f"""\
SELECT p.provider_no,
       p.last_name,
       p.first_name,
       p.email,
       p.team,
       COALESCE(p.practitionerNo, '') AS practitionerNo,
       p.status
  FROM provider p
 WHERE LOWER(p.last_name) LIKE LOWER(?)
   AND p.status = '1'
   AND {_PROVIDER_RANGE_CLAUSE}
 ORDER BY COALESCE(p.practitionerNo, ''), p.first_name, p.provider_no
"""

# Given a practitionerNo, fetch all provider rows for that physical person
# along with their corresponding security row(s) and current 2FA status.
# A LEFT JOIN is used because not every provider row necessarily has a
# matching security row (defensive).
SQL_FETCH_BY_PRACTITIONER = f"""\
SELECT p.provider_no,
       p.last_name,
       p.first_name,
       p.email,
       p.team,
       COALESCE(p.practitionerNo, '') AS practitionerNo,
       s.security_no,
       s.user_name,
       s._EYR_2FAenabled,
       s._EYR_2FASecret,
       s._EYR_2FAtotp
  FROM provider p
  LEFT JOIN security s ON s.provider_no = p.provider_no
 WHERE p.practitionerNo = ?
   AND p.status = '1'
   AND {_PROVIDER_RANGE_CLAUSE}
 ORDER BY p.team, p.provider_no
"""

# Fetch a single provider row + its security row by provider_no. Used
# for standalone accounts (PAs, NPs, anyone without a shared practitionerNo).
SQL_FETCH_BY_PROVIDER = f"""\
SELECT p.provider_no,
       p.last_name,
       p.first_name,
       p.email,
       p.team,
       COALESCE(p.practitionerNo, '') AS practitionerNo,
       s.security_no,
       s.user_name,
       s._EYR_2FAenabled,
       s._EYR_2FASecret,
       s._EYR_2FAtotp
  FROM provider p
  LEFT JOIN security s ON s.provider_no = p.provider_no
 WHERE p.provider_no = ?
   AND p.status = '1'
   AND {_PROVIDER_RANGE_CLAUSE}
"""

# Update the four 2FA columns on a single security row.
# We only ever update rows whose security_no we already fetched in the
# step above, so no further filtering is needed.
SQL_UPDATE_2FA = """\
UPDATE security
   SET _EYR_2FAenabled = 1,
       _EYR_2FASecret  = ?,
       _EYR_2FAtotp    = ?
 WHERE security_no = ?
"""

BEGIN_TRAN = "START TRANSACTION"
COMMIT_TRAN = "COMMIT"
ROLLBACK_TRAN = "ROLLBACK"
