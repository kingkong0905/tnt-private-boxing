# TNT Private Boxing

Website for TNT Private Boxing, a boxing gym. The site started as a static copy of an
existing gym site, which was rebranded and then turned into a WordPress theme.

## Repository layout

| Path | What it is |
| --- | --- |
| `html-backup/` | Static HTML copy of the site (pages, posts, and the assets they load). The source for the theme. |
| `scripts/` | Python 3 tools (standard library only) that build the theme. See below. |
| `wordpress/` | WordPress setup: `docker-compose.yml` (WordPress 6 + MariaDB) and `wp-content/` with the theme, plugins and uploads. |
| `setup-ubuntu.sh` | Installs git, PHP, Python and MySQL on Ubuntu, clones the project, and creates the database. |
| `setup-web-ubuntu.sh` | Serves the site on Ubuntu for a domain: Apache, WordPress core, and the project's `wp-content`. |

## Git setup

Git gets the code, and it pushes your changes back to GitHub. Do this once per computer.
The Ubuntu setup script installs git for you (step 2 of path A below), so you only need the
steps for installing git on a machine where you don't run that script.

**Step 1. Install git.**

- **Ubuntu:** `sudo apt-get update && sudo apt-get install -y git`
- **macOS:** run `xcode-select --install`, or `brew install git` if you use Homebrew.

Check it works:

```sh
git --version
```

**Step 2. Tell git who you are.** Use the name and the email address of your GitHub account.
These appear on your commits.

```sh
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

**Step 3. Connect git to GitHub.** The repository is private, so cloning and pushing both need a
GitHub login. You need read access to clone and write access to push
`kingkong0905/tnt-private-boxing`. Choose one method:

- **GitHub CLI (HTTPS, the simplest option).** Install `gh` from
  [cli.github.com](https://cli.github.com) (on macOS, `brew install gh`), then run:

  ```sh
  gh auth login          # choose GitHub.com, HTTPS, and sign in through the browser
  gh auth setup-git      # lets git use that login
  ```

- **SSH key.** Create a key and add it to your GitHub account:

  ```sh
  ssh-keygen -t ed25519 -C "you@example.com"    # press Enter to accept the defaults
  cat ~/.ssh/id_ed25519.pub                     # copy this output
  ```

  On GitHub, open **Settings > SSH and GPG keys > New SSH key** and paste the key. Then test it:

  ```sh
  ssh -T git@github.com
  ```

  To use SSH, clone with `git@github.com:kingkong0905/tnt-private-boxing.git` instead of the
  HTTPS address below.

**Step 4. Get the project.**

```sh
git clone https://github.com/kingkong0905/tnt-private-boxing.git
cd tnt-private-boxing
git status
```

The `main` branch is the one to work from. A server that clones or pulls also needs a login:
use the GitHub CLI login from step 3, or a read-only deploy key (see the Ubuntu server path).
If git asks for a username, you are not logged in yet, so finish step 3 first.

**Step 5. Day-to-day use.**

- Get the latest changes: `git pull --ff-only` on `main`. The `--ff-only` flag stops the pull if
  your local copy has changes that would need a merge.
- For a change you want reviewed, create a branch, commit, push, and open a pull request:

  ```sh
  git checkout -b feat/short-description
  git add path/to/changed-file other-changed-file     # add the files you changed, by name
  git commit -m "feat(scope): what changed"
  git push -u origin feat/short-description
  gh pr create --base main                             # or open the PR on GitHub
  ```

- Do not add these to a commit: `.DS_Store`, and the WordPress folders that the Docker setup
  creates in `wordpress/wp-content/` (`akismet/`, `hello.php`, `twentytwenty*/`, and the
  `index.php` files in those folders). `git status` lists them as untracked. Check the list before you commit.

## Setup guide

Pick one path:

- **[A. Ubuntu server](#a-ubuntu-server)**: the live site, served for `tntprivateboxing.com`.
- **[B. Local with Docker](#b-local-with-docker)**: the site on your own computer at `http://localhost:8080`.

### A. Ubuntu server

You need Ubuntu 24.04, `sudo` access, and internet access. The scripts tell you if something
is missing.

The repository is private, so the server needs a GitHub login before step 1. Install git and
log in on the server with Git setup steps 1 and 3. A read-only deploy key also works: add the
server's public key under the repository's **Settings > Deploy keys**, then set
`REPO_URL=git@github.com:kingkong0905/tnt-private-boxing.git` when you run the setup script.

**Step 1. Get the setup script and run it.** Either clone the repository and run the script
from it, or download only the script. The script clones the project into `~/tnt-private-boxing`
when it is not run from a checkout.

```sh
# Option 1: clone the repository first
git clone https://github.com/kingkong0905/tnt-private-boxing.git
cd tnt-private-boxing

# Option 2: download only the script (uses the GitHub CLI login)
gh api repos/kingkong0905/tnt-private-boxing/contents/setup-ubuntu.sh \
  -H "Accept: application/vnd.github.raw" > setup-ubuntu.sh
```

**Step 2. Install PHP, Python, MySQL and create the database.**

```sh
chmod +x setup-ubuntu.sh
./setup-ubuntu.sh
```

This installs git, PHP with the extensions WordPress needs, Python 3 with pip and venv, and
MySQL Server. It then creates a database named `wordpress` and a user named `wordpress`.
Both defaults match `wordpress/docker-compose.yml`. For a server, set your own password:

```sh
DB_PASSWORD='choose-a-strong-password' ./setup-ubuntu.sh
```

Allowed characters: letters, digits, and `._@%+=-` for the password; letters, digits and `_`
for the names. The script ends by listing the database, user and host it created.

**Step 3. Point the domain at the server.** In your DNS provider, add two A records that point
to the server's public IP address:

| Name | Type | Value |
| --- | --- | --- |
| `tntprivateboxing.com` | A | the server's public IP |
| `www` | A | the server's public IP |

DNS changes can take a while to spread. HTTPS in step 5 needs them in place first.

**Step 4. Serve the site for the domain.**

```sh
cd ~/tnt-private-boxing
./setup-web-ubuntu.sh
```

Run it from the project folder, which is where step 1 puts the project.

This installs Apache and PHP, downloads WordPress core into `/var/www/tntprivateboxing.com`,
links that folder's `wp-content` to the project's `wordpress/wp-content`, writes
`wp-config.php` for the database from step 2, and enables the virtual host for the domain.
The site is then reachable over plain HTTP.

Apache runs PHP as `www-data`, so that user must be able to read the project. If your home
folder is not readable by others, the script stops with a message. Fix it with:

```sh
chmod o+x "$HOME"
```

or set a different project location with `PROJECT_DIR=/path/to/tnt-private-boxing`.

Optional settings for this script:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOMAIN` | `tntprivateboxing.com` | Domain served by Apache |
| `WEB_ROOT` | `/var/www/$DOMAIN` | WordPress core folder |
| `PROJECT_DIR` | `~/tnt-private-boxing` | Project checkout with `wordpress/wp-content` |
| `LETSENCRYPT_EMAIL` | empty | Set to request an HTTPS certificate (step 5) |

The database variables (`DB_NAME`, `DB_USER`, `DB_PASSWORD`) must match what step 2 created.

**Step 5. Turn on HTTPS (optional, once DNS points at the server).**

```sh
LETSENCRYPT_EMAIL='you@example.com' ./setup-web-ubuntu.sh
```

This requests a certificate from Let's Encrypt for both names and redirects HTTP to HTTPS.
Running the script again is safe. If the certificate request fails, check the DNS records from
step 3 and run the command again.

**Step 6. Finish the WordPress installation.** Open `http://tntprivateboxing.com/` (or
`https://` after step 5). Enter the site title, an admin username, a strong password and an
email address.

**Step 7. Activate the theme.** Go to **Appearance > Themes** and activate **TNT Private
Boxing**. Activation creates the About us, Contact and News pages and the news posts. On the
first page load after activation, the news posts get their images from the theme's `uploads`
folder.

**Step 8. Check the menu.** Go to **Appearance > Menus**. Make sure a menu is assigned to the
**Primary menu** location. The header and footer both read that menu. If none is assigned,
create one with Top, About, News, Class, Location, FAQ and Contact. Use `/#class`-style links
for the anchors on the home page.

**Step 9. Check the pages.** If a page such as `/sample-page/` or `/news/` shows "Page not
found", go to **Settings > Permalinks** and click **Save Changes** without changing anything.

**Troubleshooting**

- `could not read Username` or `Repository not found` during the clone: the server has no
  GitHub login with access to the repository. Finish Git setup step 3 on the server, then run
  the script again.
- `could not connect as 'wordpress'`: run `setup-ubuntu.sh` first, and use the same
  `DB_PASSWORD` for both scripts.
- `www-data cannot read ...`: see the `chmod o+x "$HOME"` note in step 4.
- Certificate request failed: the DNS records from step 3 must point at this server.
- A news card has no image: set a featured image on that post in wp-admin. New posts show
  images only once a featured image is set.

### B. Local with Docker

You need Docker with the Compose plugin (Docker Desktop on macOS, or the Docker engine on Linux).

**Step 1. Start WordPress and MariaDB.**

```sh
cd wordpress
docker compose up -d
```

**Step 2. Finish the installation.** Open `http://localhost:8080`, enter the site details and
an admin account.

**Step 3. Activate the theme.** Go to **Appearance > Themes** and activate **TNT Private
Boxing**. Then check **Appearance > Menus** as in Ubuntu step 8.

**Stop the site** with `docker compose down`. To also delete the database, run
`docker compose down -v`.

More detail is in [`wordpress/README.md`](wordpress/README.md).

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

To regenerate the theme, the WordPress stack must be running, because the script reads the
featured images from it (Docker path, step 1):

```sh
python3 scripts/build_theme.py html-backup wordpress/wp-content/themes/tnt-private-boxing
```

The generated templates are overwritten on every run. Make changes in `scripts/build_theme.py`
(or in WordPress itself, for content and menus), not by hand in the generated files.

## Managing content

- **Menus:** Appearance > Menus. The header and footer menus both read the menu assigned to the
  primary location.
- **Page text:** the About us and Contact pages are generated templates, so their text is edited
  in the theme files. The News page lists every published post, so new posts appear there
  automatically. The WordPress "Sample Page" (`/sample-page/`) uses the About us layout with its
  body edited in wp-admin.

## Open items

These are tracked in [`wordpress/README.md`](wordpress/README.md#still-needs-your-input):

- The logo is still the original gym's artwork.
- Contact details (email, social links) are placeholders.
- Location and marketing claims still need checking against the real business.
- The contact form needs Contact Form 7 configured before it sends mail.
