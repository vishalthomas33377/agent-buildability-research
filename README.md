# Agent-Buildability Research: 100 Apps
👉 [View the live case study](https://vishalthomas33377.github.io/agent-buildability-research/)
Researches whether 100 real SaaS apps could be wrapped as AI-agent toolkits today —
auth method, self-serve vs. gated access, API surface, and a buildability verdict per
app — using an LLM research agent (Claude + web search) cross-checked against
Composio's own toolkit catalog, then verified by hand against real docs.

## What's here

```
data/apps.json                          the 100 apps to research (seed data)
agent/schema.py                         the data contract every result must satisfy
agent/research_agent.py                 the research agent: Gemini (grounded search) -> structured JSON per app
agent/research_agent_anthropic_backup.py same agent, Claude + web_search version (needs ANTHROPIC_API_KEY instead)
agent/composio_lookup.py                cross-checks each app against Composio's own toolkit catalog
agent/merge_results.py                  merges the two sources into output/final_results.json
agent/verify.py                         human verification loop (sample -> review -> report)
agent/generate_report.py                builds output/report.html, the final case study page
output/                                 all generated data + the final report lands here
```

## Setup (free research path)

The default research agent now uses **DDGS for ordinary web search + Groq for structured extraction**. This avoids Gemini Search Grounding, which is not available in the Gemini API free tier for current Gemini 3.x models. Groq currently publishes a free developer tier with generous daily request limits for its supported models.

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

Run the smoke test after installing dependencies; it checks both web search and Groq before touching your dataset:

```powershell
python agent\test_setup.py
```

Open `.env` and add a Groq API key:

```text
GROQ_API_KEY=gsk_...
COMPOSIO_API_KEY=comp-...   # optional for the Composio cross-check
```

The default model is `openai/gpt-oss-120b`. You can override it with `GROQ_MODEL`.

The research agent performs two ordinary web searches per app, then makes one LLM extraction call per app. Search results provide the evidence URLs; the LLM is not allowed to invent URLs. This keeps the research auditable while avoiding Google's paid Search Grounding dependency.

## Run the full pipeline

First test one app from a clean run:

```powershell
python agent\research_agent.py --fresh --limit 1
```

If that succeeds, test five:

```powershell
python agent\research_agent.py --fresh --limit 5
```

Then run all 100. Use `--resume` if interrupted:

```powershell
python agent\research_agent.py --fresh
python agent\research_agent.py --resume
```

Then cross-check, merge, verify, and build the HTML:

```powershell
python agent\composio_lookup.py
python agent\merge_results.py
python agent\verify.py --sample 20 --pass-label pass_1
python agent\verify.py --review
python agent\verify.py --report
python agent\generate_report.py
```

Open `output\report.html` in your browser.

## Run the full pipeline

```bash
# 1. Research all 100 apps (this is the "agent" — takes ~15-30 min, costs a few dollars)
python agent/research_agent.py

# If it gets interrupted or a few apps fail, resume safely:
python agent/research_agent.py --resume

# 2. Cross-check against Composio's own catalog
python agent/composio_lookup.py

# 3. Merge both sources into one dataset
python agent/merge_results.py

# 4. Build the report (works even before verification -- that section just says so)
python agent/generate_report.py
open output/report.html
```

## Verification loop (do this before your final report generation)

```bash
# Pass 1: sample 20 apps at random and review them by hand against real docs
python agent/verify.py --sample 20 --pass-label pass_1
python agent/verify.py --review
python agent/verify.py --report
```

Look at the misses printed by `--report`. If there's a pattern (e.g. the agent keeps
confusing "self-serve trial" with "self-serve free", or missing that an app requires a
paid plan for API access specifically), tighten `SYSTEM_PROMPT` in `research_agent.py`
to explicitly call that out, then re-run just the apps that were wrong:

```bash
python agent/research_agent.py --only 7 23 41 68   # the ids that were wrong in pass 1
python agent/merge_results.py
```

Then verify a **fresh** random sample (not the ones you already fixed) to get an honest
pass 2 number:

```bash
python agent/verify.py --sample 20 --pass-label pass_2
python agent/verify.py --review
python agent/verify.py --report
```

`generate_report.py` will automatically show the pass_1 -> pass_2 accuracy delta if both
exist in `output/verification.jsonl`.

## Deploying the report

`output/report.html` is fully self-contained (no build step, no external calls except
loading the page itself). Drop it on any static host:

- **Vercel/Netlify**: drag-and-drop the single file, or `vercel --prod output/report.html`
- **GitHub Pages**: commit it as `docs/index.html` and enable Pages on that folder

## Known limitations / where a human was needed

- The agent's web search sometimes finds marketing pages instead of developer docs for
  smaller/newer apps (rows 50-60, 84-99 in the seed list) — these get flagged with
  `confidence: "Low"` and were prioritized in manual verification.
- "Gated" vs. "self-serve with friction" is a judgment call for apps with a request-access
  form that's actually approved near-instantly vs. ones that are genuinely sales-gated;
  the agent's prompt asks it to state which, but this was double-checked by hand for every
  app marked "Gated (partnership/contact-sales)".
- Composio's toolkit slugs don't always match the app's display name (e.g. rebrands,
  multi-word names); `composio_lookup.py` falls back to SDK search when the direct slug
  guess 404s, but a few may still show as "not found" when they do in fact exist under a
  different slug — these are worth a manual spot-check before treating "not in Composio"
  as a finding.
