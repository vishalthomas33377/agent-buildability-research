"""Smoke test: dependencies, DDGS search, and one Groq JSON call."""
from __future__ import annotations
import json, os
from pathlib import Path
from dotenv import load_dotenv
from ddgs import DDGS
from groq import Groq

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

print("1/3 Python dependencies: OK")
print("2/3 Testing web search...")
rows = DDGS(timeout=12).text("Salesforce API authentication developer docs", max_results=2)
if not rows:
    raise SystemExit("Web search returned no results. Try again or run with a different network.")
print(f"    Search OK ({len(rows)} results)")

key = os.environ.get("GROQ_API_KEY")
if not key:
    raise SystemExit("GROQ_API_KEY is missing. Put it in .env and rerun this test.")
print("3/3 Testing Groq...")
client = Groq(api_key=key)
r = client.chat.completions.create(
    model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
    messages=[{"role":"user", "content":"Return exactly this JSON: {\"ok\": true}"}],
    response_format={"type":"json_object"},
    temperature=0,
    max_completion_tokens=100,
    reasoning_effort="low",
    reasoning_format="hidden",
)
obj = json.loads(r.choices[0].message.content)
if obj.get("ok") is not True:
    raise SystemExit(f"Unexpected Groq response: {obj}")
print("    Groq OK")
print("\nSETUP OK — you can run: python agent\\research_agent.py --fresh --limit 1")
