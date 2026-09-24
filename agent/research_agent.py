"""
Free research agent: DDGS web search + Groq LLM.

This replaces Gemini Search Grounding so the 100-app run does not depend on a
paid Google Search-grounding quota. DDGS performs ordinary web searches and
returns the source title, URL and snippet; Groq's free developer tier then
extracts the required structured record in one LLM call per app.

The important evidence rule is preserved: evidence_urls can only come from
URLs returned by the search step, never invented by the model.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from ddgs import DDGS
from groq import Groq
from dotenv import load_dotenv
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent))
from schema import AppResearchResult

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_DIR = Path(__file__).parent.parent / "output"
APPS_FILE = DATA_DIR / "apps.json"
RESULTS_FILE = OUT_DIR / "results.jsonl"
FAILURES_FILE = OUT_DIR / "failures.jsonl"

load_dotenv(Path(__file__).parent.parent / ".env")
MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

SYSTEM = """You are a careful SaaS/API research analyst. You are given web-search results for one app.
Use ONLY the supplied search evidence. Never invent a URL, API capability, auth method, pricing gate,
or MCP server. Prefer first-party developer docs, API reference, pricing, and official MCP pages over
blogs or aggregators. If evidence conflicts or is missing, use Unknown and explain why.

Buildability definitions:
- Buildable today: self-serve auth + documented public API and no major access blocker.
- Buildable with friction: technically possible but a meaningful hurdle exists (paid plan, manual review,
  limited scopes, etc.).
- Blocked: no usable public API or fully partnership/contact-sales gated with no self-serve path.
- Unknown: evidence is insufficient.

Return ONLY valid JSON. Keep notes concise. evidence_urls MUST be copied verbatim from the supplied
search results; never create URLs from memory.
"""


def load_apps():
    return json.loads(APPS_FILE.read_text(encoding="utf-8"))


def load_done_ids():
    if not RESULTS_FILE.exists():
        return set()
    done = set()
    for line in RESULTS_FILE.read_text(encoding="utf-8").splitlines():
        try:
            if line.strip():
                done.add(json.loads(line)["id"])
        except Exception:
            pass
    return done


def domain_from_hint(hint: str) -> str | None:
    h = (hint or "").strip()
    if not h or " " in h and "." not in h:
        return None
    if not re.match(r"^https?://", h):
        h = "https://" + h
    try:
        host = urlparse(h).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


def search_app(app: dict, max_results: int = 8) -> list[dict]:
    name = app["app"]
    hint = app.get("hint", "")
    domain = domain_from_hint(hint)
    queries = []
    if domain:
        queries.append(f'site:{domain} {name} API authentication developer docs')
        queries.append(f'site:{domain} {name} pricing API access MCP')
    else:
        queries.append(f'"{name}" API authentication developer docs pricing MCP')
        queries.append(f'"{name}" developer API access OAuth API key MCP')

    # Keep this to two searches/app to avoid search-engine throttling.
    found = []
    seen = set()
    with DDGS(timeout=12) as ddgs:
        for q in queries:
            try:
                rows = ddgs.text(q, region="us-en", safesearch="moderate", max_results=max_results, backend="auto")
            except Exception as exc:
                rows = [{"title": "SEARCH_ERROR", "href": "", "body": str(exc)}]
            for r in rows:
                url = (r.get("href") or "").strip()
                if url and url not in seen:
                    seen.add(url)
                    found.append({
                        "title": (r.get("title") or "")[:220],
                        "url": url,
                        "snippet": (r.get("body") or "")[:900],
                    })
    return found[:14]


def build_prompt(app: dict, sources: list[dict]) -> str:
    source_text = "\n\n".join(
        f"SOURCE {i}:\nTITLE: {s['title']}\nURL: {s['url']}\nSNIPPET: {s['snippet']}"
        for i, s in enumerate(sources, 1)
    ) or "NO SEARCH RESULTS"
    return f"""Research target:
App: {app['app']}
Category: {app['category']}
Hint: {app.get('hint','')}

SEARCH EVIDENCE:
{source_text}

Return one JSON object with exactly these keys:
- id (int), app (string), category (string)
- one_liner (string)
- auth_methods (array; values only: OAuth2, API key, Basic, Token, OAuth1, None / public, Other, Unknown)
- auth_notes (string)
- self_serve (one of: Self-serve (free), Self-serve (paid plan required), Gated (approval/allowlist), Gated (partnership/contact-sales), Unknown)
- self_serve_notes (string)
- has_public_api (bool)
- api_style (string)
- api_breadth (one of: Broad, Moderate, Narrow, None, Unknown)
- existing_mcp (bool)
- mcp_notes (string)
- composio_supported (null)
- composio_notes (string)
- verdict (one of: Buildable today, Buildable with friction, Blocked, Unknown)
- blocker (string)
- evidence_urls (array; ONLY exact URLs from SEARCH EVIDENCE)
- confidence (High, Medium, Low)
- agent_notes (string)

If the evidence does not establish a field, use Unknown/false/empty as appropriate and say so in agent_notes.
Do not infer that an app has an API merely because it has a website. Do not infer MCP support from generic AI claims.
"""


def research_one(client: Groq, app: dict, max_retries: int = 3) -> dict:
    last_err = None
    sources = search_app(app)
    source_urls = {s["url"] for s in sources if s.get("url")}
    prompt = build_prompt(app, sources)
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_completion_tokens=1400,
                reasoning_effort="low" if "gpt-oss" in MODEL else None,
                reasoning_format="hidden" if "gpt-oss" in MODEL else None,
            )
            text = (resp.choices[0].message.content or "").strip()
            data = json.loads(text)
            data["id"] = app["id"]
            data["app"] = app["app"]
            data["category"] = app["category"]
            data["evidence_urls"] = [u for u in data.get("evidence_urls", []) if u in source_urls]
            if not data["evidence_urls"] and sources:
                # Do not invent evidence; preserve a transparent low-confidence record.
                data["agent_notes"] = (data.get("agent_notes", "") + " No cited URL from the model survived evidence validation.").strip()
                data["confidence"] = "Low"
            result = AppResearchResult(**data)
            return result.model_dump()
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(f"Failed after {max_retries} attempts: {last_err}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="Start a new run by clearing prior research output")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", type=int, nargs="*", default=None)
    parser.add_argument("--sleep", type=float, default=2.0)
    args = parser.parse_args()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("ERROR: set GROQ_API_KEY in your PowerShell session or .env", file=sys.stderr)
        sys.exit(1)

    client = Groq(api_key=api_key)
    OUT_DIR.mkdir(exist_ok=True)
    if args.fresh:
        RESULTS_FILE.write_text("", encoding="utf-8")
        FAILURES_FILE.write_text("", encoding="utf-8")
    apps = load_apps()
    if args.only:
        apps = [a for a in apps if a["id"] in args.only]
    if args.limit:
        apps = apps[:args.limit]
    done_ids = load_done_ids() if args.resume else set()

    with open(RESULTS_FILE, "a", encoding="utf-8") as results_f, open(FAILURES_FILE, "a", encoding="utf-8") as fail_f:
        for app in apps:
            if app["id"] in done_ids:
                print(f"[{app['id']:3}] {app['app']:30} SKIP (already done)")
                continue
            try:
                print(f"[{app['id']:3}] {app['app']:30} researching...")
                result = research_one(client, app)
                results_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                results_f.flush()
                print(f"[{app['id']:3}] {app['app']:30} OK   verdict={result['verdict']}")
            except Exception as exc:
                fail_f.write(json.dumps({"id": app["id"], "app": app["app"], "error": str(exc)}) + "\n")
                fail_f.flush()
                print(f"[{app['id']:3}] {app['app']:30} FAIL {exc}")
            time.sleep(max(args.sleep, 0))


if __name__ == "__main__":
    main()
