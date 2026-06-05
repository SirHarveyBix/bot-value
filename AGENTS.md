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

Tout changement majeur doit être validé par les 3 rôles dans cet ordre. Chaque niveau peut **bloquer** la PR.

### Niveau 1 — Trader Expert (pertinence financière)

**Bloque la PR si** :

- Un seuil de scoring (pondération, gate d'exclusion, exception sectorielle) est modifié sans justification financière documentée dans `.agents/roles/trader.md`
- Une règle d'exclusion qualité (ROE < 0, BVPS ≤ 0, Dette/EBITDA > 6x) est affaiblie ou supprimée
- Une exception sectorielle (Financials, Immobilier, Utilities, Biotech) est modifiée sans validation
- Le Market Gate perd sa priorité VIX-first ou ses 4 niveaux

**Processus** : Remplir le checklist PR dans `.agents/roles/trader.md` et ajouter une entrée dans "Validation Complète des Stratégies".

### Niveau 2 — Lead Developer (intégrité technique)

**Bloque la PR si** :

- `yfinance` est utilisé pour des données fondamentales (autre que `roe_3y` fallback documenté)
- `shortlist_size` est modifié sans recalcul explicite du budget FMP (30 × 5 = 150 + 25 = 175)
- Des pondérations sont hardcodées dans le code au lieu d'utiliser `CONFIG["scoring"]["weights"]`
- Un test réseau ne passe pas par une cassette VCR.py
- Une logique temporelle sensible (freshness, decay earnings) ne passe pas par Freezegun
- Le budget FMP est dépassé (plus de 175 appels simulés pour un run complet 30 tickers)

**Processus** : Vérifier la séparation des sources, les tests, et le budget avant d'approuver.

### Niveau 3 — Product Owner (conformité architecture)

**Bloque la PR si** :

- L'architecture en entonnoir Chalutier/Sniper est contournée
- Des ETFs reçoivent un scoring fondamental (ROE, P/E) au lieu de momentum pur
- Le pipeline produit des signaux sans données FMP validées (sauf régime Panique)
- La constitution `.specify/memory/constitution.md` est contredite sans amendement documenté

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
