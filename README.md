# TNT Private Boxing

Website for TNT Private Boxing, a boxing gym. The site started as a static copy of an
existing gym site, which was rebranded and then turned into a WordPress theme.

## Repository layout

| Path | What it is |
| --- | --- |
| `html-backup/` | Static HTML copy of the site (pages, posts, and the assets they load). The source for the theme. |
| `scripts/` | Python 3 tools (standard library only). See below. |
| `wordpress/` | Local WordPress setup: `docker-compose.yml` (WordPress 6 + MariaDB) and `wp-content/` with the theme and the copied plugins and assets. |

## How the pieces fit together

1. **`scripts/mirror.py`** downloads the public pages and assets of the original site into a
   folder, and rewrites site-local links to relative paths. It fetches from the live site, so it
   needs network access.
2. **`scripts/rebrand.py`** renames the old brand to "TNT Private Boxing" in that folder.
   Real identifiers of the original business (social handles, email, domain) are replaced
   with placeholders. This produced `html-backup/`.
3. **`scripts/build_theme.py`** turns `html-backup/` into a WordPress theme at
   `wordpress/wp-content/themes/tnt-private-boxing/`: one PHP template per captured page, plus
   `functions.php`.

```sh
# Regenerate the theme from the static copy (run from the repository root)
python3 scripts/build_theme.py html-backup wordpress/wp-content/themes/tnt-private-boxing
```

The generated templates are overwritten on every run. Make changes in `scripts/build_theme.py`
(or in WordPress itself, for content and menus), not by hand in the generated files.

## Running the site locally

Requires Docker. The full steps are in [`wordpress/README.md`](wordpress/README.md). In short:

```sh
cd wordpress
docker compose up -d        # then open http://localhost:8080
```

Finish the WordPress setup, then activate **TNT Private Boxing** under Appearance > Themes.
Activation creates the About us, Contact and News pages and the news posts.

## Managing content

- **Menus:** Appearance > Menus. The header and footer menus both read the menu assigned to the
  primary location.
- **Page text:** the About us, Contact and News pages are generated templates, so their text is
  edited in the theme files. The WordPress "Sample Page" (`/sample-page/`) uses the About us
  layout with its body edited in wp-admin.

## Open items

These are tracked in [`wordpress/README.md`](wordpress/README.md#still-needs-your-input):

- The logo is still the original gym's artwork.
- Contact details (email, social links) are placeholders.
- Location and marketing claims still need checking against the real business.
- The contact form needs Contact Form 7 configured before it sends mail.
