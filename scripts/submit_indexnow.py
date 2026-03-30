#!/usr/bin/env python3
"""Submit site URLs to IndexNow.

Usage:
  python scripts/submit_indexnow.py --base-url https://g3industries.io
  python scripts/submit_indexnow.py --base-url https://g3industries.io --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

DEFAULT_ENDPOINT = "https://api.indexnow.org/indexnow"
DEFAULT_STATIC_PATHS = ["/", "/products", "/security", "/grants", "/about", "/blog"]
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        raise ValueError("Base URL cannot be empty.")
    if not value.startswith("http://") and not value.startswith("https://"):
        value = f"https://{value}"
    parsed = urllib_parse.urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid base URL: {value}")
    return f"{parsed.scheme}://{parsed.netloc}"


def build_default_urls(base_url: str) -> list[str]:
    # Lazy import keeps the script usable even if app imports are heavy.
    from app import BLOG_POSTS

    urls = [f"{base_url}{path}" for path in DEFAULT_STATIC_PATHS]
    for post in BLOG_POSTS:
        slug = str(post.get("slug", "")).strip()
        if slug:
            urls.append(f"{base_url}/blog/{slug}")
    # Stable ordering helps diffing dry-run output.
    return sorted(set(urls))


def load_urls_from_file(path: str) -> list[str]:
    urls: list[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            candidate = line.strip()
            if candidate and not candidate.startswith("#"):
                urls.append(candidate)
    return sorted(set(urls))


def submit_indexnow(
    endpoint: str,
    host: str,
    key: str,
    key_location: str,
    urls: list[str],
    timeout_seconds: float,
) -> tuple[bool, str]:
    payload = {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "g3-indexnow/1.0"},
    )

    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            if 200 <= response.status < 300:
                return True, body or f"IndexNow accepted payload ({response.status})."
            return False, f"IndexNow returned HTTP {response.status}: {body}"
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, f"IndexNow HTTP {exc.code}: {body}"
    except Exception as exc:  # pylint: disable=broad-except
        return False, f"IndexNow request failed: {exc}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit URLs to IndexNow")
    parser.add_argument("--base-url", default="https://g3industries.io", help="Canonical site URL")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="IndexNow endpoint")
    parser.add_argument(
        "--key",
        default=os.environ.get("INDEXNOW_KEY", "").strip(),
        help="IndexNow key (or use INDEXNOW_KEY env var)",
    )
    parser.add_argument(
        "--key-location",
        default="",
        help="Public URL that serves your key text. Defaults to <base-url>/indexnow-key.txt",
    )
    parser.add_argument(
        "--urls-file",
        default="",
        help="Optional newline-delimited URL file (if omitted, script builds URLs from app.py)",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout seconds")
    parser.add_argument("--dry-run", action="store_true", help="Print payload and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        base_url = normalize_base_url(args.base_url)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    key = args.key.strip()
    if not key:
        print("error: missing IndexNow key. Pass --key or set INDEXNOW_KEY.", file=sys.stderr)
        return 2

    key_location = args.key_location.strip() or f"{base_url}/indexnow-key.txt"
    host = urllib_parse.urlparse(base_url).netloc

    if args.urls_file:
        urls = load_urls_from_file(args.urls_file)
    else:
        urls = build_default_urls(base_url)

    if not urls:
        print("error: no URLs found to submit.", file=sys.stderr)
        return 2

    payload_preview = {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlCount": len(urls),
        "firstUrls": urls[:5],
    }

    if args.dry_run:
        print(json.dumps(payload_preview, indent=2))
        return 0

    ok, message = submit_indexnow(
        endpoint=args.endpoint,
        host=host,
        key=key,
        key_location=key_location,
        urls=urls,
        timeout_seconds=args.timeout,
    )

    if ok:
        print(f"submitted {len(urls)} URL(s) to IndexNow")
        if message:
            print(message)
        return 0

    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
