"""
Builds the single self-contained HTML case study page from:
  - output/final_results.json   (the 100 research results)
  - output/verification.jsonl   (human verification records, pass_1/pass_2)

Output: output/report.html -- deploy this directly (Vercel/Netlify/GitHub
Pages all serve a static HTML file with zero config) and submit that URL.
"""

from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "output"
FINAL_FILE = OUT_DIR / "final_results.json"
VERIFICATION_FILE = OUT_DIR / "verification.jsonl"
REPORT_FILE = OUT_DIR / "report.html"


def load_data():
    results = json.loads(FINAL_FILE.read_text()) if FINAL_FILE.exists() else []
    verification = []
    if VERIFICATION_FILE.exists():
        verification = [json.loads(l) for l in VERIFICATION_FILE.read_text().splitlines() if l.strip()]
    return results, verification


def compute_patterns(results: list[dict]) -> dict:
    n = len(results)
    auth_counter = Counter()
    for r in results:
        for a in r.get("auth_methods", []):
            auth_counter[a] += 1

    self_serve_counter = Counter(r.get("self_serve", "Unknown") for r in results)
    verdict_counter = Counter(r.get("verdict", "Unknown") for r in results)
    blocker_counter = Counter(r.get("blocker", "").strip() for r in results if r.get("blocker", "").strip())
    mcp_count = sum(1 for r in results if r.get("existing_mcp"))
    composio_count = sum(1 for r in results if r.get("composio_supported"))

    by_category = defaultdict(lambda: Counter())
    for r in results:
        by_category[r.get("category", "?")][r.get("verdict", "Unknown")] += 1

    return {
        "n": n,
        "auth_counter": auth_counter,
        "self_serve_counter": self_serve_counter,
        "verdict_counter": verdict_counter,
        "blocker_counter": blocker_counter,
        "mcp_count": mcp_count,
        "composio_count": composio_count,
        "by_category": dict(by_category),
    }


def compute_verification_summary(verification: list[dict]) -> dict:
    by_pass = defaultdict(list)
    for r in verification:
        by_pass[r.get("pass_label", "pass_1")].append(r)
    summary = {}
    for label, rows in by_pass.items():
        # Prefer the quick app-level review when present; fall back to the original field-level review.
        quick = [r for r in rows if r.get("review_scope") == "app"]
        used = quick if quick else rows
        total = len(used)
        correct = sum(1 for r in used if r["correct"])
        misses = [r for r in used if not r["correct"]]
        summary[label] = {
            "total": total, "correct": correct,
            "pct": round(100 * correct / total, 1) if total else 0,
            "misses": misses,
            "scope": "apps" if quick else "fields",
        }
    return summary


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def verdict_class(v: str) -> str:
    return {"Buildable today": "v-good", "Buildable with friction": "v-mid",
            "Blocked": "v-bad"}.get(v, "v-unknown")


def render_table_rows(results: list[dict]) -> str:
    rows = []
    for r in sorted(results, key=lambda x: x["id"]):
        auth = ", ".join(r.get("auth_methods", [])) or "—"
        evidence = r.get("evidence_urls", [])
        ev_link = f'<a href="{esc(evidence[0])}" target="_blank" rel="noopener">source</a>' if evidence else "—"
        rows.append(f"""
        <tr data-category="{esc(r.get('category',''))}" data-verdict="{esc(r.get('verdict',''))}">
          <td>{r['id']}</td>
          <td class="app-name">{esc(r['app'])}</td>
          <td>{esc(r.get('category',''))}</td>
          <td>{esc(r.get('one_liner',''))}</td>
          <td>{esc(auth)}</td>
          <td>{esc(r.get('self_serve',''))}</td>
          <td>{esc(r.get('api_breadth',''))}</td>
          <td>{"✓" if r.get('existing_mcp') else "—"}</td>
          <td>{"✓" if r.get('composio_supported') else ("—" if r.get('composio_supported') is False else "?")}</td>
          <td><span class="verdict-badge {verdict_class(r.get('verdict',''))}">{esc(r.get('verdict',''))}</span></td>
          <td>{esc(r.get('blocker',''))}</td>
          <td>{ev_link}</td>
        </tr>""")
    return "\n".join(rows)


def render_category_bars(patterns: dict) -> str:
    parts = []
    for cat, counter in sorted(patterns["by_category"].items()):
        total = sum(counter.values())
        good = counter.get("Buildable today", 0)
        mid = counter.get("Buildable with friction", 0)
        bad = counter.get("Blocked", 0)
        unk = total - good - mid - bad
        parts.append(f"""
        <div class="cat-row">
          <div class="cat-label">{esc(cat)}</div>
          <div class="cat-bar">
            <div class="seg v-good" style="width:{100*good/total:.1f}%" title="{good} buildable today"></div>
            <div class="seg v-mid" style="width:{100*mid/total:.1f}%" title="{mid} buildable with friction"></div>
            <div class="seg v-bad" style="width:{100*bad/total:.1f}%" title="{bad} blocked"></div>
            <div class="seg v-unknown" style="width:{100*unk/total:.1f}%" title="{unk} unknown"></div>
          </div>
          <div class="cat-count">{total}</div>
        </div>""")
    return "\n".join(parts)


def render_verification_section(vsummary: dict) -> str:
    if not vsummary:
        return "<p class='muted'>No verification data yet — run agent/verify.py to generate it.</p>"
    parts = []
    labels = sorted(vsummary.keys())
    for label in labels:
        s = vsummary[label]
        parts.append(f"""
        <div class="verify-pass">
          <h3>{esc(label)}</h3>
          <div class="big-stat">{s['correct']}/{s['total']} <span class="muted">{('apps' if s.get('scope') == 'apps' else 'fields')} correct ({s['pct']}%)</span></div>
          {"<div class='misses'><strong>Misses:</strong><ul>" + "".join(
              (f"<li>[{m['id']}] {esc(m['app'])} — wrong fields: <code>{esc(', '.join(m.get('wrong_fields') or ['unspecified']))}</code>"
               + (f"; corrections: {esc(str(m.get('corrections')))}" if m.get('corrections') else "") + "</li>")
              if s.get('scope') == 'apps' else
              f"<li>[{m['id']}] {esc(m['app'])} — <code>{esc(m['field_checked'])}</code>: agent said <em>{esc(m['agent_said'])}</em>, actually <em>{esc(m['human_found'])}</em></li>"
              for m in s['misses']) + "</ul></div>" if s['misses'] else "<p class='muted'>No misses in this pass.</p>"}
        </div>""")
    if len(labels) >= 2:
        first, last = vsummary[labels[0]], vsummary[labels[-1]]
        delta = last['pct'] - first['pct']
        parts.insert(0, f"""
        <div class="verify-delta">
          Verification accuracy moved from <strong>{first['pct']}%</strong> ({labels[0]}) to
          <strong>{last['pct']}%</strong> ({labels[-1]}), a {'+' if delta>=0 else ''}{delta:.1f} point change.
          Passes are based on fresh random samples; misses are shown rather than hidden.
        </div>""")
    return "\n".join(parts)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent-Buildability Research: 100 Apps</title>
<style>
  :root {{
    --ink:#16181d; --muted:#6b7280; --line:#e5e7eb; --bg:#fafafa; --card:#ffffff;
    --good:#0f9d58; --good-bg:#e6f7ee; --mid:#b45309; --mid-bg:#fef3e2;
    --bad:#c0362c; --bad-bg:#fdecea; --unk:#9ca3af; --unk-bg:#f3f4f6;
    --accent:#4338ca;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family: -apple-system, "Segoe UI", Inter, Roboto, sans-serif; line-height:1.5; }}
  header {{ padding:48px 32px 32px; max-width:1100px; margin:0 auto; }}
  header h1 {{ font-size:2rem; margin:0 0 8px; letter-spacing:-0.02em; }}
  header p.sub {{ color:var(--muted); font-size:1.05rem; margin:0; max-width:70ch; }}
  main {{ max-width:1100px; margin:0 auto; padding:0 32px 80px; }}
  section {{ margin-top:48px; }}
  h2 {{ font-size:1.3rem; margin:0 0 16px; border-bottom:2px solid var(--ink); padding-bottom:8px; }}
  .stat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:16px; margin-bottom:24px; }}
  .stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:18px; }}
  .stat .num {{ font-size:2rem; font-weight:700; }}
  .stat .label {{ color:var(--muted); font-size:0.85rem; }}
  .headline-list {{ list-style:none; padding:0; margin:0; display:grid; gap:10px; }}
  .headline-list li {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
    border-radius:6px; padding:14px 16px; }}
  .cat-row {{ display:grid; grid-template-columns:220px 1fr 40px; align-items:center; gap:12px; margin-bottom:8px; }}
  .cat-label {{ font-size:0.9rem; }}
  .cat-count {{ text-align:right; color:var(--muted); font-size:0.85rem; }}
  .cat-bar {{ display:flex; height:16px; border-radius:4px; overflow:hidden; background:var(--unk-bg); }}
  .seg {{ height:100%; }}
  .v-good {{ background:var(--good); }} .v-mid {{ background:var(--mid); }}
  .v-bad {{ background:var(--bad); }} .v-unknown {{ background:var(--unk); }}
  .legend {{ display:flex; gap:16px; font-size:0.8rem; color:var(--muted); margin-top:8px; flex-wrap:wrap; }}
  .legend span {{ display:inline-flex; align-items:center; gap:6px; }}
  .dot {{ width:10px; height:10px; border-radius:2px; display:inline-block; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); font-size:0.85rem; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  td {{ white-space:normal; }}
  th {{ position:sticky; top:0; background:var(--card); cursor:pointer; user-select:none; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; max-height:640px; overflow-y:auto; }}
  .app-name {{ font-weight:600; }}
  .verdict-badge {{ padding:2px 8px; border-radius:999px; font-size:0.75rem; font-weight:600; white-space:nowrap; }}
  .verdict-badge.v-good {{ background:var(--good-bg); color:var(--good); }}
  .verdict-badge.v-mid {{ background:var(--mid-bg); color:var(--mid); }}
  .verdict-badge.v-bad {{ background:var(--bad-bg); color:var(--bad); }}
  .verdict-badge.v-unknown {{ background:var(--unk-bg); color:var(--unk); }}
  .filters {{ display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }}
  .filters select, .filters input {{ padding:6px 10px; border:1px solid var(--line); border-radius:6px; font-size:0.85rem; }}
  .agent-flow {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; }}
  .flow-step {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }}
  .flow-step .n {{ color:var(--accent); font-weight:700; font-size:0.8rem; }}
  .flow-step h4 {{ margin:6px 0; }}
  .flow-step p {{ margin:0; color:var(--muted); font-size:0.88rem; }}
  .method-card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px; max-width:900px; }}
  .method-card p {{ margin:0 0 10px; }}
  .method-card p:last-child {{ margin-bottom:0; }}
  .method-card ul {{ margin:0; padding-left:20px; }}
  .method-card li {{ margin-bottom:8px; }}
  .verify-pass {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:18px; margin-bottom:16px; }}
  .verify-delta {{ background:#eef2ff; border:1px solid #c7d2fe; border-radius:8px; padding:14px 16px; margin-bottom:16px; font-size:0.95rem; }}
  .big-stat {{ font-size:1.5rem; font-weight:700; margin:6px 0 10px; }}
  .misses ul {{ margin:8px 0 0; padding-left:20px; font-size:0.88rem; }}
  .misses code {{ background:var(--unk-bg); padding:1px 5px; border-radius:4px; }}
  .muted {{ color:var(--muted); }}
  footer {{ max-width:1100px; margin:0 auto; padding:24px 32px 60px; color:var(--muted); font-size:0.85rem; }}
  a {{ color:var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>Would this app survive an AI agent trying to use it?</h1>
  <p class="sub">Researching auth, access gating, API surface, and agent-buildability across 100 real
  SaaS apps — done by an agent, verified by a human, with the misses shown honestly. This page is the
  whole case study: patterns first, full data below, then how it was built and checked.</p>
</header>
<main>

<section id="patterns">
  <h2>The headline patterns</h2>
  <div class="stat-grid">
    <div class="stat"><div class="num">{n_buildable_today}</div><div class="label">Buildable today / 100</div></div>
    <div class="stat"><div class="num">{n_friction}</div><div class="label">Buildable with friction</div></div>
    <div class="stat"><div class="num">{n_blocked}</div><div class="label">Blocked</div></div>
    <div class="stat"><div class="num">{pct_oauth}%</div><div class="label">Use OAuth2</div></div>
    <div class="stat"><div class="num">{n_mcp}</div><div class="label">Already have an MCP server</div></div>
    <div class="stat"><div class="num">{n_composio}</div><div class="label">Already in Composio's catalog</div></div>
  </div>
  <ul class="headline-list">
    {headline_bullets}
  </ul>
</section>

<section id="methodology">
  <h2>Methodology</h2>
  <div class="method-card">
    <p><strong>Scope:</strong> 100 real SaaS applications were evaluated for agent-buildability.</p>
    <p><strong>Evidence:</strong> The research agent used public web documentation and extracted structured fields for authentication, access model, API surface, MCP availability, and buildability.</p>
    <p><strong>Verification:</strong> A separate random sample was manually checked against the cited documentation. Material misses are shown rather than hidden.</p>
    <p><strong>Interpretation:</strong> “Buildable today” means the documented interface appears usable for an agent integration; it does not mean a production-ready integration requires no engineering effort.</p>
  </div>
</section>

<section id="by-category">
  <h2>Buildability by category</h2>
  {category_bars}
  <div class="legend">
    <span><span class="dot v-good"></span>Buildable today</span>
    <span><span class="dot v-mid"></span>Buildable with friction</span>
    <span><span class="dot v-bad"></span>Blocked</span>
    <span><span class="dot v-unknown"></span>Unknown</span>
  </div>
</section>

<section id="table">
  <h2>All 100 apps</h2>
  <div class="filters">
    <input id="search" type="text" placeholder="Search app name...">
    <select id="filter-category"><option value="">All categories</option>{category_options}</select>
    <select id="filter-verdict">
      <option value="">All verdicts</option>
      <option>Buildable today</option><option>Buildable with friction</option>
      <option>Blocked</option><option>Unknown</option>
    </select>
  </div>
  <div class="table-wrap">
  <table id="apps-table">
    <thead><tr>
      <th>#</th><th>App</th><th>Category</th><th>What it does</th><th>Auth</th>
      <th>Access</th><th>API breadth</th><th>MCP exists</th><th>In Composio</th>
      <th>Verdict</th><th>Blocker</th><th>Evidence</th>
    </tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
  </div>
</section>

<section id="agent">
  <h2>How the research agent works</h2>
  <div class="agent-flow">
    <div class="flow-step"><div class="n">STEP 1</div><h4>Seed list</h4>
      <p>100 apps loaded from data/apps.json with category + name hint.</p></div>
    <div class="flow-step"><div class="n">STEP 2</div><h4>Agent research</h4>
      <p>DDGS web search gathers current public evidence, then a Groq-hosted LLM
      extracts structured JSON: auth, access model, API surface, verdict, and evidence URLs.</p></div>
    <div class="flow-step"><div class="n">STEP 3</div><h4>Composio cross-check</h4>
      <p>Each app is checked against Composio's own toolkit catalog via their SDK/public
      catalog — a second, independent signal on buildability.</p></div>
    <div class="flow-step"><div class="n">STEP 4</div><h4>Human verification</h4>
      <p>A random sample is manually checked against real docs; misses are logged and
      the agent's prompt is tightened for a second pass.</p></div>
  </div>
  <p style="margin-top:16px;" class="muted">Where a human was needed: judgment calls on ambiguous
  gating language (e.g. "request access" pages that are actually near-instant vs. genuinely
  sales-gated), apps with renamed/rebranded docs the search missed, and final sign-off on every
  "Blocked" verdict before treating it as a finding rather than a search miss.</p>
</section>

<section id="verification">
  <h2>Human Verification &amp; Error Analysis</h2>
  <p class="muted">Verification is a sampled audit of the agent's research, not a claim that every row was manually checked.</p>
  {verification_html}
</section>

<section id="limitations">
  <h2>Limitations</h2>
  <div class="method-card">
    <ul>
      <li>SaaS documentation and MCP availability can change over time.</li>
      <li>Search-based research can miss poorly indexed, renamed, or gated documentation.</li>
      <li>API availability and free-plan availability are separate questions; an API may exist while access is paid or restricted.</li>
      <li>The manual audit covers a sample rather than every one of the 100 applications.</li>
      <li>“Unknown” is retained when the available evidence is insufficient rather than being inferred.</li>
    </ul>
  </div>
</section>

</main>
<footer>
  Built for the Composio AI Product Ops take-home. Source: see repo README for how to re-run the
  agent, the verification loop, and this report generator.
</footer>
<script>
  const search = document.getElementById('search');
  const catFilter = document.getElementById('filter-category');
  const verdictFilter = document.getElementById('filter-verdict');
  const rows = Array.from(document.querySelectorAll('#apps-table tbody tr'));
  function applyFilters() {{
    const q = search.value.toLowerCase();
    const cat = catFilter.value;
    const verdict = verdictFilter.value;
    rows.forEach(r => {{
      const name = r.querySelector('.app-name').textContent.toLowerCase();
      const rowCat = r.dataset.category;
      const rowVerdict = r.dataset.verdict;
      const show = name.includes(q) && (!cat || cat === rowCat) && (!verdict || verdict === rowVerdict);
      r.style.display = show ? '' : 'none';
    }});
  }}
  [search, catFilter, verdictFilter].forEach(el => el.addEventListener('input', applyFilters));
</script>
</body>
</html>
"""


def main():
    results, verification = load_data()
    if not results:
        print("No results yet in output/final_results.json — run research_agent.py, "
              "composio_lookup.py, then merge_results.py first. Writing an empty-state page.")

    patterns = compute_patterns(results) if results else {
        "n": 0, "auth_counter": Counter(), "self_serve_counter": Counter(),
        "verdict_counter": Counter(), "blocker_counter": Counter(),
        "mcp_count": 0, "composio_count": 0, "by_category": {}
    }
    vsummary = compute_verification_summary(verification)

    n = patterns["n"] or 1
    top_auth = patterns["auth_counter"].most_common(1)
    top_blocker = patterns["blocker_counter"].most_common(1)
    gated_pct = round(100 * sum(v for k, v in patterns["self_serve_counter"].items()
                                 if k.startswith("Gated")) / n, 1)

    bullets = []
    if top_auth:
        bullets.append(f"<li><strong>{esc(top_auth[0][0])}</strong> is the dominant auth method, "
                        f"used by {top_auth[0][1]}/{patterns['n']} apps.</li>")
    bullets.append(f"<li><strong>{gated_pct}%</strong> of apps are gated in some way "
                    f"(approval, paid plan, or partnership) rather than fully self-serve.</li>")
    if top_blocker:
        bullets.append(f"<li>The most common blocker is <strong>{esc(top_blocker[0][0])}</strong> "
                        f"({top_blocker[0][1]} apps).</li>")
    bullets.append(f"<li><strong>{patterns['mcp_count']}/{patterns['n']}</strong> apps already have "
                    f"a known MCP server; <strong>{patterns['composio_count']}/{patterns['n']}</strong> "
                    f"are already in Composio's own catalog.</li>")

    categories = sorted(set(r.get("category", "") for r in results))
    category_options = "".join(f'<option value="{esc(c)}">{esc(c)}</option>' for c in categories)

    html = HTML_TEMPLATE.format(
        n_buildable_today=patterns["verdict_counter"].get("Buildable today", 0),
        n_friction=patterns["verdict_counter"].get("Buildable with friction", 0),
        n_blocked=patterns["verdict_counter"].get("Blocked", 0),
        pct_oauth=round(100 * patterns["auth_counter"].get("OAuth2", 0) / n, 1),
        n_mcp=patterns["mcp_count"],
        n_composio=patterns["composio_count"],
        headline_bullets="\n".join(bullets),
        category_bars=render_category_bars(patterns) if patterns["by_category"] else "<p class='muted'>No data yet.</p>",
        category_options=category_options,
        table_rows=render_table_rows(results) if results else "<tr><td colspan='12'>No data yet.</td></tr>",
        verification_html=render_verification_section(vsummary),
    )

    OUT_DIR.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html, encoding="utf-8")
    print(f"Wrote {REPORT_FILE}")


if __name__ == "__main__":
    main()
