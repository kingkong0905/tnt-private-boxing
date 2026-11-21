#!/usr/bin/env python3
"""Mirror the public pages and assets of a WordPress site into a static folder.

Usage:  python3 -I mirror.py <out_dir>

Stdlib only. Site-local links are rewritten to relative file paths so the copy
works from disk or from any static server. Brand text is NOT changed here;
rebrand.py runs afterwards.
"""
import os
import posixpath
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque

ORIGIN = "https://laboxinggym.net"
HOST = "laboxinggym.net"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
PAGE_SITEMAPS = ("page-sitemap.xml", "post-sitemap.xml", "category-sitemap.xml")
DELAY = 0.35  # seconds between requests, to be polite to the server

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ASSET_EXT = {".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg",
             ".ico", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".webm", ".pdf", ".json"}
TEXT_EXT = {".css", ".js", ".svg", ".json", ".xml", ".txt"}
BLOCKED_RE = re.compile(r"(^|/)(wp-json|wp-admin|wp-login\.php|wp-cron\.php|xmlrpc\.php|feed|comments|embed)(/|$)")

# Absolute site URLs, including JSON-escaped ones such as https:\/\/host\/path
ABS_RE = re.compile(
    r"(?:https?:)?(?:\\?/){2}(?:www\.)?" + re.escape(HOST) + r"(?![\w.-])"
    r"((?:\\/|[^\s\"'<>()\[\]{},;|^`\\])*)",
    re.I,
)
# Root-relative values in quoted HTML attributes, e.g. href="/about-us/"
ROOT_ATTR_RE = re.compile(
    r'''(\b(?:href|src|srcset|poster|action|data-src|data-srcset|data-lazy-src)\s*=\s*)(["'])(/(?!/)[^"'<>]*)\2''',
    re.I,
)
ROOT_TOKEN_RE = re.compile(r'''/(?!/)[^\s,"'<>()]*''')
CSS_URL_RE = re.compile(r'''url\(\s*(["']?)([^"')\s]+)\1\s*\)''', re.I)
IMPORT_RE = re.compile(r'''@import\s+(?:url\()?\s*["']([^"']+)["']''', re.I)


def http_get(url):
    """Return (status, content_type, body). Retries transient failures."""
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, r.headers.get_content_type(), r.read()
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (404, 410):
                return e.code, "", b""
        except Exception as e:  # network hiccup, timeout, etc.
            last = repr(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"gave up on {url}: {last}")


def parse_local(raw):
    """Split a site-local URL fragment into (path, query, fragment)."""
    s = raw.replace("\\/", "/").replace("&amp;", "&")
    s, _, frag = s.partition("#")
    path, _, query = s.partition("?")
    if not path.startswith("/"):
        path = "/" + path
    return path, query, frag


def classify(path, query):
    """Return ('page', path) / ('asset', path) for files we mirror, else None."""
    if BLOCKED_RE.search(path) or ".." in path.split("/"):
        return None
    under_wp = path.startswith(("/wp-content/", "/wp-includes/"))
    if path.endswith("/"):
        return None if under_wp or query else ("page", path)
    ext = posixpath.splitext(path)[1].lower()
    if ext == ".php":
        return None
    if under_wp or ext in ASSET_EXT:
        return ("asset", path)
    if query:  # dynamic pages (?s=, ?p=, ?paged=) are skipped
        return None
    if ext in ("", ".html", ".htm"):
        return ("page", path if ext else path + "/")
    return None


def page_target(path):
    if path == "/":
        return "index.html"
    if path.endswith((".html", ".htm")):
        return path.lstrip("/")
    return path.strip("/") + "/index.html"


def asset_target(path):
    return path.lstrip("/")


def decode(body):
    try:
        return body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return body.decode("latin-1"), "latin-1"


class Mirror:
    def __init__(self, out):
        self.out = out
        self.queue = deque()
        self.queued = set()
        self.texts = {}     # target -> (text, encoding)
        self.ok = set()     # targets successfully saved
        self.failed = []    # (url, reason)

    # ----- discovery -------------------------------------------------------
    def enqueue(self, kind, path):
        key = (kind, path)
        if key not in self.queued:
            self.queued.add(key)
            self.queue.append(key)

    def consider(self, path, query):
        c = classify(path, query)
        if c:
            self.enqueue(*c)

    def consider_ref(self, ref, base_path):
        if ref.startswith(("data:", "#", "javascript:", "mailto:", "tel:", "http:", "https:", "//")):
            return
        if ref.startswith("/"):
            self.consider(*parse_local(ref)[:2])
            return
        clean = ref.split("#")[0].split("?")[0]
        joined = posixpath.normpath(posixpath.join(posixpath.dirname(base_path), clean))
        self.consider(joined, "")

    def discover(self, text, base_path, is_css=False):
        for m in ABS_RE.finditer(text):
            self.consider(*parse_local(m.group(1))[:2])
        if is_css:
            for m in CSS_URL_RE.finditer(text):
                self.consider_ref(m.group(2), base_path)
            for m in IMPORT_RE.finditer(text):
                self.consider_ref(m.group(1), base_path)
            return
        for m in ROOT_ATTR_RE.finditer(text):
            for tok in ROOT_TOKEN_RE.findall(m.group(3)):
                self.consider(*parse_local(tok)[:2])
        for m in CSS_URL_RE.finditer(text):  # inline style="url(...)"
            if m.group(2).startswith("/"):
                self.consider(*parse_local(m.group(2))[:2])

    # ----- crawling --------------------------------------------------------
    def crawl(self):
        while self.queue:
            kind, path = self.queue.popleft()
            url = ORIGIN + path
            try:
                status, ctype, body = http_get(url)
            except RuntimeError as e:
                self.failed.append((url, str(e)))
                time.sleep(DELAY)
                continue
            time.sleep(DELAY)
            if status != 200:
                self.failed.append((url, f"status {status}"))
                continue

            target = page_target(path) if kind == "page" else asset_target(path)
            ext = posixpath.splitext(target)[1].lower()
            is_text = kind == "page" or ext in TEXT_EXT or ctype.startswith("text/")
            if is_text:
                text, enc = decode(body)
                self.texts[target] = (text, enc)
                self.ok.add(target)
                self.discover(text, path, is_css=(ext == ".css"))
                print(f"[{kind}] {path}", file=sys.stderr)
            else:
                self.save_bytes(target, body)
                self.ok.add(target)
                print(f"[asset] {path} ({len(body)} bytes)", file=sys.stderr)

    # ----- output ----------------------------------------------------------
    def save_bytes(self, target, data):
        dest = os.path.join(self.out, target)
        os.makedirs(os.path.dirname(dest) or self.out, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)

    def local_ref(self, from_target, path, query):
        c = classify(path, query)
        if not c:
            return None
        kind, p = c
        target = page_target(p) if kind == "page" else asset_target(p)
        if target not in self.ok:
            return None
        return posixpath.relpath(target, posixpath.dirname(from_target) or ".")

    def rewrite(self, text, target):
        def abs_sub(m):
            path, query, frag = parse_local(m.group(1))
            local = self.local_ref(target, path, query)
            if local is None:
                return m.group(0)
            if "\\/" in m.group(0):  # keep JSON-style escaping
                local = local.replace("/", "\\/")
            return local + ("#" + frag if frag else "")

        def root_attr_sub(m):
            def tok(t):
                path, query, frag = parse_local(t.group(0))
                local = self.local_ref(target, path, query)
                if local is None:
                    return t.group(0)
                return local + ("#" + frag if frag else "")
            return m.group(1) + m.group(2) + ROOT_TOKEN_RE.sub(tok, m.group(3)) + m.group(2)

        def css_sub(m):
            ref = m.group(2)
            if not ref.startswith("/") or ref.startswith("//"):
                return m.group(0)
            path, query, frag = parse_local(ref)
            local = self.local_ref(target, path, query)
            if local is None:
                return m.group(0)
            q = m.group(1)
            return "url(" + q + local + ("#" + frag if frag else "") + q + ")"

        text = ABS_RE.sub(abs_sub, text)
        text = ROOT_ATTR_RE.sub(root_attr_sub, text)
        text = CSS_URL_RE.sub(css_sub, text)
        return text

    def write_texts(self):
        for target, (text, enc) in self.texts.items():
            new = self.rewrite(text, target)
            dest = os.path.join(self.out, target)
            os.makedirs(os.path.dirname(dest) or self.out, exist_ok=True)
            with open(dest, "w", encoding=enc, newline="") as f:
                f.write(new)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    m = Mirror(out)

    # Seeds: the homepage plus every page/post/category in the site's sitemaps.
    m.enqueue("page", "/")
    _, _, idx = http_get(ORIGIN + "/sitemap.xml")
    for loc in ET.fromstring(idx).iter(SITEMAP_NS + "loc"):
        href = loc.text.strip()
        if posixpath.basename(urllib.parse.urlparse(href).path) not in PAGE_SITEMAPS:
            continue
        _, _, sub = http_get(href)
        for u in ET.fromstring(sub).iter(SITEMAP_NS + "loc"):
            path = urllib.parse.urlparse(u.text.strip()).path or "/"
            c = classify(path, "")
            if c:
                m.enqueue(*c)
    print(f"queued {len(m.queue)} seed items", file=sys.stderr)

    m.crawl()
    m.write_texts()

    pages = sorted(t for t in m.ok if t.endswith(".html"))
    assets = sorted(t for t in m.ok if not t.endswith(".html"))
    print(f"\nSAVED pages={len(pages)} assets={len(assets)} failed={len(m.failed)}")
    for p in pages:
        print("  page:", p)
    for url, why in m.failed:
        print("  FAILED:", url, "-", why)


if __name__ == "__main__":
    main()
