# CI v3.5 — Hetzner Server Setup

## Prerekvizity
Existující cron `cron-ci-daily-snapshots.sh` sbírá denní snapshots.
Nový `ci_dashboard_refresh.py` přidává: funnel scores, thumbnaily, leaderboard, HTML dashboard.

## Setup (jednorázově)

```bash
# 1. SSH na Hetzner
ssh fermato@100.71.221.77

# 2. Pull nový kód
cd /home/fermato/Chief-of-Staff
git pull

# 3. Pip install (pokud chybí nové závislosti)
/home/fermato/venv/bin/pip install anthropic  # pro AI tagging

# 4. Vytvořit/aktualizovat cron launcher
cat > /home/fermato/cron-ci-dashboard.sh << 'EOF'
#!/bin/bash
source /home/fermato/run-all-crons.sh
load_creds
cd "$REPO/fermato-dev"
"$VENV/python3" scripts/ci_dashboard_refresh.py --days 14 >> /home/fermato/logs/ci-dashboard.log 2>&1
EOF
chmod +x /home/fermato/cron-ci-dashboard.sh

# 5. Přidat cron (denně v 06:15, po CI snapshot collection v 06:00)
(crontab -l; echo "15 6 * * * /home/fermato/cron-ci-dashboard.sh") | crontab -

# 6. Ověřit
crontab -l | grep dashboard
```

## Co pipeline dělá (denně 06:15)
1. Sbírá včerejší daily snapshots z Meta API
2. Počítá funnel scores (Hook/Watch/Click/Convert 1-100)
3. Ukládá thumbnail URLs pro aktivní ads
4. Aktualizuje creative leaderboard
5. Generuje HTML dashboard
6. Kopíruje HTML + DB do dashboard repa → git push → Railway auto-deploy

## AI Tagging (týdně)
AI tagging (Claude Vision, ~$0.003/ad) se spouští v rámci weekly runneru.
Neběží denně (zbytečný cost). Nové ads se tagují při weekly run.

## Monitoring
- Log: `/home/fermato/logs/ci-dashboard.log`
- Dashboard: `http://100.71.221.77:8501` (Streamlit backup) nebo Railway
- HTML: `fermato-dev/data/ci-dashboard.html`
