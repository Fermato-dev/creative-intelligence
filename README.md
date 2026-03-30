# Fermato Creative Intelligence

Meta Ads performance analysis toolkit pro e-commerce. Automaticky stahuje ad-level data z Meta API, pocita hook rate / hold rate / fatigue skore a generuje **kill / scale / iterate** doporuceni pro kazdy ad.

## Co to umi

- **Creative Intelligence** (`creative_intelligence.py`) — core analyza Meta Ads: spend, ROAS, CPA, CVR, hook rate, hold rate, fatigue detection, video drop-off diagnoza
- **Creative Vision** (`creative_vision.py`) — AI analyza kreativ pres Claude Vision API (extrakce klicovych framu, transkripce audia, vizualni analyza)
- **Weekly Runner** (`creative_weekly_runner.py`) — orchestrator pro automaticky tydenni beh s Pumble notifikacemi a historickymi trendy
- **GA4 Bridge** (`ga4_bridge.py`) — attribution cross-check s Google Analytics 4
- **Shoptet Bridge** (`shoptet_bridge.py`) — overeni objednavek a trzeb z e-shopu

## Klicove metriky

| Metrika | Popis |
|---------|-------|
| Hook Rate | 3s video views / impressions — jak dobre creative zaujme |
| Hold Rate | ThruPlays / 3s views — jak dobre creative udrzi pozornost |
| Fatigue Score | Sleduje frequency, CTR trend, CPA trend — detekce opotrebeni |
| Video Drop-off | Diagnoza: SPATNY_HOOK / MIDDLE_SAG / POZDNI_CTA |

## Rozhodovaci engine

Kazdy ad dostane doporuceni:
- **SCALE** — vysoka ROAS + niska CPA + dobra confidence → zvysit budget
- **KILL** — niska ROAS + vysoka CPA + dostatek dat → zastavit
- **ITERATE** — potencial, ale problem v hook/hold/LP → konkretni diagnoza co zlepsit

## Setup

### Prerekvizity
- Python 3.10+
- Meta Marketing API access token
- (volitelne) `ANTHROPIC_API_KEY` pro Claude Vision analyzu
- (volitelne) `ffmpeg` v PATH pro video analyzu

### Environment variables

```bash
export META_ADS_ACCESS_TOKEN="your_meta_token"
export ANTHROPIC_API_KEY="your_anthropic_key"    # pro creative_vision.py
export SHOPTET_API_TOKEN="your_shoptet_token"    # pro shoptet_bridge.py
```

### Pouziti

```bash
# Zakladni analyza poslednich 14 dni
python creative_intelligence.py

# Poslednich 30 dni, JSON vystup
python creative_intelligence.py --days 30 --json

# CSV export
python creative_intelligence.py --csv

# Tydenni automaticky beh (7 dni + Pumble report + AI analyza)
python creative_weekly_runner.py

# Bez Pumble notifikace
python creative_weekly_runner.py --no-pumble

# AI analyza kreativ
python creative_vision.py --report
```

## Konfigurace

V `creative_intelligence.py` si uprav target metriky:

```python
TARGET_CPA = 250       # CZK, cilova CPA
TARGET_ROAS = 2.5      # cilova ROAS
MIN_SPEND_FOR_DECISION = 200  # min spend pro rozhodnuti
MIN_IMPRESSIONS = 1000  # min impressions pro hook rate
```

## Architektura

```
creative_intelligence.py   # Core: Meta API → metriky → scoring → doporuceni
creative_vision.py         # AI: video framy → Claude Vision → kreativni insights
creative_weekly_runner.py  # Orchestrator: schedule + snapshots + alerting + Pumble
ga4_bridge.py             # GA4 attribution cross-check
shoptet_bridge.py         # Shoptet order/revenue verification
```

## License

Internal tool — Fermato s.r.o.
