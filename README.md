# Creative Intelligence

Fermato Meta Ads creative analytics — dashboard + rule engine pro optimalizaci kreativ.

## Struktura

```
dashboard/          # Streamlit dashboard (multi-page)
  app.py            # Hlavni stranka — prehled kreativ
  shared_data.py    # Sdilena data, cache, helpers
  pages/
    1_Video_kreativy.py
    2_Bannery_a_staticke.py
    3_Attribution_check.py

scripts/            # Analytics engine + bridges
  creative_intelligence.py   # Core rule engine (KILL/SCALE/ITERATE/WATCH)
  creative_vision.py         # AI-powered creative recommendations
  creative_weekly_runner.py  # Tydeni automaticky runner
  ga4_bridge.py              # GA4 Data API wrapper
  shoptet_bridge.py          # Shoptet order data bridge
```

## Setup

```bash
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

## Data zdroje

- **Meta Ads API** — creative-level metriky (ROAS, CPA, CVR, hook rate, spend)
- **GA4** — attribution, channel mix, device breakdown
- **Shoptet** — objednavky, revenue pro attribution check
