"""
Merges output/results.jsonl (LLM research) with output/composio_lookup.jsonl
(Composio catalog cross-check) into output/final_results.json -- the single
file generate_report.py reads to build the HTML page.
"""

from __future__ import annotations
import json
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "output"
RESULTS_FILE = OUT_DIR / "results.jsonl"
COMPOSIO_FILE = OUT_DIR / "composio_lookup.jsonl"
FINAL_FILE = OUT_DIR / "final_results.json"


def load_jsonl(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[row["id"]] = row
    return out


def main():
    research = load_jsonl(RESULTS_FILE)
    composio = load_jsonl(COMPOSIO_FILE)

    merged = []
    for app_id, r in sorted(research.items()):
        c = composio.get(app_id, {})
        if c.get("found") is True:
            r["composio_supported"] = True
            notes = f"Composio has a toolkit (slug: {c.get('slug', '?')})"
            if c.get("tool_count") is not None:
                notes += f", {c['tool_count']} tools"
            if c.get("is_composio_managed") is not None:
                notes += f", managed auth: {c['is_composio_managed']}"
            r["composio_notes"] = notes
        elif c.get("found") is False:
            r["composio_supported"] = False
            r["composio_notes"] = "No matching toolkit found in Composio's public catalog"
        elif c.get("found") is None:
            r["composio_supported"] = None
            r["composio_notes"] = f"Lookup failed (network/host error), not a real miss: {c.get('error', '')[:120]}"
        merged.append(r)

    FINAL_FILE.write_text(json.dumps(merged, indent=2))
    print(f"Merged {len(merged)} apps -> {FINAL_FILE}")
    missing = [a for a in research if a not in composio]
    if missing:
        print(f"Note: {len(missing)} apps have no composio_lookup row (run composio_lookup.py first)")


if __name__ == "__main__":
    main()
