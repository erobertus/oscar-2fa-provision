"""SQL statements used by the provisioning script.

All statements use parameterised placeholders (?) — never string-format
user input into SQL. The DB user (`tfa_admin`) only has the column-level
grants needed for these specific statements.
"""

# Search providers by last name (case-insensitive substring match).
# Returns one row per provider account belonging to anyone whose last name
# matches. We later group by practitionerNo to collapse to a "person".
SQL_SEARCH_BY_LASTNAME = """\
SELECT p.provider_no,
       p.last_name,
       p.first_name,
       p.email,
       p.team,
       p.practitionerNo,
       p.status
  FROM provider p
 WHERE LOWER(p.last_name) LIKE LOWER(?)
   AND p.status = '1'
   AND COALESCE(p.practitionerNo, '') <> ''
 ORDER BY p.practitionerNo, p.first_name
"""

# Given a practitionerNo, fetch all provider rows for that physical person
# along with their corresponding security row(s) and current 2FA status.
# A LEFT JOIN is used because not every provider row necessarily has a
# matching security row (defensive).
SQL_FETCH_BY_PRACTITIONER = """\
SELECT p.provider_no,
       p.last_name,
       p.first_name,
       p.email,
       p.team,
       p.practitionerNo,
       s.security_no,
       s.user_name,
       s._EYR_2FAenabled,
       s._EYR_2FASecret,
       s._EYR_2FAtotp
  FROM provider p
  LEFT JOIN security s ON s.provider_no = p.provider_no
 WHERE p.practitionerNo = ?
   AND p.status = '1'
 ORDER BY p.team, p.provider_no
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
