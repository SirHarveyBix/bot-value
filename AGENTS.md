# Équipe ValueMomentum Scanner

Ce document définit les rôles et responsabilités de l'équipe travaillant sur le bot. Les rôles détaillés sont dans `.agents/roles/`.

---

## Rôles

### Product Owner (PO)

**Mission :** Garantir que le bot répond aux besoins métier et respecte les spécifications.

- Valide la conformité des fonctionnalités avec l'architecture en Entonnoir (Section 2 des specs).
- Supervise la qualité des données via l'API FMP (Sniper).
- S'assure que les ratios de données (Chalutier & Sniper) sont respectés.

Rôle complet : `.agents/roles/po.md`

### Trader Expert ValueMomentum

**Mission :** Maximiser la performance de la stratégie et minimiser les risques.

- Pilote le **Market Gate** (cascade 4 niveaux : normal / bear_light / prudence / panic).
- Valide les seuils de liquidité institutionnels (Cap 2B$, Volume 5M$).
- Analyse le **ROE 3 ans** pour confirmer le Moat structurel des entreprises.

Rôle complet : `.agents/roles/trader.md`

### Lead Developer

**Mission :** Garantir l'architecture, la performance et l'intégrité des données.

- Assure la robustesse du stockage **SQLite** pour les accès concurrents.
- Supervise la séparation asynchrone (yfinance vs httpx/FMP).
- Valide l'exactitude du calcul ROE multi-années.
- Gère le déploiement via **supervisord** (voir `supervisord.conf` et README).

Rôle complet : `.agents/roles/lead-dev.md`

### Senior Developers

- **Dév Senior 1 (Performance/Data)** : Intégration API FMP pour le Sniper, optimisation batch download yfinance.
- **Dév Senior 2 (Algorithmes)** : Scoring asymétrique (Momentum technique vs Qualité fondamentale).
- **Dév Senior 3 (Système/Ops)** : Résilience du scheduler APScheduler 4.x et déploiement supervisord.

### Beginner Developer

- Installation (`venv`, `requirements.txt`).
- Tests de bout en bout (`python3 main.py --now --force`).
- Consultation des logs (`data/logs/`).

---

## Workflow de Validation

Tout changement majeur doit être validé par :

1. Le **Trader** (pertinence financière).
2. Le **Lead Dev** (intégrité technique / async).
3. Le **PO** (conformité architecture funnel).

---

## Commandes Utiles

```bash
# Lancer les tests
./venv/bin/pytest tests/ -v

# Scan immédiat (test, marché fermé OK)
./venv/bin/python main.py --now --force

# Statut du process manager
./venv/bin/supervisorctl -c supervisord.conf status

# Logs en temps réel
tail -f data/logs/scanner_$(date +%Y-%m-%d).log

# Installer le LaunchAgent (démarrage auto au boot)
bash scripts/install-launchd.sh
launchctl list | grep valuemomentum   # PID non-zéro = actif
```
