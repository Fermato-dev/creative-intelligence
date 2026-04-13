# fermato-dev — Creative Intelligence v3.5

Fermato Meta Ads Creative Intelligence system.
Python package: `creative_intelligence/`

## Struktura

```
creative_intelligence/
  config.py              — shared config, targets, benchmarks
  meta_client.py         — Meta Graph API client (retry, pagination)
  claude_client.py       — Claude API client (text + vision)
  metrics.py             — ad-level metrics calculation (25+ metrik)
  rules.py               — kill/scale/iterate rule engine
  report.py              — text report + CSV export
  vision.py              — AI vision analysis (video + static)
  runner.py              — weekly orchestrator (pumble, snapshot, vision)
  pumble.py              — Pumble notification client
  decomposition.py       — v3: scene decomposition (hook/body/CTA)
  component_db.py        — v3: component library (SQLite)
  combinator.py          — v3: combinatorial recommendations
  change_tracker.py      — v3: daily snapshots + change detection + lift
  funnel_scores.py       — v3.5: Hook/Watch/Click/Convert scoring (1-100)
  performance_shifts.py  — v3.5: Scaling/Declining/New/Paused categorization
  visual_tagger.py       — v3.5: AI visual format + messaging tagging
  comparative.py         — v3.5: ad type/format/messaging/length comparison
  leaderboard.py         — v3.5: weekly creative ranking + position tracking
  cli.py                 — unified CLI entry point
```

## Spusteni

```bash
python -m creative_intelligence --days 7           # weekly report
python -m creative_intelligence --days 14 --json   # JSON export
python -m creative_intelligence decompose           # v3: scene decomposition
python -m creative_intelligence components          # v3: list component library
python -m creative_intelligence recommend           # v3: combinatorial recommendations
python -m creative_intelligence scores              # v3.5: funnel scores (1-100)
python -m creative_intelligence shifts              # v3.5: performance shifts
python -m creative_intelligence leaderboard         # v3.5: creative leaderboard
python -m creative_intelligence tag                 # v3.5: AI visual format tagging
python -m creative_intelligence compare             # v3.5: comparative analysis
```

## Config

- `META_ADS_ACCESS_TOKEN` — Meta Graph API
- `ANTHROPIC_API_KEY` — Claude API
- `PUMBLE_API_TOKEN` — Pumble notifications
- Ad Account: `act_346692147206629`
- Targets: ROAS 2.5, CPA 250 CZK

## Jazyk

Vždy česky.
