#!/usr/bin/env python3
"""Build a WordPress theme from the static clone in html-backup/.

Usage:  python3 -I build_theme.py <html_dir> <theme_dir>

Each captured page becomes a complete WordPress template:
  index.html                -> front-page.php         (homepage)
  about-us/index.html       -> page-about-us.php
  contact/index.html        -> page-contact.php
  news/index.html           -> page-news.php
  category/news/index.html  -> category-news.php
  <post>/index.html         -> single-post-<post>.php

Site-local links become home_url() calls and files under wp-content/ are loaded
with content_url(), so the theme works wherever WordPress is installed.
Author archives are skipped because they need real WordPress users.

Stdlib only. Re-running overwrites the generated files in theme_dir.
"""
import html
import os
import posixpath
import re
import shutil
import subprocess
import sys

SITE_SUFFIX = " - TNT Private Boxing"
PAGE_TEMPLATES = {
    "about-us": ("page-about-us.php", "About us"),
    "contact": ("page-contact.php", "Contact"),
    "news": ("page-news.php", "News"),
}
CATEGORY_DIR = "category/news"
CATEGORY_TEMPLATE = "category-news.php"
SKIP_REF = ("http:", "https:", "//", "data:", "mailto:", "tel:", "javascript:", "#", "<?", "{", "$")

# WordPress-generated <head> items that point at the old site or are redundant.
HEAD_DROP = [
    re.compile(r"""<link\b[^>]*\brel=["'](?:alternate|canonical|shortlink|EditURI|pingback|https://api\.w\.org/)[^>]*>[ \t]*\n?""", re.I),
    re.compile(
        r"""<meta\b(?![^>]*(?:charset|name=["']viewport|name=["']description|"""
        r"""property=["']og:(?:title|description|type|site_name|locale)["']))[^>]*>[ \t]*\n?""",
        re.I,
    ),
    re.compile(r"""<script\b[^>]*application/ld\+json[^>]*>.*?</script>[ \t]*\n?""", re.I | re.S),
]
ATTR_RE = re.compile(
    r"""(\s(?:href|src|srcset|poster|action|data-src|data-srcset|data-lazy-src)\s*=\s*)(["'])(.*?)\2""",
    re.I | re.S,
)
# (?<![\w-]) keeps this from matching inside PHP output such as content_url( or home_url(.
CSS_URL_RE = re.compile(r"""(?<![\w-])url\(\s*(["']?)([^"')\s]+)\1\s*\)""", re.I)
SCRIPT_SPLIT_RE = re.compile(r"(<script\b[^>]*>.*?</script>)", re.I | re.S)
# wp-content paths inside inline JavaScript/JSON config, e.g. "../wp-content/..." or the
# JSON-escaped "..\/wp-content\/..." (also inside space-separated srcset strings). The match
# ends at whitespace, comma, or quote; the lookbehind skips root-relative "/wp-content".
SCRIPT_WP_CONTENT_RE = re.compile(r"""(?<![\w/\\:.])(?:\.\.\\?/)*wp-content(?:\\?/[^\s"',\\<>()]+)+""")


def script_wp_content(m, base_dir):
    path = m.group(0).replace("\\/", "/")
    new = fix_ref(path, base_dir)
    return m.group(0) if new == path else new


def php_str(value):
    """Return value as a single-quoted PHP string literal."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def fix_ref(ref, base_dir):
    """Turn one site-local reference into PHP that outputs the WordPress URL."""
    if not ref or ref != ref.strip() or ref.startswith(SKIP_REF):
        return ref
    body, has_hash, frag = ref.partition("#")
    frag = "#" + frag if has_hash else ""
    path, has_q, query = body.partition("?")
    query = "?" + query if has_q else ""
    if not path:
        return ref

    if path.startswith("/"):
        resolved = path.lstrip("/")
    else:
        resolved = posixpath.normpath(posixpath.join(base_dir, path))
    if resolved == ".":
        resolved = ""
    if resolved.startswith(".."):
        return ref  # points outside the site; leave untouched

    # Page links: "index.html" and "<dir>/index.html" become home_url('/<dir>/').
    if resolved in ("", "index.html") or resolved.endswith("/index.html"):
        dirpart = "" if resolved in ("", "index.html") else posixpath.dirname(resolved)
        url_path = "/" + (dirpart + "/" if dirpart else "")
        return "<?php echo esc_url( home_url( %s ) ); ?>%s" % (php_str(url_path), frag)

    # Theme/plugin/upload assets live under wp-content/.
    if resolved.startswith("wp-content/"):
        rest = resolved[len("wp-content/"):] + query
        return "<?php echo esc_url( content_url( %s ) ); ?>%s" % (php_str(rest), frag)

    return "<?php echo esc_url( home_url( %s ) ); ?>%s" % (php_str("/" + resolved + query), frag)


def fix_attrs(fragment, base_dir):
    def repl(m):
        name, quote, value = m.group(1), m.group(2), m.group(3)
        if "srcset" in name.lower():
            cands = []
            for cand in value.split(","):
                cand = cand.strip()
                if not cand:
                    continue
                bits = cand.split(None, 1)
                new = fix_ref(bits[0], base_dir)
                cands.append(new + (" " + bits[1] if len(bits) > 1 else ""))
            return name + quote + ", ".join(cands) + quote
        return name + quote + fix_ref(value, base_dir) + quote

    return ATTR_RE.sub(repl, fragment)


def fix_css(text, base_dir):
    def repl(m):
        q, ref = m.group(1), m.group(2)
        new = fix_ref(ref, base_dir)
        if new == ref:
            return m.group(0)
        return "url(" + q + new + q + ")"

    return CSS_URL_RE.sub(repl, text)


def fix_markup(text, base_dir):
    """Rewrite references in HTML, leaving script bodies (JavaScript) untouched."""
    out = []
    for part in SCRIPT_SPLIT_RE.split(text):
        if not part:
            continue
        if part[:7].lower() == "<script":
            end = part.index(">") + 1
            body = SCRIPT_WP_CONTENT_RE.sub(lambda m: script_wp_content(m, base_dir), part[end:])
            out.append(fix_attrs(part[:end], base_dir) + body)
        else:
            # CSS first, so the attribute pass never sees the PHP it just wrote.
            out.append(fix_attrs(fix_css(part, base_dir), base_dir))
    return "".join(out)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def page_title(text):
    m = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
    return html.unescape(m.group(1).strip()) if m else ""


def strip_suffix(title):
    return title[: -len(SITE_SUFFIX)] if title.endswith(SITE_SUFFIX) else title


def build_template(src_path, rel_src, base_dir):
    """Return the full PHP template text for one captured page."""
    text = read(src_path)
    m_head = re.search(r"<head\b[^>]*>(.*?)</head>", text, re.I | re.S)
    m_body = re.search(r"<body\b([^>]*)>", text, re.I)
    m_end = text.rfind("</body>")
    if not (m_head and m_body and m_end > m_body.end()):
        raise SystemExit(f"unexpected page structure: {rel_src}")

    doctype = text[: m_head.start()]
    head_inner = m_head.group(1)
    for rx in HEAD_DROP:
        head_inner = rx.sub("", head_inner)
    head_inner = fix_markup(head_inner, base_dir)

    body_attrs = m_body.group(1)
    body_inner = fix_markup(text[m_body.end():m_end], base_dir)
    tail = text[m_end + len("</body>"):]

    banner = (
        "<?php\n/**\n * Generated from html-backup/" + rel_src
        + " by scripts/build_theme.py. Edit freely.\n */\n?>\n"
    )
    return (
        banner
        + doctype
        + "<head>"
        + head_inner
        + "\n<?php wp_head(); ?>\n</head>\n"
        + "<body" + body_attrs + ">\n<?php wp_body_open(); ?>"
        + body_inner
        + "<?php wp_footer(); ?>\n</body>"
        + tail
    )


def check_template(name, src_text, out_text):
    problems = []
    if out_text.count("<?php") != out_text.count("?>"):
        problems.append("unbalanced PHP tags")
    for tag in ("div", "section", "main", "header", "footer", "nav", "ul", "a"):
        src_n = len(re.findall(rf"<{tag}\b", src_text, re.I))
        out_n = len(re.findall(rf"<{tag}\b", out_text, re.I))
        if src_n != out_n:
            problems.append(f"<{tag}> count {src_n} -> {out_n}")
    if "wp_head()" not in out_text or "wp_footer()" not in out_text:
        problems.append("missing wp_head/wp_footer")
    if re.search(r"laboxinggym|la\s+boxing", out_text, re.I):
        problems.append("old brand still present")
    if re.search(r"(?:home_url|content_url)\(\s*'[^']*<\?php", out_text):
        problems.append("PHP nested inside PHP")
    status = "ok" if not problems else "CHECK: " + "; ".join(problems)
    print(f"  {name:<40} {status}")
    return not problems


FUNCTIONS_PHP = r"""<?php
/**
 * TNT Private Boxing theme setup.
 *
 * Generated by scripts/build_theme.py. On activation this creates the pages,
 * posts and category that the templates in this theme are named after, and
 * shows the latest-posts homepage through front-page.php.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Pages, posts and categories the templates expect to exist.
 *
 * @return array
 */
function tnt_pb_content_map() {
	return array(
		'pages'      => array(
__PAGES__
		),
		'posts'      => array(
__POSTS__
		),
		'categories' => array(
			array( 'slug' => 'news', 'name' => 'News' ),
		),
	);
}

/**
 * Create the content the templates depend on, skipping anything that exists.
 */
function tnt_pb_setup_content() {
	$map = tnt_pb_content_map();

	foreach ( $map['categories'] as $cat ) {
		if ( ! term_exists( $cat['slug'], 'category' ) ) {
			wp_insert_term( $cat['name'], 'category', array( 'slug' => $cat['slug'] ) );
		}
	}
	$news_term = get_term_by( 'slug', 'news', 'category' );
	$news_id   = $news_term ? (int) $news_term->term_id : 0;

	foreach ( $map['pages'] as $page ) {
		if ( ! get_page_by_path( $page['slug'], OBJECT, 'page' ) ) {
			wp_insert_post(
				array(
					'post_type'   => 'page',
					'post_status' => 'publish',
					'post_title'  => $page['title'],
					'post_name'   => $page['slug'],
				)
			);
		}
	}

	foreach ( $map['posts'] as $post ) {
		if ( get_page_by_path( $post['slug'], OBJECT, 'post' ) ) {
			continue;
		}
		wp_insert_post(
			array(
				'post_type'     => 'post',
				'post_status'   => 'publish',
				'post_title'    => $post['title'],
				'post_name'     => $post['slug'],
				'post_category' => $news_id ? array( $news_id ) : array(),
			)
		);
	}

	// Homepage shows latest posts, so WordPress uses front-page.php for "/".
	update_option( 'show_on_front', 'posts' );
	update_option( 'permalink_structure', '/%postname%/' );
	flush_rewrite_rules();
}
add_action( 'after_switch_theme', 'tnt_pb_setup_content' );
"""

INDEX_PHP = """<?php
/**
 * Fallback template for any view that has no dedicated template.
 */
?>
<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo( 'charset' ); ?>">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?php echo esc_html( wp_get_document_title() ); ?></title>
<?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<main id="content" style="max-width:860px;margin:0 auto;padding:40px 16px;">
<?php if ( have_posts() ) : ?>
	<?php while ( have_posts() ) : the_post(); ?>
		<article <?php post_class(); ?>>
			<h1><?php the_title(); ?></h1>
			<?php the_content(); ?>
		</article>
	<?php endwhile; ?>
<?php else : ?>
	<p><?php esc_html_e( 'Nothing found.', 'tnt-private-boxing' ); ?></p>
<?php endif; ?>
</main>
<?php wp_footer(); ?>
</body>
</html>
"""

NOT_FOUND_PHP = """<?php
/**
 * 404 template.
 */
?>
<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo( 'charset' ); ?>">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?php echo esc_html( wp_get_document_title() ); ?></title>
<?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<main id="content" style="max-width:860px;margin:0 auto;padding:40px 16px;">
	<h1><?php esc_html_e( 'Page not found', 'tnt-private-boxing' ); ?></h1>
	<p><a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php esc_html_e( 'Back to the homepage', 'tnt-private-boxing' ); ?></a></p>
</main>
<?php wp_footer(); ?>
</body>
</html>
"""

STYLE_CSS = """/*
Theme Name: TNT Private Boxing
Description: Templates cloned from the original gym site and renamed to TNT Private Boxing. Styling comes from the copied Neve/Elementor assets in wp-content/.
Version: 1.0.0
Text Domain: tnt-private-boxing
*/
"""


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    html_dir = os.path.abspath(sys.argv[1])
    theme_dir = os.path.abspath(sys.argv[2])
    os.makedirs(theme_dir, exist_ok=True)

    jobs = []  # (template_name, source_rel, base_dir)
    posts = []
    print("Templates:")
    jobs.append(("front-page.php", "index.html", ""))

    for name in sorted(os.listdir(html_dir)):
        path = os.path.join(html_dir, name)
        if not os.path.isdir(path) or name in ("wp-content", "wp-includes", "author", "category"):
            continue
        index = os.path.join(path, "index.html")
        if not os.path.isfile(index):
            continue
        text = read(index)
        if name in PAGE_TEMPLATES:
            jobs.append((PAGE_TEMPLATES[name][0], name + "/index.html", name))
        elif re.search(r'class="[^"]*\bsingle-post\b', text):
            jobs.append(("single-post-" + name + ".php", name + "/index.html", name))
            posts.append((name, strip_suffix(page_title(text))))
        else:
            print(f"  skipped {name}/ (no template mapping)")

    category_index = os.path.join(html_dir, CATEGORY_DIR, "index.html")
    if os.path.isfile(category_index):
        jobs.append((CATEGORY_TEMPLATE, CATEGORY_DIR + "/index.html", CATEGORY_DIR))

    all_ok = True
    for template, rel_src, base_dir in jobs:
        src_path = os.path.join(html_dir, rel_src)
        src_text = read(src_path)
        out_text = build_template(src_path, rel_src, base_dir)
        with open(os.path.join(theme_dir, template), "w", encoding="utf-8", newline="") as f:
            f.write(out_text)
        all_ok &= check_template(template, src_text, out_text)

    pages_php = []
    for slug, (_, title) in PAGE_TEMPLATES.items():
        pages_php.append(f"\t\t\tarray( 'slug' => {php_str(slug)}, 'title' => {php_str(title)} ),")
    posts_php = [
        f"\t\t\tarray( 'slug' => {php_str(slug)}, 'title' => {php_str(title)} ),"
        for slug, title in posts
    ]
    functions = (
        FUNCTIONS_PHP.replace("__PAGES__", "\n".join(pages_php))
        .replace("__POSTS__", "\n".join(posts_php))
    )
    with open(os.path.join(theme_dir, "functions.php"), "w", encoding="utf-8") as f:
        f.write(functions)
    for name, body in (
        ("index.php", INDEX_PHP),
        ("404.php", NOT_FOUND_PHP),
        ("style.css", STYLE_CSS),
    ):
        with open(os.path.join(theme_dir, name), "w", encoding="utf-8") as f:
            f.write(body)

    print(f"\nWrote {len(jobs)} templates + functions.php, index.php, 404.php, style.css")
    print("All checks passed." if all_ok else "Some checks need a look (see CHECK lines).")

    php = shutil.which("php")
    if php:
        bad = []
        for name in sorted(os.listdir(theme_dir)):
            if name.endswith(".php"):
                res = subprocess.run([php, "-l", os.path.join(theme_dir, name)],
                                     capture_output=True, text=True)
                if res.returncode != 0:
                    bad.append(name)
        print("php -l: all files parse." if not bad else f"php -l failed: {', '.join(bad)}")
    else:
        print("php not found; skipped php -l.")


if __name__ == "__main__":
    main()
