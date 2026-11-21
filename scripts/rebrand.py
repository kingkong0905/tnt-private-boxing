#!/usr/bin/env python3
"""Rename the brand "LA Boxing Gym" -> "TNT Private Boxing" in a mirrored site.

Usage:  python3 -I rebrand.py <site_dir>

Edits text files in place. Real identifiers of the original business (social
handles, the Gmail address, the laboxinggym.net domain) are replaced with
neutral placeholders instead of being renamed, so nothing points at the
original gym's accounts.
"""
import os
import re
import sys

NEW = "TNT Private Boxing"
NEW_SLUG = "tntprivateboxing"
PLACEHOLDER_EMAIL = "hello@example.com"
TEXT_EXT = {".html", ".htm", ".css", ".js", ".json", ".xml", ".svg", ".txt"}

# Ordered: longer / more specific rules first.
PLAIN_RULES = [
    ("https://www.facebook.com/LABOXINGGYM", "#"),
    ("https://www.instagram.com/laboxing_gym/", "#"),
    ("laboxinggym@gmail.com", PLACEHOLDER_EMAIL),
    ("laboxinggymLT", NEW),
    ("laboxinggymlt", NEW_SLUG),
    ("#laboxinggym", "#" + NEW_SLUG),
    ("LABOXINGGYM", NEW_SLUG.upper()),
]

REGEX_RULES = [
    # Remove the scheme + domain from leftover absolute links (WordPress
    # endpoints like /wp-json/ and /wp-admin/admin-ajax.php become root-relative).
    (re.compile(r"https?:(?:\\?/){2}(?:www\.)?laboxinggym\.net", re.I), ""),
    (re.compile(r"https?%3A%2F%2Flaboxinggym\.net", re.I), ""),
    # Brand name, with case preserved and duplicate names collapsed.
    (re.compile(r"\bLA[\s_-]+BOXING[\s_-]+GYM\b(?:\s+LA[\s_-]+BOXING[\s_-]+GYM\b)*", re.I), "BRAND"),
    (re.compile(r"\bLA[\s_-]+BOXING\b", re.I), "BRAND"),
    # Any remaining domain or handle mentions.
    (re.compile(r"laboxinggym\.net", re.I), ""),
    (re.compile(r"laboxinggym", re.I), NEW_SLUG),
]

# WordPress discovery <link> tags (RSS, oEmbed, RSD, REST) point at the old site.
DISCOVERY_LINK_RE = re.compile(r"<link\b[^>]*(?:wp-json|xmlrpc\.php|/feed/|comments/feed)[^>]*>[ \t]*\n?")


def brand_sub(m):
    return NEW.upper() if m.group(0).isupper() else NEW


def rebrand_text(text):
    for old, new in PLAIN_RULES:
        text = text.replace(old, new)
    for pattern, repl in REGEX_RULES:
        if repl == "BRAND":
            text = pattern.sub(brand_sub, text)
        else:
            text = pattern.sub(repl, text)
    text = DISCOVERY_LINK_RE.sub("", text)
    return text


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = os.path.abspath(sys.argv[1])

    changed = 0
    for dirpath, _, files in os.walk(root):
        for name in files:
            if os.path.splitext(name)[1].lower() not in TEXT_EXT:
                continue
            path = os.path.join(dirpath, name)
            with open(path, "rb") as f:
                raw = f.read()
            try:
                text, enc = raw.decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                text, enc = raw.decode("latin-1"), "latin-1"
            new = rebrand_text(text)
            if new != text:
                with open(path, "w", encoding=enc, newline="") as f:
                    f.write(new)
                changed += 1

    # Rename the author archive folder that carried the old handle.
    old_author = os.path.join(root, "author", "laboxinggymlt")
    new_author = os.path.join(root, "author", NEW_SLUG)
    if os.path.isdir(old_author) and not os.path.exists(new_author):
        os.rename(old_author, new_author)

    print(f"files changed: {changed}")


if __name__ == "__main__":
    main()
