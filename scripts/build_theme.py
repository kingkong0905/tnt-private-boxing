#!/usr/bin/env python3
"""Build a WordPress theme from the static clone in html-backup/.

Usage:  python3 -I build_theme.py <html_dir> <theme_dir>

Each captured page becomes a complete WordPress template:
  index.html                -> front-page.php         (homepage)
  about-us/index.html       -> page-about-us.php
  contact/index.html        -> page-contact.php
  news/index.html           -> page-news.php          (cards loop over published posts)
  category/news/index.html  -> category-news.php
  about-us/index.html       -> page-sample-page.php   (WordPress "Sample Page", editable content)
  <post>/index.html         -> single-post-<post>.php

Site-local links become home_url() calls and files under wp-content/ are loaded
with content_url(), so the theme works wherever WordPress is installed.
Author archives are skipped because they need real WordPress users.

Stdlib only, but reading the featured images needs the WordPress stack running
(cd wordpress && docker compose up -d). Re-running overwrites the generated files in theme_dir.
"""
import html
import json
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
# The three menu lists in each captured page: Neve's desktop header and mobile sidebar, and
# the Elementor nav. Each is replaced with a call that prints the theme's primary menu in
# that list's markup, so the links are edited in WordPress admin (Appearance > Menus).
PRIMARY_NAV_LISTS = {
    "nv-primary-navigation-desktop-main": "header",
    "nv-primary-navigation-mobile-sidebar": "mobile",
    "menu-1-214be1b": "footer",
}
PRIMARY_NAV_RE = re.compile(
    r'<ul id="(' + "|".join(PRIMARY_NAV_LISTS) + r')" class="[^"]*">.*?</ul>', re.S
)


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


# The main content of the "Sample Page" template comes from the WordPress page, so its text is
# edited in wp-admin. The head title follows the page too.
MAIN_RE = re.compile(r'<main id="content"[^>]*>.*?</main>', re.S)
EDITABLE_MAIN = (
    '<main id="content" class="neve-main" tabindex="-1">\n'
    "<?php while ( have_posts() ) : the_post(); ?>\n"
    '<div style="max-width:748px;margin:0 auto;padding:60px 16px;">\n'
    "<h1><?php the_title(); ?></h1>\n"
    '<div class="entry-content"><?php the_content(); ?></div>\n'
    "</div>\n"
    "<?php endwhile; ?>\n"
    "</main>"
)
TITLE_RE = re.compile(r"<title>.*?</title>", re.S | re.I)
TITLE_PHP = "<title><?php echo esc_html( wp_get_document_title() ); ?></title>"


def apply_editable_content(text):
    """Replace the captured main content and head title with WordPress-driven output."""
    text = MAIN_RE.sub(lambda m: EDITABLE_MAIN, text, count=1)
    return TITLE_RE.sub(lambda m: TITLE_PHP, text, count=1)


# The news listing on /news/ is rebuilt from WordPress posts, so posts published in wp-admin
# appear there. The card markup is the captured Premium Blog card, filled from each post.
NEWS_WRAP_OPEN_RE = re.compile(r'<div class="premium-blog-wrap\b[^"]*"[^>]*>')
DIV_TAG_RE = re.compile(r"</?div\b")
NEWS_LOOP_OPEN = (
    "<?php $tnt_news = new WP_Query( array( 'post_type' => 'post', "
    "'post_status' => 'publish', 'nopaging' => true ) );\n"
    "while ( $tnt_news->have_posts() ) : $tnt_news->the_post(); ?>\n"
)
NEWS_LOOP_CLOSE = "<?php endwhile; wp_reset_postdata(); ?>\n"
NEWS_CARD = """<div class="premium-blog-post-outer-container" data-total="1">
<div class="premium-blog-post-container premium-blog-skin-classic">
<?php if ( has_post_thumbnail() ) : ?>
<div class="premium-blog-thumb-effect-wrapper">
<div class="premium-blog-thumbnail-container premium-blog-zoomin-effect">
<?php the_post_thumbnail( 'full' ); ?>
<div class="premium-blog-thumbnail-overlay">
<a class="elementor-icon" href="<?php the_permalink(); ?>" target="_self">
<span class="elementor-screen-only"><?php the_title(); ?></span>
</a>
</div>
</div>
</div>
<?php endif; ?>
<div class="premium-blog-content-wrapper">
<div class="premium-blog-inner-container">
<h2 class="premium-blog-entry-title">
<a href="<?php the_permalink(); ?>" target="_self"><?php the_title(); ?></a>
</h2>
<div class="premium-blog-entry-meta">
<span class="premium-blog-meta-separator">•</span>
<div class="premium-blog-post-time premium-blog-meta-data">
<i class="fa fa-calendar-alt" aria-hidden="true"></i>
<span><?php echo esc_html( get_the_date() ); ?></span>
</div>
</div>
</div>
<div class="premium-blog-content-inner-wrapper">
<p class="premium-blog-post-content"><?php echo esc_html( get_the_excerpt() ); ?></p>
</div>
</div>
</div>
</div>
"""


def apply_news_listing(text):
    """Replace the captured news cards with a loop over the published WordPress posts."""
    m = NEWS_WRAP_OPEN_RE.search(text)
    if not m:
        return text
    depth, end = 0, None
    for tag in DIV_TAG_RE.finditer(text, m.start()):
        depth += -1 if tag.group(0).startswith("</") else 1
        if depth == 0:
            end = text.index(">", tag.start()) + 1
            break
    if end is None:
        raise SystemExit("unbalanced <div> in the news listing")
    close = text.rindex("</div>", m.end(), end)  # the wrapper's own closing tag
    return text[: m.end()] + NEWS_LOOP_OPEN + NEWS_CARD + NEWS_LOOP_CLOSE + text[close:]


# Per-template rewrites, applied to the generated output and to the source used for checks.
TEMPLATE_TRANSFORMS = {
    "page-sample-page.php": apply_editable_content,
    "page-news.php": apply_news_listing,
}


def replace_primary_nav(text):
    """Swap each hard-coded menu list for a call that prints the primary menu."""
    return PRIMARY_NAV_RE.sub(
        lambda m: "<?php tnt_pb_primary_menu( '%s' ); ?>" % PRIMARY_NAV_LISTS[m.group(1)], text
    )


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
    if "<?" in text:
        # Captured text is copied into .php files, so a PHP tag in it would run on the site.
        raise SystemExit(f"refusing to copy PHP tags from html-backup/{rel_src}")
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
    body_inner = fix_markup(replace_primary_nav(text[m_body.end():m_end]), base_dir)
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
    if "tnt_pb_primary_menu(" not in out_text or PRIMARY_NAV_RE.search(out_text):
        problems.append("menu list not replaced")
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
 * posts and category that the templates in this theme are named after, the
 * primary menu (edit it in Appearance > Menus), and shows the latest-posts
 * homepage through front-page.php.
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
		'thumbnails' => array(
__THUMBS__
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

	tnt_pb_seed_primary_menu();

	// Homepage shows latest posts, so WordPress uses front-page.php for "/".
	update_option( 'show_on_front', 'posts' );
	update_option( 'permalink_structure', '/%postname%/' );
	flush_rewrite_rules();
}
add_action( 'after_switch_theme', 'tnt_pb_setup_content' );

/**
 * Attach the captured news images to the seeded posts as featured images. Each image is an
 * existing file in uploads/, registered in the media library without generating new sizes.
 * Posts that already have an image are skipped.
 */
function tnt_pb_seed_featured_images() {
	$map     = tnt_pb_content_map();
	$uploads = wp_get_upload_dir();

	foreach ( $map['thumbnails'] as $slug => $relative ) {
		$post = get_page_by_path( $slug, OBJECT, 'post' );
		if ( ! $post || has_post_thumbnail( $post->ID ) ) {
			continue;
		}
		$file = path_join( $uploads['basedir'], $relative );
		$size = file_exists( $file ) ? getimagesize( $file ) : false;
		if ( ! $size ) {
			continue;
		}
		$attachment_id = wp_insert_attachment(
			array(
				'post_mime_type' => $size['mime'],
				'post_title'     => $post->post_title,
				'post_status'    => 'inherit',
			),
			$file,
			$post->ID,
			true
		);
		if ( is_wp_error( $attachment_id ) ) {
			continue;
		}
		wp_update_attachment_metadata(
			$attachment_id,
			array( 'width' => $size[0], 'height' => $size[1], 'file' => $relative )
		);
		set_post_thumbnail( $post->ID, $attachment_id );
	}
}

/**
 * Attach the news images once, on the first page load after the theme is active.
 */
function tnt_pb_maybe_seed_featured_images() {
	if ( defined( 'TNT_PB_GENERATOR' ) || get_option( 'tnt_pb_images_seeded' ) ) {
		return;
	}
	tnt_pb_seed_featured_images();
	update_option( 'tnt_pb_images_seeded', 1 );
}
add_action( 'init', 'tnt_pb_maybe_seed_featured_images' );

/**
 * Menu items seeded into the primary menu on activation. Pages are linked by
 * slug, so they follow the page; the rest are root-relative URLs.
 *
 * @return array
 */
function tnt_pb_primary_menu_items() {
	return array(
		array( 'title' => 'Top', 'url' => '/' ),
		array( 'title' => 'About', 'page' => 'about-us', 'url' => '/about-us/' ),
		array( 'title' => 'News', 'page' => 'news', 'url' => '/news/' ),
		array( 'title' => 'Class', 'url' => '/#class' ),
		array( 'title' => 'Location', 'url' => '/#location' ),
		array( 'title' => 'FAQ', 'url' => '/#faq' ),
		array( 'title' => 'Contact', 'url' => '/#contact' ),
	);
}

/**
 * Create the "Primary menu" with the default items, unless a menu is already
 * assigned to the primary location. Edit it afterwards in Appearance > Menus.
 */
function tnt_pb_seed_primary_menu() {
	$locations = get_nav_menu_locations();
	if ( ! empty( $locations['primary'] ) ) {
		return;
	}

	$menu = wp_get_nav_menu_object( 'Primary menu' );
	if ( $menu ) {
		$menu_id = (int) $menu->term_id;
	} else {
		$menu_id = wp_create_nav_menu( 'Primary menu' );
		if ( is_wp_error( $menu_id ) ) {
			return;
		}
		foreach ( tnt_pb_primary_menu_items() as $item ) {
			$page = ! empty( $item['page'] ) ? get_page_by_path( $item['page'], OBJECT, 'page' ) : null;
			$link = $page
				? array( 'menu-item-type' => 'post_type', 'menu-item-object' => 'page', 'menu-item-object-id' => $page->ID )
				: array( 'menu-item-type' => 'custom', 'menu-item-url' => $item['url'] );
			wp_update_nav_menu_item(
				$menu_id,
				0,
				array_merge( array( 'menu-item-title' => $item['title'], 'menu-item-status' => 'publish' ), $link )
			);
		}
	}

	$locations['primary'] = $menu_id;
	set_theme_mod( 'nav_menu_locations', $locations );
}

/**
 * Seed the primary menu once on the first page load. Sites that activated the theme
 * before the menu was added get it without switching themes again.
 */
function tnt_pb_maybe_seed_primary_menu() {
	if ( defined( 'TNT_PB_GENERATOR' ) || get_option( 'tnt_pb_menu_seeded' ) ) {
		return;
	}
	tnt_pb_seed_primary_menu();
	update_option( 'tnt_pb_menu_seeded', 1 );
}
add_action( 'init', 'tnt_pb_maybe_seed_primary_menu' );

/**
 * Register the menu location that the templates print.
 */
function tnt_pb_register_menus() {
	register_nav_menus( array( 'primary' => __( 'Primary menu', 'tnt-private-boxing' ) ) );
}
add_action( 'after_setup_theme', 'tnt_pb_register_menus' );

/**
 * Print the primary menu inside one of the theme's three menu lists, in the markup
 * that list's CSS expects. Neve's lists wrap each link in div.wrap.
 *
 * @param string $list 'header' (desktop), 'mobile' (sidebar) or 'footer' (Elementor).
 */
function tnt_pb_primary_menu( $list = 'header' ) {
	$lists = array(
		'header' => array(
			'menu_id'    => 'nv-primary-navigation-desktop-main',
			'menu_class' => 'primary-menu-ul nav-ul menu-desktop',
			'before'     => '<div class="wrap">',
			'after'      => '</div>',
		),
		'mobile' => array(
			'menu_id'    => 'nv-primary-navigation-mobile-sidebar',
			'menu_class' => 'primary-menu-ul nav-ul menu-mobile',
			'before'     => '<div class="wrap">',
			'after'      => '</div>',
		),
		'footer' => array(
			'menu_id'    => 'menu-1-214be1b',
			'menu_class' => 'hfe-nav-menu',
		),
	);
	$style = isset( $lists[ $list ] ) ? $lists[ $list ] : $lists['header'];

	wp_nav_menu(
		array_merge(
			array(
				'theme_location' => 'primary',
				'container'      => false,
				'fallback_cb'    => false,
			),
			$style
		)
	);
}

/**
 * Add the classes the Elementor header styles expect to the primary menu's list items.
 */
function tnt_pb_primary_menu_item_class( $classes, $item, $args ) {
	if ( ! isset( $args->theme_location ) || 'primary' !== $args->theme_location ) {
		return $classes;
	}
	if ( 'menu-1-214be1b' === $args->menu_id ) {
		$classes[] = 'parent';
		$classes[] = 'hfe-creative-menu';
	} elseif ( in_array( 'current-menu-item', $classes, true ) ) {
		$classes[] = 'nv-active';
	}
	return $classes;
}
add_filter( 'nav_menu_css_class', 'tnt_pb_primary_menu_item_class', 10, 3 );

/**
 * Add the link class the Elementor header styles expect to the primary menu's links.
 */
function tnt_pb_primary_menu_link_class( $atts, $item, $args ) {
	if ( isset( $args->theme_location, $args->menu_id ) && 'primary' === $args->theme_location && 'menu-1-214be1b' === $args->menu_id ) {
		$atts['class'] = trim( ( isset( $atts['class'] ) ? $atts['class'] . ' ' : '' ) . 'hfe-menu-item' );
	}
	return $atts;
}
add_filter( 'nav_menu_link_attributes', 'tnt_pb_primary_menu_link_class', 10, 3 );
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


# Featured images are read from WordPress itself: a small script runs inside the WordPress
# container, loads WordPress with wp-load.php, and asks get_post_thumbnail_id() for each post.
WORDPRESS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wordpress")
COMPOSE_FILE = os.path.join(WORDPRESS_DIR, "docker-compose.yml")
THUMBS_MARKER = "TNT_THUMBS:"
# Paths and slugs read back from WordPress are checked before they are written into functions.php.
SAFE_UPLOAD_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
SAFE_SLUG = re.compile(r"[a-z0-9-]+")
THUMBS_PHP = (
    # TNT_PB_GENERATOR tells the theme's one-time seed hooks not to write to the database.
    "define( 'TNT_PB_GENERATOR', true ); require '/var/www/html/wp-load.php'; "
    "$out = array(); "
    "foreach ( get_posts( array( 'post_type' => 'post', 'post_status' => 'publish', "
    "'numberposts' => -1, 'orderby' => 'ID', 'order' => 'ASC' ) ) as $post ) { "
    "$id = get_post_thumbnail_id( $post ); "
    "if ( ! $id ) { continue; } "
    "$file = get_post_meta( $id, '_wp_attached_file', true ); "
    "if ( $file ) { $out[] = array( $post->post_name, $file ); } "
    "} "
    "echo '%s' . wp_json_encode( $out ) . PHP_EOL; " % THUMBS_MARKER
)


def compose_exec(service, args, user=None):
    """Run a command inside a service container of the WordPress compose project."""
    cmd = ["docker", "compose", "-f", COMPOSE_FILE, "exec", "-T"]
    if user:
        cmd += ["-u", user]
    try:
        return subprocess.run(cmd + [service, *args], capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise SystemExit("docker is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        raise SystemExit("docker compose did not answer within 120 seconds")


def wordpress_exec(args):
    """Run a command in the WordPress container as www-data and return the completed process."""
    res = compose_exec("wordpress", args, user="www-data")
    if res.returncode != 0:
        raise SystemExit(
            "could not reach the WordPress container (is the stack running? "
            "cd wordpress && docker compose up -d): " + res.stderr.strip()
        )
    return res


def news_thumbnails():
    """Return (post slug, image path under uploads/) for each published post with a featured image."""
    out = wordpress_exec(["php", "-r", THUMBS_PHP]).stdout
    for line in out.splitlines():
        if line.startswith(THUMBS_MARKER):
            try:
                rows = json.loads(line[len(THUMBS_MARKER):])
            except ValueError:
                raise SystemExit("WordPress returned an unreadable thumbnail list")
            thumbs = []
            for slug, rel in rows:
                if not (isinstance(slug, str) and isinstance(rel, str)):
                    continue
                if not SAFE_SLUG.fullmatch(slug):
                    print(f"  skipped featured image: unexpected slug {slug!r}")
                    continue
                if not SAFE_UPLOAD_PATH.fullmatch(rel) or ".." in rel.split("/"):
                    print(f"  skipped featured image for {slug}: unexpected path {rel!r}")
                    continue
                thumbs.append((slug, rel))
            return thumbs
    raise SystemExit("WordPress did not return the thumbnail list. Output was: " + out[-300:])


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
    # WordPress's default "Sample Page" (/sample-page/) uses the About us layout.
    jobs.append(("page-sample-page.php", "about-us/index.html", "about-us"))

    all_ok = True
    for template, rel_src, base_dir in jobs:
        src_path = os.path.join(html_dir, rel_src)
        src_text = read(src_path)
        out_text = build_template(src_path, rel_src, base_dir)
        check_src = replace_primary_nav(src_text)
        transform = TEMPLATE_TRANSFORMS.get(template)
        if transform:
            out_text = transform(out_text)
            check_src = transform(check_src)
        with open(os.path.join(theme_dir, template), "w", encoding="utf-8", newline="") as f:
            f.write(out_text)
        all_ok &= check_template(template, check_src, out_text)

    pages_php = []
    for slug, (_, title) in PAGE_TEMPLATES.items():
        pages_php.append(f"\t\t\tarray( 'slug' => {php_str(slug)}, 'title' => {php_str(title)} ),")
    posts_php = [
        f"\t\t\tarray( 'slug' => {php_str(slug)}, 'title' => {php_str(title)} ),"
        for slug, title in posts
    ]
    thumbs_php = [
        f"\t\t\t{php_str(slug)} => {php_str(rel)},"
        for slug, rel in news_thumbnails()
    ]
    functions = (
        FUNCTIONS_PHP.replace("__PAGES__", "\n".join(pages_php))
        .replace("__POSTS__", "\n".join(posts_php))
        .replace("__THUMBS__", "\n".join(thumbs_php))
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
