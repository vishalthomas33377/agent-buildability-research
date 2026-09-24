"""
Composio cross-check.

For each app, checks whether Composio already has a toolkit for it. This is
a free, high-signal secondary source: if Composio already ships a working
toolkit for an app, that's strong evidence the app is buildable (someone
already solved the auth/API problem), and their toolkit metadata tells us
tool count and whether it's Composio-managed auth.

Two lookup strategies, tried in order, because the exact slug Composio uses
doesn't always match the app's display name:
  1. Direct slug guess (e.g. "HubSpot" -> "hubspot") against the public
     toolkit markdown endpoint (composio.dev/toolkits/{slug}.md) -- no
     API key required for this, it's a public page.
  2. If that 404s, use the authenticated SDK search
     (tools.get_raw_composio_tools(search=app_name)) to find the real slug,
     which DOES need COMPOSIO_API_KEY set.

Writes composio_lookup.jsonl, one row per app, which merge_results.py
then folds into the final results (composio_supported / composio_notes).

Note: Composio's SDK surface has changed across versions; if
`from composio import Composio` or the methods below don't match what's
installed, check https://docs.composio.dev/python/python-sdk-reference
for the current method names and adjust load_toolkit_via_sdk() -- the
public markdown fallback (strategy 1) will still work either way.
"""

from __future__ import annotations
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_DIR = Path(__file__).parent.parent / "output"
APPS_FILE = DATA_DIR / "apps.json"
OUT_FILE = OUT_DIR / "composio_lookup.jsonl"


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"\(.*?\)", "", s)          # drop "(open-source CRM)" etc.
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def try_public_markdown(slug: str) -> dict | None:
    url = f"https://composio.dev/toolkits/{slug}.md"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 404:
            return None  # genuinely not in the catalog under this slug
        if r.status_code != 200:
            # Network/allowlist/server error -- NOT the same as "not found".
            # Surface it loudly instead of silently reporting a false negative.
            raise RuntimeError(f"HTTP {r.status_code} fetching {url}: {r.text[:200]}")
        text = r.text
        m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        meta = json.loads(m.group(1)) if m else {}
        tools_match = re.search(r"Tools:\s*(\d+)", text)
        return {
            "found": True,
            "slug": meta.get("slug", slug),
            "url": meta.get("url", url),
            "is_composio_managed": meta.get("is_composio_managed"),
            "tool_count": int(tools_match.group(1)) if tools_match else None,
        }
    except requests.RequestException as e:
        raise RuntimeError(f"Network error fetching {url}: {e}")


def try_sdk_search(app_name: str, api_key: str) -> dict | None:
    try:
        from composio import Composio
    except ImportError:
        return None
    try:
        client = Composio(api_key=api_key)
        results = client.tools.get_raw_composio_tools(search=app_name, limit=5)
        if not results:
            return None
        first = results[0]
        toolkit_slug = getattr(first, "toolkit_slug", None) or (
            first.get("toolkit", {}).get("slug") if isinstance(first, dict) else None
        )
        return {"found": True, "slug": toolkit_slug, "via": "sdk_search"}
    except Exception as e:
        return {"found": False, "error": str(e)}


def lookup_one(app: dict, api_key: str | None) -> dict:
    slug_guess = slugify(app["app"])
    try:
        result = try_public_markdown(slug_guess)
    except RuntimeError as e:
        # Network/host problem, not a real "not found" -- don't record a false negative.
        return {"id": app["id"], "app": app["app"], "found": None, "method": "error",
                "slug_tried": slug_guess, "error": str(e)}

    if result:
        result.update({"id": app["id"], "app": app["app"], "method": "public_markdown", "slug_tried": slug_guess})
        return result

    if api_key:
        sdk_result = try_sdk_search(app["app"], api_key)
        if sdk_result and sdk_result.get("found"):
            sdk_result.update({"id": app["id"], "app": app["app"], "method": "sdk_search"})
            return sdk_result

    return {"id": app["id"], "app": app["app"], "found": False, "method": "none", "slug_tried": slug_guess}


def main():
    api_key = os.environ.get("COMPOSIO_API_KEY")
    if not api_key:
        print("WARNING: COMPOSIO_API_KEY not set. Falling back to public markdown lookup only "
              "(works for exact slug guesses; will miss apps with non-obvious slugs).", file=sys.stderr)

    apps = json.loads(APPS_FILE.read_text())
    OUT_DIR.mkdir(exist_ok=True)

    with open(OUT_FILE, "w") as f:
        for app in apps:
            result = lookup_one(app, api_key)
            f.write(json.dumps(result) + "\n")
            f.flush()
            status = "FOUND" if result.get("found") else ("ERROR: " + result.get("error", "")[:60] if result.get("found") is None else "not found")
            print(f"[{app['id']:3}] {app['app']:30} {status} (tried slug: {result.get('slug_tried', result.get('slug'))})")
            time.sleep(0.3)  # be polite to the public endpoint


if __name__ == "__main__":
    main()
