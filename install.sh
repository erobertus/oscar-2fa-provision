#!/bin/sh
# install.sh — install, upgrade, or uninstall oscar-2fa-provision on a host.
#
# Usage (as root):
#   ./install.sh                    install or upgrade in place
#   ./install.sh --no-venv          skip the private venv (use system python3 deps)
#   ./install.sh --non-interactive  no prompts; migration keeps paths in place
#   ./install.sh --migrate-paths    re-run the keep-or-move path review on an
#                                   existing /etc config (files moved on request)
#   ./install.sh --uninstall        remove code + launcher; keep config, logs, data
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
# checkout's .env is migrated to the /etc config verbatim, then for each
# path parameter (OUTPUT_DIR, LOG_DIR, PKEY_FILE) the script asks whether
# to keep the current location or move the existing files to the FHS
# default and update the config accordingly. With --non-interactive (or
# no TTY) everything stays where it is, pinned to absolute paths.

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
INTERACTIVE=1
MIGRATE_PATHS=0
for arg in "$@"; do
    case "$arg" in
        --no-venv)          MAKE_VENV=0 ;;
        --uninstall)        ACTION=uninstall ;;
        --non-interactive)  INTERACTIVE=0 ;;
        --migrate-paths)    MIGRATE_PATHS=1 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done
# No terminal on stdin (cron, piped) — never hang on a prompt.
[ -t 0 ] || INTERACTIVE=0

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
# OUTPUT_DIR is deliberately NOT filled in: local PDF copies are opt-in
# (the PDF carries the TOTP secret); $DATA_DIR/output exists if wanted.
sed -e "s|^LOG_DIR=.*|LOG_DIR=$LOG_DIR|" \
    -e "s|^PKEY_FILE=.*|PKEY_FILE=$CONF_DIR/ssh/oscar_db.key|" \
    "$SRC_DIR/.env.sample" > "$CONF_SAMPLE"
chmod 640 "$CONF_SAMPLE"

# --- migration helpers ----------------------------------------------------
# Read a variable's value from the conf, stripping quotes/trailing comments.
conf_get() {
    sed -n "s|^$1=||p" "$CONF_FILE" | head -1 \
        | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//'
}

conf_set() {
    sed -i "s|^$1=.*|$1=$2|" "$CONF_FILE"
    echo "    config: $1=$2"
}

# Resolve a .env value to an absolute path. Relative values in a checkout
# .env were resolved against the checkout directory; after migration the
# tool runs from /opt, so they must be pinned or data would silently move.
# ~-prefixed values are left for the shell to expand (never checkout-relative).
resolve_path() {
    case "$1" in
        ""|/*|"~"*) echo "$1" ;;
        *) readlink -f "$SRC_DIR/$1" 2>/dev/null || echo "$SRC_DIR/$1" ;;
    esac
}

# Ask a single-letter choice; sets $CHOICE. prompt_choice "text" "kmd" "k"
prompt_choice() {
    while :; do
        printf "%s [%s] (default %s): " "$1" "$2" "$3"
        read -r CHOICE || CHOICE=""
        CHOICE=$(echo "${CHOICE:-$3}" | tr 'A-Z' 'a-z' | cut -c1)
        case "$2" in *"$CHOICE"*) return 0 ;; esac
        echo "    Please answer one of: $2"
    done
}

# Interactively migrate one path parameter: keep it where it is, or move
# the existing files to the FHS default and point the config there.
#   migrate_var VAR DEFAULT KIND GLOB
# KIND: dir  — a directory; matching files are moved
#       file — a single file (e.g. the SSH key)
# For OUTPUT_DIR a third option offers disabling local copies entirely.
migrate_var() {
    _var=$1; _default=$2; _kind=$3; _glob=$4
    _cur=$(resolve_path "$(conf_get "$_var")")
    case "$_cur" in ""|"~"*) return 0 ;; esac      # unset or $HOME-based: leave
    [ "$_cur" = "$_default" ] && { conf_set "$_var" "$_cur"; return 0; }

    if [ "$_kind" = "dir" ]; then
        _n=$(find "$_cur" -maxdepth 1 -name "$_glob" -type f 2>/dev/null | wc -l)
        _what="$_n file(s) matching $_glob"
    else
        [ -f "$_cur" ] && _n=1 || _n=0
        _what="the file"
    fi

    echo ""
    echo "  $_var is currently: $_cur ($_what there)"
    if [ "$INTERACTIVE" = "0" ]; then
        conf_set "$_var" "$_cur"
        echo "    (non-interactive: kept in place)"
        return 0
    fi

    _choices="km"; _menu="    [k] keep it there
    [m] move existing file(s) to $_default and use that from now on"
    if [ "$_var" = "OUTPUT_DIR" ]; then
        _choices="kmd"
        _menu="$_menu
    [d] disable local PDF copies (recommended — the PDFs contain the
        TOTP secret; existing files are left for you to review/shred)"
    fi
    echo "$_menu"
    prompt_choice "  Choose" "$_choices" "k"

    case "$CHOICE" in
        k) conf_set "$_var" "$_cur" ;;
        d) conf_set "$_var" "" ;;
        m)
            if [ "$_kind" = "file" ]; then
                mkdir -p "$(dirname "$_default")"
                if [ -f "$_cur" ]; then
                    mv "$_cur" "$_default"
                    chmod 600 "$_default"
                    echo "    moved: $_cur → $_default"
                else
                    echo "    note: $_cur does not exist yet; nothing to move."
                fi
                conf_set "$_var" "$_default"
            else
                mkdir -p "$_default"
                if [ "$_n" -gt 0 ]; then
                    find "$_cur" -maxdepth 1 -name "$_glob" -type f \
                        -exec mv {} "$_default"/ \;
                    echo "    moved: $_n file(s) → $_default/"
                fi
                rmdir "$_cur" 2>/dev/null && echo "    removed empty dir: $_cur" || true
                conf_set "$_var" "$_default"
            fi
            ;;
    esac
}

# Run the keep-or-move review over every path parameter in $CONF_FILE.
migrate_paths() {
    migrate_var OUTPUT_DIR "$DATA_DIR/output"           dir  "*.pdf"
    migrate_var LOG_DIR    "$LOG_DIR"                   dir  "provision.log*"
    migrate_var PKEY_FILE  "$CONF_DIR/ssh/oscar_db.key" file "-"
    # NEXTCLOUD_DIR is an external mount — no FHS default to move to; just
    # pin a checkout-relative value to its absolute location.
    _nc=$(conf_get NEXTCLOUD_DIR)
    _ncr=$(resolve_path "$_nc")
    [ "$_nc" != "$_ncr" ] && conf_set NEXTCLOUD_DIR "$_ncr" || true
}

if [ ! -f "$CONF_FILE" ]; then
    if [ -f "$SRC_DIR/.env" ]; then
        # Migrate an existing checkout deployment: values are kept verbatim,
        # then each path parameter is offered a keep-or-move choice.
        echo "Migrating existing $SRC_DIR/.env to $CONF_FILE ..."
        cp "$SRC_DIR/.env" "$CONF_FILE"
        chmod 600 "$CONF_FILE"
        migrate_paths
        NEW_CONF=migrated
    else
        cp "$CONF_SAMPLE" "$CONF_FILE"
        chmod 600 "$CONF_FILE"
        NEW_CONF=1
    fi
else
    chmod 600 "$CONF_FILE"
    NEW_CONF=0
    if [ "$MIGRATE_PATHS" = "1" ]; then
        echo "Reviewing path parameters in $CONF_FILE (--migrate-paths) ..."
        migrate_paths
    fi
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
