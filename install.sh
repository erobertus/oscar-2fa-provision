#!/bin/sh
# install.sh — install, upgrade, or uninstall oscar-2fa-provision on a host.
#
# Usage (as root):
#   ./install.sh              install or upgrade in place
#   ./install.sh --no-venv    skip the private venv (use system python3 deps)
#   ./install.sh --uninstall  remove code + launcher; keep config, logs, data
#
# Layout installed (FHS):
#   /opt/oscar-2fa-provision/                     code, templates, .venv
#   /usr/local/bin/oscar-2fa-provision            launcher (symlink)
#   /etc/oscar-2fa-provision/oscar-2fa-provision.conf   config, root:root 600
#   /etc/oscar-2fa-provision/ssh/                 SSH tunnel key(s), 700
#   /var/log/oscar-2fa-provision/                 audit log
#   /var/lib/oscar-2fa-provision/output/          generated PDFs
#
# Re-running is safe: code is refreshed, an existing config file is NEVER
# overwritten (a fresh .sample is placed beside it for diffing).
#
# First install on a host that already runs from a git checkout: the
# checkout's .env is migrated to the /etc config verbatim, except that
# relative paths (OUTPUT_DIR, LOG_DIR, PKEY_FILE, NEXTCLOUD_DIR) are pinned
# to their current absolute location so existing output/log/key locations
# are preserved.

set -eu

APP=oscar-2fa-provision
PREFIX=/opt/$APP
BIN_LINK=/usr/local/bin/$APP
CONF_DIR=/etc/$APP
CONF_FILE=$CONF_DIR/$APP.conf
CONF_SAMPLE=$CONF_DIR/$APP.conf.sample
LOG_DIR=/var/log/$APP
DATA_DIR=/var/lib/$APP

SRC_PATH=$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")
SRC_DIR=$(dirname "$SRC_PATH")

MAKE_VENV=1
ACTION=install
for arg in "$@"; do
    case "$arg" in
        --no-venv)   MAKE_VENV=0 ;;
        --uninstall) ACTION=uninstall ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" != "0" ]; then
    echo "This script must run as root (writes to /opt, /etc, /var)." >&2
    exit 1
fi

if [ "$ACTION" = "uninstall" ]; then
    echo "Removing $PREFIX and $BIN_LINK ..."
    rm -rf "$PREFIX"
    rm -f "$BIN_LINK"
    echo "Left in place (remove manually if truly done with the tool):"
    echo "  $CONF_DIR    (config + SSH keys)"
    echo "  $LOG_DIR     (audit log)"
    echo "  $DATA_DIR    (generated PDFs)"
    exit 0
fi

# --- code ---------------------------------------------------------------
echo "Installing code to $PREFIX ..."
mkdir -p "$PREFIX/templates" "$PREFIX/sql"

for f in main.py audit.py db_config.py db_connection.py distribute.py \
         document.py provider.py qr.py sql_const.py term.py totp.py \
         requirements.txt README.md; do
    install -m 644 "$SRC_DIR/$f" "$PREFIX/$f"
done
install -m 755 "$SRC_DIR/$APP.sh" "$PREFIX/$APP.sh"
install -m 644 "$SRC_DIR/templates/instructions.html" "$PREFIX/templates/"
install -m 644 "$SRC_DIR/sql/01_create_tfa_admin.sql" "$PREFIX/sql/"

# --- python deps --------------------------------------------------------
if [ "$MAKE_VENV" = "1" ]; then
    echo "Setting up venv at $PREFIX/.venv ..."
    if [ ! -x "$PREFIX/.venv/bin/python3" ]; then
        python3 -m venv "$PREFIX/.venv"
    fi
    if ! "$PREFIX/.venv/bin/pip" install --quiet -r "$PREFIX/requirements.txt"; then
        echo "ERROR: pip install failed. The 'mariadb' driver and WeasyPrint" >&2
        echo "need system packages first — see README.md 'System packages'." >&2
        echo "Fix and re-run, or use --no-venv to rely on system python3." >&2
        exit 1
    fi
else
    echo "Skipping venv (--no-venv): the wrapper will use system python3."
fi

# --- config -------------------------------------------------------------
echo "Configuring $CONF_DIR ..."
mkdir -p "$CONF_DIR/ssh"
chmod 750 "$CONF_DIR"
chmod 700 "$CONF_DIR/ssh"

# Installed sample gets FHS paths instead of the checkout-relative defaults.
sed -e "s|^OUTPUT_DIR=.*|OUTPUT_DIR=$DATA_DIR/output|" \
    -e "s|^LOG_DIR=.*|LOG_DIR=$LOG_DIR|" \
    -e "s|^PKEY_FILE=.*|PKEY_FILE=$CONF_DIR/ssh/oscar_db.key|" \
    "$SRC_DIR/.env.sample" > "$CONF_SAMPLE"
chmod 640 "$CONF_SAMPLE"

# Rewrite a path variable in $CONF_FILE to an absolute path when its current
# value is relative. Relative paths in a checkout .env were resolved against
# the checkout directory; after migration the tool runs from /opt, so they
# must be pinned to their original absolute location or data would silently
# move. Handles optional quotes and trailing comments on the value.
absolutize_var() {
    _var=$1
    _val=$(sed -n "s|^${_var}=||p" "$CONF_FILE" | head -1 \
           | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
    case "$_val" in
        ""|/*) ;;  # empty or already absolute — leave as-is
        *)
            _abs=$(readlink -f "$SRC_DIR/$_val" 2>/dev/null || echo "$SRC_DIR/$_val")
            sed -i "s|^${_var}=.*|${_var}=$_abs|" "$CONF_FILE"
            echo "  $_var: '$_val' → $_abs (kept pointing at the same location)"
            ;;
    esac
}

if [ ! -f "$CONF_FILE" ]; then
    if [ -f "$SRC_DIR/.env" ]; then
        # Migrate an existing checkout deployment: keep every configured
        # value; only relative paths get pinned to their current location.
        echo "Migrating existing $SRC_DIR/.env to $CONF_FILE ..."
        cp "$SRC_DIR/.env" "$CONF_FILE"
        chmod 600 "$CONF_FILE"
        for v in OUTPUT_DIR LOG_DIR PKEY_FILE NEXTCLOUD_DIR; do
            absolutize_var "$v"
        done
        NEW_CONF=migrated
    else
        cp "$CONF_SAMPLE" "$CONF_FILE"
        chmod 600 "$CONF_FILE"
        NEW_CONF=1
    fi
else
    chmod 600 "$CONF_FILE"
    NEW_CONF=0
fi

# --- runtime dirs + launcher ---------------------------------------------
mkdir -p "$LOG_DIR" "$DATA_DIR/output"
chmod 750 "$LOG_DIR" "$DATA_DIR" "$DATA_DIR/output"
ln -sf "$PREFIX/$APP.sh" "$BIN_LINK"

echo ""
echo "Installed. Run with: $APP"
if [ "$NEW_CONF" = "1" ]; then
    echo ""
    echo "NEW INSTALL — edit the config before first use:"
    echo "  ${EDITOR:-vi} $CONF_FILE"
    echo "(DB credentials, SMTP relay, login URL; see comments in the file.)"
elif [ "$NEW_CONF" = "migrated" ]; then
    echo ""
    echo "Migrated your checkout .env to $CONF_FILE — review it, then"
    echo "the old $SRC_DIR/.env is no longer read and can be removed."
    echo "(The wrapper now prefers the /etc config whenever it exists.)"
else
    echo "Existing config kept: $CONF_FILE"
    echo "Fresh sample for diffing: $CONF_SAMPLE"
fi
