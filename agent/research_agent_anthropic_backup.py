"""
Research agent.

For each app in data/apps.json, calls Claude (with the server-side web_search
tool switched on) and asks it to research the app's auth model, access
gating, API surface, and buildability, returning strict JSON matching
schema.AppResearchResult.

Design notes (things we'd explain in an interview):
- We use Anthropic's built-in `web_search` tool rather than scraping
  ourselves. It's server-executed: Claude decides what to search, issues
  the searches, reads results, and we get the final answer back in one
  API call. This is the "agent" part -- the model is doing the research
  loop, not just summarizing text we hand it.
- Output is forced to strict JSON via prompt + a final parse/validate step
  against schema.AppResearchResult. Anything that fails validation is
  logged to failures.jsonl instead of silently dropped or guessed.
- Results are written incrementally (append to results.jsonl) so a crash
  or rate limit partway through doesn't lose completed work, and re-runs
  can skip apps already done (--resume).
- This is intentionally a first pass. Pass 2 (after verify.py finds
  systematic errors) tightens the prompt below and re-runs only the
  apps that failed verification -- see README for how that loop works.
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

from anthropic import Anthropic
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent))
from schema import AppResearchResult

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_DIR = Path(__file__).parent.parent / "output"
APPS_FILE = DATA_DIR / "apps.json"
RESULTS_FILE = OUT_DIR / "results.jsonl"
FAILURES_FILE = OUT_DIR / "failures.jsonl"

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a product-ops researcher. Given the name of a software product, \
research it using web search and determine facts needed to evaluate whether it could be \
wrapped as a tool/toolkit for an AI agent to call (e.g. via an MCP server).

Research and confirm, using web search on the product's OWN developer/API documentation \
wherever possible (not third-party blogs, unless docs are unavailable):

1. What the product does, in one sentence.
2. Authentication method(s) supported by its API: OAuth2, API key, Basic, Token, OAuth1, \
   None/public, or Other. Note specifics (e.g. "OAuth2 with PKCE", "static API key from settings").
3. Whether a developer can self-serve API access for free / on a trial (create an account and \
   get credentials themselves), vs. whether it requires a paid plan tier, admin approval, \
   allowlisting, or a partnership / contact-sales process to get API credentials at all.
4. Whether there is a documented public REST or GraphQL API, how broad it is (broad = covers \
   most core objects/actions, moderate = covers some, narrow = very limited, none = no API), \
   and whether an official or well-known MCP server already exists for it.
5. A verdict: "Buildable today" (self-serve auth + documented API, no major blocker), \
   "Buildable with friction" (possible but has a real hurdle, e.g. paid plan required, manual \
   app review, limited scopes), or "Blocked" (no public API, or fully partnership-gated with \
   no self-serve path at all). State the main blocker if not "Buildable today".
6. Evidence: real URLs (docs pages, pricing pages, API reference) that support your answers. \
   Only include URLs you actually found via search -- never invent a URL.

Be honest about uncertainty. If you couldn't find something after searching, say so in \
agent_notes and mark confidence "Low" rather than guessing.

Respond with ONLY a single JSON object (no markdown fences, no commentary) with exactly these \
keys: id, app, category, one_liner, auth_methods (array), auth_notes, self_serve, \
self_serve_notes, has_public_api (bool), api_style, api_breadth, existing_mcp (bool), \
mcp_notes, verdict, blocker, evidence_urls (array), confidence, agent_notes.
"""


def load_apps() -> list[dict]:
    return json.loads(APPS_FILE.read_text())


def load_done_ids() -> set[int]:
    if not RESULTS_FILE.exists():
        return set()
    done = set()
    for line in RESULTS_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            done.add(json.loads(line)["id"])
        except Exception:
            pass
    return done


def research_one(client: Anthropic, app: dict, max_retries: int = 3) -> dict:
    user_msg = (
        f"Research this product: \"{app['app']}\" (category: {app['category']}, "
        f"hint: {app['hint']}). id={app['id']}, category=\"{app['category']}\", "
        f"app=\"{app['app']}\"."
    )

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
                messages=[{"role": "user", "content": user_msg}],
            )
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            ).strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(text)
            # Ensure id/app/category are exactly what we passed in, not whatever the model echoed
            data["id"] = app["id"]
            data["app"] = app["app"]
            data["category"] = app["category"]
            result = AppResearchResult(**data)
            return result.model_dump()
        except (json.JSONDecodeError, ValidationError, Exception) as e:
            last_err = e
            time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Failed after {max_retries} attempts: {last_err}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="Skip apps already in results.jsonl")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N apps (for testing)")
    parser.add_argument("--only", type=int, nargs="*", default=None, help="Only process these app ids")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: set ANTHROPIC_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)

    client = Anthropic(api_key=api_key)
    OUT_DIR.mkdir(exist_ok=True)

    apps = load_apps()
    if args.only:
        apps = [a for a in apps if a["id"] in args.only]
    if args.limit:
        apps = apps[: args.limit]

    done_ids = load_done_ids() if args.resume else set()

    with open(RESULTS_FILE, "a") as results_f, open(FAILURES_FILE, "a") as fail_f:
        for app in apps:
            if app["id"] in done_ids:
                print(f"[{app['id']:3}] {app['app']:30} SKIP (already done)")
                continue
            try:
                result = research_one(client, app)
                results_f.write(json.dumps(result) + "\n")
                results_f.flush()
                print(f"[{app['id']:3}] {app['app']:30} OK   verdict={result['verdict']}")
            except Exception as e:
                fail_f.write(json.dumps({"id": app["id"], "app": app["app"], "error": str(e)}) + "\n")
                fail_f.flush()
                print(f"[{app['id']:3}] {app['app']:30} FAIL {e}")


if __name__ == "__main__":
    main()
