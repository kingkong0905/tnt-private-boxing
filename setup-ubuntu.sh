#!/usr/bin/env bash
# Set up the TNT Private Boxing project on Ubuntu: git, PHP, Python and MySQL.
#
# Usage:   ./setup-ubuntu.sh
#
# If this script is inside a checkout of the project, that checkout is used. Otherwise the
# project is cloned into PROJECT_DIR, or updated with a fast-forward pull if it already exists.
#
# Optional environment overrides:
#   PROJECT_DIR   where to clone the project   (default: $HOME/tnt-private-boxing)
#   REPO_URL      git URL to clone from        (default: the GitHub repository)
#   REPO_BRANCH   branch to clone              (default: main)
#   DB_NAME       database name                (default: wordpress; letters, digits and _)
#   DB_USER       database user                (default: wordpress; letters, digits and _)
#   DB_PASSWORD   database password            (default: wordpress; letters, digits and ._@%+=-)
#
# The database defaults match wordpress/docker-compose.yml. Set DB_PASSWORD for anything other
# than local development. The script installs packages with apt, so it asks for sudo when not
# run as root. It is safe to run again.

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/tnt-private-boxing}"
REPO_URL="${REPO_URL:-https://github.com/kingkong0905/tnt-private-boxing.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
DB_NAME="${DB_NAME:-wordpress}"
DB_USER="${DB_USER:-wordpress}"
DB_PASSWORD="${DB_PASSWORD:-wordpress}"

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ "$DB_NAME" =~ ^[A-Za-z0-9_]+$ ]] || die "DB_NAME may only contain letters, digits and _"
[[ "$DB_USER" =~ ^[A-Za-z0-9_]+$ ]] || die "DB_USER may only contain letters, digits and _"
# The password is written into SQL, so keep it to characters that need no escaping.
[[ "$DB_PASSWORD" =~ ^[A-Za-z0-9._@%+=-]+$ ]] || die "DB_PASSWORD may only contain letters, digits and ._@%+=-"

if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=""
else
    command -v sudo >/dev/null || die "sudo is needed to install packages"
    SUDO="sudo"
fi

[[ -r /etc/os-release ]] || die "cannot read /etc/os-release"
# shellcheck disable=SC1091
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "this script is for Ubuntu (found: ${PRETTY_NAME:-unknown})"

export DEBIAN_FRONTEND=noninteractive

log "Updating package lists"
$SUDO apt-get update

log "Installing git"
$SUDO apt-get install -y git

log "Installing PHP (CLI and the extensions WordPress uses)"
$SUDO apt-get install -y \
    php-cli php-mysql php-curl php-gd php-mbstring php-xml php-zip php-intl php-bcmath

log "Installing Python 3, pip and venv"
$SUDO apt-get install -y python3 python3-pip python3-venv

log "Installing MySQL Server"
$SUDO apt-get install -y mysql-server

setup_repo() {
    local script_dir top
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if top="$(git -C "$script_dir" rev-parse --show-toplevel 2>/dev/null)" \
        && [[ -f "$top/wordpress/docker-compose.yml" && -f "$top/scripts/build_theme.py" ]]; then
        PROJECT_DIR="$top"
        log "Using the project checkout this script is in: $PROJECT_DIR"
    elif [[ -d "$PROJECT_DIR/.git" ]]; then
        log "Updating the project in $PROJECT_DIR"
        if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain)" ]]; then
            warn "$PROJECT_DIR has local changes, so it was not updated"
        else
            git -C "$PROJECT_DIR" pull --ff-only
        fi
    else
        log "Cloning $REPO_URL ($REPO_BRANCH) into $PROJECT_DIR"
        git clone --branch "$REPO_BRANCH" "$REPO_URL" "$PROJECT_DIR"
    fi
}

setup_repo

log "Starting MySQL"
if [[ -d /run/systemd/system ]]; then
    $SUDO systemctl enable --now mysql
else
    $SUDO service mysql start
fi

log "Creating database '$DB_NAME' and user '$DB_USER'"
# Ubuntu's MySQL root account uses the auth_socket plugin, so the admin commands run through
# the system user (sudo mysql) rather than a password.
$SUDO mysql <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
SQL

log "Checking the database connection"
MYSQL_PWD="$DB_PASSWORD" mysql -h 127.0.0.1 -u "$DB_USER" "$DB_NAME" -e "SELECT VERSION();" \
    || die "could not connect as '$DB_USER' to '$DB_NAME'"

log "Checking installed versions"
git --version
php -v | head -n 1
php -m | grep -qi '^mysqli$' || die "the PHP mysqli extension is missing"
python3 --version
MYSQL_PWD="$DB_PASSWORD" mysql -h 127.0.0.1 -u "$DB_USER" -e "SELECT VERSION();" -N \
    | sed 's/^/MySQL server /'

cat <<EOF

Setup finished.

  Project:   $PROJECT_DIR
  Database:  $DB_NAME
  User:      $DB_USER
  Host:      127.0.0.1:3306

Connect with:  mysql -h 127.0.0.1 -u $DB_USER -p $DB_NAME

WordPress core is not in this repository. To run the site with Docker instead, see
$PROJECT_DIR/wordpress/README.md. The Python scripts in scripts/ use only the standard library.
EOF
