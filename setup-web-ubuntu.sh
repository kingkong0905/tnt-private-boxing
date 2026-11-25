#!/usr/bin/env bash
# Serve the TNT Private Boxing WordPress site on an Ubuntu server for a domain name.
#
# Usage:   ./setup-web-ubuntu.sh
#
# Run setup-ubuntu.sh first: this script uses the database it creates.
#
# What it does:
#   - installs Apache with the PHP module and the extensions WordPress needs
#   - installs WordPress core into WEB_ROOT, the document root for the domain
#   - links WEB_ROOT/wp-content to the project's wordpress/wp-content, so the theme,
#     plugins and uploads come from the repository
#   - writes wp-config.php for the database created by setup-ubuntu.sh
#   - creates and enables an Apache virtual host for DOMAIN
#   - optionally requests an HTTPS certificate from Let's Encrypt (set LETSENCRYPT_EMAIL)
#
# Optional environment overrides:
#   DOMAIN             site domain                 (default: tntprivateboxing.com)
#   WEB_ROOT           document root              (default: /var/www/$DOMAIN)
#   PROJECT_DIR        project checkout            (default: $HOME/tnt-private-boxing)
#   DB_NAME            database name              (default: wordpress)
#   DB_USER            database user              (default: wordpress)
#   DB_PASSWORD        database password          (default: wordpress)
#   LETSENCRYPT_EMAIL  email for certificates; set it to request HTTPS
#
# Before HTTPS is requested, the DNS A records for DOMAIN and www.DOMAIN must point to this
# server. The script does not change DNS. It is safe to run again.

set -euo pipefail

DOMAIN="${DOMAIN:-tntprivateboxing.com}"
WEB_ROOT="${WEB_ROOT:-/var/www/$DOMAIN}"
PROJECT_DIR="${PROJECT_DIR:-$HOME/tnt-private-boxing}"
DB_NAME="${DB_NAME:-wordpress}"
DB_USER="${DB_USER:-wordpress}"
DB_PASSWORD="${DB_PASSWORD:-wordpress}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"

WP_CONTENT_SRC="$PROJECT_DIR/wordpress/wp-content"
SITE_CONF="/etc/apache2/sites-available/$DOMAIN.conf"

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "DOMAIN may only contain letters, digits, . and -"
[[ "$WEB_ROOT" == /* ]] || die "WEB_ROOT must be an absolute path"
[[ "$DB_NAME" =~ ^[A-Za-z0-9_]+$ ]] || die "DB_NAME may only contain letters, digits and _"
[[ "$DB_USER" =~ ^[A-Za-z0-9_]+$ ]] || die "DB_USER may only contain letters, digits and _"
[[ "$DB_PASSWORD" =~ ^[A-Za-z0-9._@%+=-]+$ ]] || die "DB_PASSWORD may only contain letters, digits and ._@%+=-"
if [[ -n "$LETSENCRYPT_EMAIL" ]]; then
    [[ "$LETSENCRYPT_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+$ ]] || die "LETSENCRYPT_EMAIL is not an email address"
fi

if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=""
else
    command -v sudo >/dev/null || die "sudo is needed to install packages and write system files"
    SUDO="sudo"
fi

[[ -r /etc/os-release ]] || die "cannot read /etc/os-release"
# shellcheck disable=SC1091
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "this script is for Ubuntu (found: ${PRETTY_NAME:-unknown})"

export DEBIAN_FRONTEND=noninteractive

# Run a command as www-data, which is the user Apache runs PHP as.
as_www() {
    if [[ "$(id -u)" -eq 0 ]]; then
        runuser -u www-data -- "$@"
    else
        sudo -u www-data -- "$@"
    fi
}

# Start, restart or reload a service with systemd when it is running, otherwise with service.
svc() {
    if [[ -d /run/systemd/system ]]; then
        $SUDO systemctl "$1" "$2"
    else
        $SUDO service "$2" "$1"
    fi
}

log "Checking the project and the database"
[[ -d "$WP_CONTENT_SRC" ]] || die "no wordpress/wp-content in $PROJECT_DIR; run setup-ubuntu.sh first or set PROJECT_DIR"
command -v mysql >/dev/null || die "the mysql client is missing; run setup-ubuntu.sh first"
MYSQL_PWD="$DB_PASSWORD" mysql -h 127.0.0.1 -u "$DB_USER" "$DB_NAME" -e "SELECT 1;" >/dev/null \
    || die "could not connect as '$DB_USER' to '$DB_NAME'; run setup-ubuntu.sh first"

log "Installing Apache, PHP and the tools this script uses"
$SUDO apt-get update
$SUDO apt-get install -y apache2 libapache2-mod-php php-mysql php-curl php-gd php-mbstring \
    php-xml php-zip php-intl php-bcmath curl openssl tar
if [[ -e /etc/apache2/mods-enabled/mpm_event.load ]]; then
    # mod_php needs the prefork MPM.
    $SUDO a2dismod -q mpm_event
    $SUDO a2enmod -q mpm_prefork
fi
$SUDO a2enmod -q rewrite headers

log "Checking that Apache's PHP user can read the project"
if ! as_www test -x "$WP_CONTENT_SRC" || ! as_www test -r "$WP_CONTENT_SRC/themes"; then
    die "www-data cannot read $WP_CONTENT_SRC. Make its parent folders readable (for example: chmod o+x \"$HOME\") or set PROJECT_DIR"
fi

install_core() {
    if [[ -f "$WEB_ROOT/wp-settings.php" ]]; then
        log "WordPress core is already in $WEB_ROOT"
        return
    fi
    log "Downloading WordPress into $WEB_ROOT"
    local tmp
    tmp="$(mktemp -d)"
    curl -fsSL https://wordpress.org/latest.tar.gz -o "$tmp/wordpress.tar.gz"
    tar -xzf "$tmp/wordpress.tar.gz" -C "$tmp"
    $SUDO mkdir -p "$WEB_ROOT"
    # Copy everything except the default wp-content: the project's wp-content is linked below.
    local item
    for item in "$tmp"/wordpress/*; do
        [[ "$(basename "$item")" == "wp-content" ]] && continue
        $SUDO cp -a "$item" "$WEB_ROOT/"
    done
    rm -rf "$tmp"
}

link_content() {
    local target="$WEB_ROOT/wp-content"
    if [[ -L "$target" && "$(readlink -f "$target")" == "$(readlink -f "$WP_CONTENT_SRC")" ]]; then
        log "wp-content is already linked to the project"
        return
    fi
    if [[ -e "$target" && ! -L "$target" ]]; then
        die "$target already exists and is not a link. Move it aside, then run this script again"
    fi
    log "Linking $target to $WP_CONTENT_SRC"
    $SUDO ln -sfn "$WP_CONTENT_SRC" "$target"
}

write_config() {
    local cfg="$WEB_ROOT/wp-config.php"
    if [[ -f "$cfg" ]]; then
        log "wp-config.php already exists; keeping it"
        return
    fi
    log "Writing wp-config.php"
    local tmp key
    tmp="$(mktemp)"
    cat > "$tmp" <<PHP
<?php
define( 'DB_NAME', '$DB_NAME' );
define( 'DB_USER', '$DB_USER' );
define( 'DB_PASSWORD', '$DB_PASSWORD' );
define( 'DB_HOST', '127.0.0.1' );
define( 'DB_CHARSET', 'utf8mb4' );
define( 'DB_COLLATE', '' );

PHP
    for key in AUTH_KEY SECURE_AUTH_KEY LOGGED_IN_KEY NONCE_KEY \
               AUTH_SALT SECURE_AUTH_SALT LOGGED_IN_SALT NONCE_SALT; do
        printf "define( '%s', '%s' );\n" "$key" "$(openssl rand -hex 32)" >> "$tmp"
    done
    cat >> "$tmp" <<'PHP'

$table_prefix = 'wp_';
define( 'WP_DEBUG', false );
define( 'DISALLOW_FILE_EDIT', true );

if ( ! defined( 'ABSPATH' ) ) {
	define( 'ABSPATH', __DIR__ . '/' );
}
require_once ABSPATH . 'wp-settings.php';
PHP
    $SUDO install -m 640 -o www-data -g www-data "$tmp" "$cfg"
    rm -f "$tmp"
}

write_vhost() {
    log "Configuring Apache for $DOMAIN"
    local tmp
    tmp="$(mktemp)"
    cat > "$tmp" <<CONF
<VirtualHost *:80>
    ServerName $DOMAIN
    ServerAlias www.$DOMAIN
    DocumentRoot $WEB_ROOT

    <Directory $WEB_ROOT>
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    ErrorLog \${APACHE_LOG_DIR}/$DOMAIN-error.log
    CustomLog \${APACHE_LOG_DIR}/$DOMAIN-access.log combined
</VirtualHost>
CONF
    $SUDO install -m 644 "$tmp" "$SITE_CONF"
    rm -f "$tmp"
    $SUDO a2ensite -q "$DOMAIN.conf"
    $SUDO apache2ctl configtest
}

install_core
link_content
$SUDO chown -R www-data:www-data "$WEB_ROOT"
write_config
write_vhost

# WordPress stores uploads in wp-content/uploads, so Apache's user must be able to write there.
if [[ -d "$WP_CONTENT_SRC/uploads" ]]; then
    $SUDO chown -R www-data:www-data "$WP_CONTENT_SRC/uploads"
fi

if [[ -n "$LETSENCRYPT_EMAIL" ]]; then
    log "Requesting an HTTPS certificate for $DOMAIN"
    $SUDO apt-get install -y certbot python3-certbot-apache
    $SUDO a2enmod -q ssl
    $SUDO certbot --apache --non-interactive --agree-tos --redirect \
        -m "$LETSENCRYPT_EMAIL" -d "$DOMAIN" -d "www.$DOMAIN" \
        || warn "certbot failed. Check that DNS for $DOMAIN and www.$DOMAIN points to this server, then run this script again"
fi

log "Starting Apache"
svc restart apache2

log "Checking the site on this server"
status="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $DOMAIN" http://127.0.0.1/ || true)"
echo "http://$DOMAIN/ on this server answered $status (302 means WordPress is waiting for its installation)"
asset="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $DOMAIN" \
    http://127.0.0.1/wp-content/themes/tnt-private-boxing/style.css || true)"
echo "theme stylesheet through the domain answered $asset"

cat <<EOF

Web setup finished.

  Domain:         $DOMAIN and www.$DOMAIN
  Document root:  $WEB_ROOT
  wp-content:     $WP_CONTENT_SRC (linked as $WEB_ROOT/wp-content)

Next steps:
  1. Point the DNS A records for $DOMAIN and www.$DOMAIN at this server's public IP.
  2. Open http://$DOMAIN/ and finish the WordPress installation.
  3. In Appearance > Themes, activate TNT Private Boxing.
  4. For HTTPS, run again with LETSENCRYPT_EMAIL set once DNS points here.
EOF
