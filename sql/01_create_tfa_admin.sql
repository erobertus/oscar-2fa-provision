-- =============================================================================
-- oscar-2fa-provision: dedicated DB user grants
-- =============================================================================
-- Run this as a DB administrator (e.g. root) after deploying the project.
-- Adjust the database name (oscar_15) if yours is different, and choose a
-- strong password before running CREATE USER.
--
-- The user `tfa_admin` is intentionally narrowly scoped:
--   * It can SEARCH and DISPLAY enough provider/security data to confirm
--     the right physical person is being provisioned.
--   * It can UPDATE only the three custom 2FA columns we manage.
--   * It cannot read or modify passwords, PINs, or any other column.
--
-- The PIN rotation script (Oscar_2FA / 2FA_gen.sh) uses a separate user
-- (`oath_admin`) and is not affected by these grants.
-- =============================================================================

-- 1) Create the user. Replace 'CHANGE_ME' before running.
CREATE USER 'tfa_admin'@'helium.robertustech.com' IDENTIFIED BY 'MWM3qcq-vmk-exv1vyb';

-- 2) Grants on the provider table — read-only.
GRANT SELECT (provider_no, last_name, first_name, email,
              practitionerNo, team, status)
  ON `oscar_15`.`provider`
  TO 'tfa_admin'@'helium.robertustech.com';

-- 3) Grants on the security table — read for IDs and 2FA state, update
--    only the three custom 2FA columns this project manages.
GRANT SELECT (security_no, user_name, provider_no,
              `_EYR_2FAenabled`, `_EYR_2FASecret`, `_EYR_2FAtotp`)
  ON `oscar_15`.`security`
  TO 'tfa_admin'@'helium.robertustech.com';

GRANT UPDATE (`_EYR_2FAenabled`, `_EYR_2FASecret`, `_EYR_2FAtotp`)
  ON `oscar_15`.`security`
  TO 'tfa_admin'@'helium.robertustech.com';

FLUSH PRIVILEGES;

-- 4) Verify
SHOW GRANTS FOR 'tfa_admin'@'helium.robertustech.com';
