"""
Human verification loop.

Usage:
  python verify.py --sample 20              # pick a fresh random sample to review
  python verify.py --review                 # walk through the sample interactively
  python verify.py --report                 # print accuracy summary from verification.jsonl

Workflow this supports (this is the "pass 1 -> pass 2" loop the assignment
asks for):
  1. `--sample 20` picks 20 apps at random (or use --ids to pick specific
     ones you want to double check, e.g. ones the agent marked Low
     confidence).
  2. `--review` shows you, one at a time, what the agent said for
     auth_methods / self_serve / verdict + its evidence URLs. You open the
     evidence URL (or search yourself), and type in whether the agent was
     right, and what the correct answer is if not.
  3. `--report` tallies accuracy, broken down by field, and prints out the
     specific misses -- this is what goes on the case study page and is
     what tells you what to fix in the agent's prompt before pass 2.
  4. Fix research_agent.py's SYSTEM_PROMPT based on the pattern of misses,
     then re-run just the wrong ones:
       python research_agent.py --only 7 23 41 68   (the ids that were wrong)
     Re-run --sample/--review/--report on a NEW random sample after that to
     show pass 2 accuracy without reviewing the same apps you already fixed.
"""

from __future__ import annotations
import argparse
import json
import random
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "output"
FINAL_FILE = OUT_DIR / "final_results.json"
SAMPLE_FILE = OUT_DIR / "verification_sample.json"
VERIFICATION_FILE = OUT_DIR / "verification.jsonl"

FIELDS_TO_CHECK = ["auth_methods", "self_serve", "has_public_api", "existing_mcp", "verdict"]


def cmd_sample(n: int, ids: list[int] | None, pass_label: str):
    data = {r["id"]: r for r in json.loads(FINAL_FILE.read_text())}
    if ids:
        chosen = [data[i] for i in ids if i in data]
    else:
        chosen = random.sample(list(data.values()), min(n, len(data)))
    SAMPLE_FILE.write_text(json.dumps({"pass_label": pass_label, "apps": chosen}, indent=2), encoding="utf-8")
    print(f"Sampled {len(chosen)} apps -> {SAMPLE_FILE}")
    print("App ids:", [a["id"] for a in chosen])


def cmd_review_detailed():
    """Original field-by-field review, kept as an optional deep-dive."""
    sample = json.loads(SAMPLE_FILE.read_text())
    pass_label = sample["pass_label"]
    apps = sample["apps"]
    print(f"Reviewing {len(apps)} apps (pass: {pass_label}). Ctrl+C to stop and save partial progress.\n")

    records = []
    try:
        for app in apps:
            print("=" * 70)
            print(f"[{app['id']}] {app['app']}  ({app['category']})")
            print(f"  Agent verdict: {app['verdict']}   confidence: {app.get('confidence')}")
            print(f"  auth_methods: {app.get('auth_methods')}")
            print(f"  self_serve: {app.get('self_serve')}  -- {app.get('self_serve_notes','')}")
            print(f"  has_public_api: {app.get('has_public_api')}  api_breadth: {app.get('api_breadth')}")
            print(f"  existing_mcp: {app.get('existing_mcp')}  -- {app.get('mcp_notes','')}")
            print(f"  Evidence: {app.get('evidence_urls')}")
            print()
            for field in FIELDS_TO_CHECK:
                agent_val = str(app.get(field))
                ans = input(f"  Is '{field}' = {agent_val} correct? [y/n/skip]: ").strip().lower()
                if ans == "skip":
                    continue
                correct = ans == "y"
                human_val = agent_val
                if not correct:
                    human_val = input(f"    What's the correct value for '{field}'? ").strip()
                source = input("    Source you checked (URL, optional): ").strip()
                notes = input("    Notes (optional): ").strip()
                records.append({
                    "pass_label": pass_label, "id": app["id"], "app": app["app"],
                    "field_checked": field, "agent_said": agent_val, "human_found": human_val,
                    "correct": correct, "source_checked": source, "reviewer_notes": notes,
                    "review_scope": "field",
                })
            print()
    except KeyboardInterrupt:
        print("\nStopped early, saving progress so far.")

    with open(VERIFICATION_FILE, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Saved {len(records)} verification records -> {VERIFICATION_FILE}")


def cmd_review_quick():
    """One human decision per sampled app, with optional field-level correction notes.

    This keeps the required human audit while avoiding 5-6 prompts for every app.
    The reviewer still checks the cited evidence before deciding.
    """
    sample = json.loads(SAMPLE_FILE.read_text())
    pass_label = sample["pass_label"]
    apps = sample["apps"]
    print(f"Quick-reviewing {len(apps)} apps (pass: {pass_label}). Ctrl+C to stop and save partial progress.\n")
    print("For each app, review the cited evidence and decide whether the overall record is correct.")
    print("Use n only when one or more material fields are wrong; you can record which ones.\n")

    records = []
    try:
        for app in apps:
            print("=" * 78)
            print(f"[{app['id']}] {app['app']}  ({app['category']})")
            print(f"  Verdict: {app.get('verdict')} | Confidence: {app.get('confidence')}")
            print(f"  Auth: {app.get('auth_methods')}")
            print(f"  Access: {app.get('self_serve')}")
            print(f"  Public API: {app.get('has_public_api')} | Breadth: {app.get('api_breadth')}")
            print(f"  MCP: {app.get('existing_mcp')}")
            print("  Evidence:")
            for i, url in enumerate(app.get("evidence_urls") or [], 1):
                print(f"    {i}. {url}")
            print()

            ans = input("  After checking the evidence, is the overall record correct? [y/n/skip]: ").strip().lower()
            if ans == "skip":
                continue

            correct = ans == "y"
            wrong_fields = []
            corrections = {}
            source = input("  Source checked (URL, optional): ").strip()
            notes = ""
            if not correct:
                raw = input("  Wrong fields (comma-separated: auth_methods,self_serve,has_public_api,existing_mcp,verdict): ").strip()
                wrong_fields = [x.strip() for x in raw.split(",") if x.strip()]
                for field in wrong_fields:
                    corrections[field] = input(f"    Correct value for {field}: ").strip()
                notes = input("  Notes (optional): ").strip()

            records.append({
                "pass_label": pass_label,
                "id": app["id"],
                "app": app["app"],
                "field_checked": "__app__",
                "agent_said": "overall record",
                "human_found": "overall record correct" if correct else "material discrepancies found",
                "correct": correct,
                "source_checked": source,
                "reviewer_notes": notes,
                "review_scope": "app",
                "wrong_fields": wrong_fields,
                "corrections": corrections,
            })
            print()
    except KeyboardInterrupt:
        print("\nStopped early, saving progress so far.")

    with open(VERIFICATION_FILE, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Saved {len(records)} quick verification records -> {VERIFICATION_FILE}")


def cmd_report():
    if not VERIFICATION_FILE.exists():
        print("No verification.jsonl yet -- run --sample then --review first.")
        return
    rows = [json.loads(l) for l in VERIFICATION_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        print("verification.jsonl is empty.")
        return

    by_pass: dict[str, list[dict]] = {}
    for r in rows:
        by_pass.setdefault(r.get("pass_label", "pass_1"), []).append(r)

    for pass_label, prows in by_pass.items():
        # Quick reviews are one decision per app; detailed reviews remain field-level.
        quick = [r for r in prows if r.get("review_scope") == "app"]
        detailed = [r for r in prows if r.get("review_scope") == "field" or not r.get("review_scope")]

        if quick:
            total = len(quick)
            correct = sum(1 for r in quick if r["correct"])
            print(f"\n=== {pass_label}: app-level verification {correct}/{total} correct ({100*correct/total:.1f}%) ===")
            misses = [r for r in quick if not r["correct"]]
            if misses:
                print("  Missed apps / fields:")
                for m in misses:
                    fields = ", ".join(m.get("wrong_fields") or []) or "unspecified"
                    print(f"    [{m['id']}] {m['app']}: {fields}")
                    if m.get("corrections"):
                        print(f"      Corrections: {m['corrections']}")
            else:
                print("  No misses in this pass.")

        if detailed:
            total = len(detailed)
            correct = sum(1 for r in detailed if r["correct"])
            print(f"\n=== {pass_label}: field-level verification {correct}/{total} correct ({100*correct/total:.1f}%) ===")
            by_field: dict[str, list[dict]] = {}
            for r in detailed:
                by_field.setdefault(r["field_checked"], []).append(r)
            for field, frows in by_field.items():
                fc = sum(1 for r in frows if r["correct"])
                print(f"  {field:16} {fc}/{len(frows)} correct")
            misses = [r for r in detailed if not r["correct"]]
            if misses:
                print("  Misses:")
                for m in misses:
                    print(f"    [{m['id']}] {m['app']} / {m['field_checked']}: "
                          f"agent said '{m['agent_said']}', actually '{m['human_found']}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, help="Sample size")
    parser.add_argument("--ids", type=int, nargs="*", help="Specific app ids to sample instead of random")
    parser.add_argument("--pass-label", default="pass_1", help="Label for this verification pass, e.g. pass_1, pass_2")
    parser.add_argument("--review", action="store_true", help="Quick one-decision-per-app human review")
    parser.add_argument("--detailed-review", action="store_true", help="Original field-by-field review")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.sample is not None or args.ids:
        cmd_sample(args.sample or len(args.ids or []), args.ids, args.pass_label)
    elif args.review:
        cmd_review_quick()
    elif args.detailed_review:
        cmd_review_detailed()
    elif args.report:
        cmd_report()
    else:
        parser.print_help()
