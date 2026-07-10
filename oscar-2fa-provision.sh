#!/bin/sh
# oscar-2fa-provision.sh
# Wrapper for the OSCAR EMR 2FA provisioning utility.
#
# Configuration is resolved in this order:
#   1. $CONFIG_DIR/$ENV_FILENAME        (explicit override, dev or testing)
#   2. /etc/oscar-2fa-provision/oscar-2fa-provision.conf   (installed system)
#   3. <script dir>/.env                (git-checkout development mode)
# The file is sourced shell-style (`set -a; . file; set +a`), so values with
# spaces or metacharacters must be quoted. Mirrors Oscar_Auto_Billing.

set -e

# Resolve the script directory regardless of where it was invoked from
# (readlink -f follows the /usr/local/bin symlink to the real install dir).
SCRIPT_PATH=$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")

ETC_CONF="/etc/oscar-2fa-provision/oscar-2fa-provision.conf"

if [ -n "${CONFIG_DIR:-}" ]; then
    ENV_PATH="$CONFIG_DIR/${ENV_FILENAME:-.env}"
elif [ -f "$ETC_CONF" ]; then
    ENV_PATH="$ETC_CONF"
else
    ENV_PATH="$SCRIPT_DIR/${ENV_FILENAME:-.env}"
fi

VERBOSE=${VERBOSE:-1}

if [ -f "$ENV_PATH" ]; then
    [ "$VERBOSE" = "1" ] && echo "Loading environment from: $ENV_PATH"
    set -a
    . "$ENV_PATH"
    set +a
else
    echo "WARNING: $ENV_PATH not found — relying on environment variables only." >&2
fi

WORK_DIR=${WORK_DIR:-$SCRIPT_DIR}

# Prefer the private venv created by install.sh; fall back to system python3.
if [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python3"
else
    PYTHON=python3
fi

if [ "$VERBOSE" = "1" ]; then
    echo "Script:  $SCRIPT_PATH"
    echo "Work dir: $WORK_DIR"
    echo "Config:  $ENV_PATH"
    echo "Python:  $PYTHON"
fi

cd "$WORK_DIR"
exec "$PYTHON" "$SCRIPT_DIR/main.py" "$@"
