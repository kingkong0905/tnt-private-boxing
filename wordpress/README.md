# TNT Private Boxing: WordPress project

Built from the static clone in `../html-backup/` (the backup, rebranded to TNT Private Boxing).

## What's here

- `wp-content/themes/tnt-private-boxing/`: the theme. One template per captured page:
  `front-page.php` (home), `page-about-us.php`, `page-contact.php`, `page-news.php`,
  `category-news.php`, and one `single-post-<slug>.php` per news post.
- `wp-content/` (everything else): images, video, and the CSS/JS from the original site
  (Neve theme and Elementor assets). The templates load these.
- `docker-compose.yml`: WordPress 6 + MariaDB for local use.

## Run it locally

1. Install Docker Desktop.
2. From this folder: `docker compose up -d`
3. Open http://localhost:8080 and finish the WordPress setup (admin user, etc.).
4. Go to **Appearance > Themes** and activate **TNT Private Boxing**.
   Activation creates the About us, Contact and News pages, the five news posts,
   and the News category, and sets the homepage to show latest posts (which uses `front-page.php`).
5. Stop with `docker compose down`. Add `-v` to also delete the database.

## Regenerate the theme from the clone

From the project root:

    python3 scripts/build_theme.py html-backup wordpress/wp-content/themes/tnt-private-boxing

This overwrites the generated template files. Edits made by hand in the theme will be lost.

## Still needs your input

- **Logo.** The logo images (`wp-content/uploads/2024/10/logo.png` and `cropped-logo-*.png`)
  are the original gym's artwork and still show the old name. Replace them.
- **Contact details.** The email is a placeholder (`hello@example.com`), and the Facebook and
  Instagram links are `#`. Put TNT's real details in.
- **Location and claims.** The copy still says "Downtown Los Angeles" and "No.1 Boxing Gym".
  Check both against TNT's real location and marketing.
- **Contact form.** The contact page has Contact Form 7 markup. It won't send mail until that
  plugin is installed and configured.
- **Author pages.** The original author archive pages are not included.
- **Themes list.** `wp-content/themes/neve/` holds only the Neve CSS that the templates load.
  It shows in WordPress's theme list. Don't activate it.
- **Editing.** The pages are static templates. Text changes go into the theme's PHP files,
  not the WordPress page editor.
- **Size.** The copied video (`Boxing_Video_Ver1.mp4`) is about 49 MB.
