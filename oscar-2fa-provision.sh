#!/bin/sh
# oscar-2fa-provision.sh
# Wrapper for the OSCAR EMR 2FA provisioning utility.
#
# Loads a .env file from CONFIG_DIR (default: this script's directory) so
# the same checkout can be deployed under different config directories
# without code changes. Mirrors the convention used by Oscar_Auto_Billing.

set -e

# Resolve the script directory regardless of where it was invoked from.
SCRIPT_PATH=$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")

CONFIG_DIR=${CONFIG_DIR:-$SCRIPT_DIR}
ENV_FILENAME=${ENV_FILENAME:-".env"}
ENV_PATH="$CONFIG_DIR/$ENV_FILENAME"

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

if [ "$VERBOSE" = "1" ]; then
    echo "Script: $SCRIPT_PATH"
    echo "Work dir: $WORK_DIR"
    echo "Config:  $ENV_PATH"
fi

cd "$WORK_DIR"
exec python3 "$WORK_DIR/main.py" "$@"
