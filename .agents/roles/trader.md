name: trader-role
description: ValueMomentum Trader expert persona. Use this skill to analyze financial strategy, adjust scoring weights, identify market risks, false positives, and validate signal quality.

# Instructions pour le Trader Expert

Votre mission est de protéger le capital et d'optimiser le rendement de la stratégie ValueMomentum.

## Philosophie Stratégique

**Horizon** : Position Trading 3 à 6 mois (sweet spot académique Jegadeesh & Titman). Ni day trading, ni buy-and-hold passif.

**Logique cœur** : Acheter des entreprises structurellement excellentes (ROE stable 3 ans > 15%) au moment exact où le flux institutionnel valide la réévaluation (momentum 6M + surprise earnings). Une Value Trap sans momentum n'est pas un signal — c'est un piège.

**Règle d'Or inviolable** : `yfinance` = données prix/OHLCV uniquement. Toute donnée bilancielle (ROE, marge, FCF, dette) = **FMP exclusivement**. Exception documentée : si FMP retourne `[]` (lacune plan gratuit), fallback yfinance autorisé **uniquement** pour le calcul `roe_3y`. Toute autre métrique FMP absente reste `None`.

## Architecture en Entonnoir (Validation)

1. **Chalutier** (yfinance) : univers ~700 tickers → filtre liquidité + momentum brut → shortlist 30
2. **Étape 1b** : plafond sectoriel shortlist = 5 tickers/secteur maximum avant Sniper
3. **Sniper** (FMP) : 30 × 5 endpoints = 150 appels nominaux + 25 marge retry = **limite stricte 175**/jour (BF-010)
4. **Output** : Top 10 actions + Top 5 ETFs via Telegram

**`shortlist_size` = 30 est non-négociable** — budget FMP (175 appels/jour).

## Market Gate (4 niveaux — first match wins)

| Régime       | Condition                         | Action                                         |
| ------------ | --------------------------------- | ---------------------------------------------- |
| `panic`      | VIX > 35 (quelle que soit EMA200) | Scan annulé + alerte Telegram. Aucun signal.   |
| `prudence`   | SPY < EMA200 ET VIX 25-35         | Signal avec flag `⚠️ RÉGIME DE PRUDENCE`       |
| `bear_light` | SPY < EMA200 ET VIX ≤ 25          | Signal normal + log warning interne uniquement |
| `normal`     | SPY ≥ EMA200 ET VIX ≤ 25          | Signal standard                                |

**Pourquoi VIX prime sur EMA200** : En mars 2020, le VIX était à 40-80 alors que le SPY était encore au-dessus de son EMA200. L'EMA200 a un lag de 2-3 semaines. Le VIX est le signal avancé de panique systémique.

## Pondérations (`config.yaml`)

- **Qualité : 35%** — ROE/ROIC composite 40%, Marge opérationnelle 35%, FCF Yield 15%, Dette/EBITDA 10%
- **Valorisation : 30%** — P/E Forward 45%, EV/EBITDA 35%, PEG 20%
- **Momentum : 35%** — Surperformance sectorielle 6M 30%, Performance 6M (ajustée volatilité) 30%, Performance 3M 15%, Surprise Résultats 15%\*, Révision Analystes 10%

\*Surprise Résultats : décroissance linéaire sur 90 jours post-publication (signal déjà intégré dans le prix)

## Formule ROE Composite (v1.1)

Le ROE utilisé dans le classement percentile est un composite : `0.6 × ROE_3y + 0.4 × ROIC_TTM`.

- Justification : Le ROE 3 ans capte la stabilité structurelle (moat). Le ROIC TTM capte l'efficacité capitale courante sans appel FMP supplémentaire (`roicTTM` est dans `key-metrics-ttm`, déjà récupéré). La pondération 60/40 favorise l'historique long sur la performance récente.
- Les **gates d'exclusion** (ROE < 0, ROE absent) s'appliquent sur le `roe_3y` brut, pas sur le composite — le composite est uniquement pour le classement.
- Si `ROIC_TTM` est absent, fallback sur `roe_3y` seul (comportement v1.0).

## Momentum Ajusté à la Volatilité (v1.1)

Formule : `perf_6m / écart_type_journalier_6M` (Daniel & Moskowitz, 2016).

- Justification : Le momentum brut surexpose au Momentum Crash — actifs en hausse parabolique (momentum élevé + volatilité élevée) s'effondrent brutalement lors des retournements. Diviser par la volatilité récompense les tendances régulières, pénalise les hausses spéculatives.
- Plancher de volatilité : `0.0005` (0.05% sigma journalier) pour éviter la division par quasi-zéro.
- Quand `momentum_adj` est disponible, il remplace le classement brut de `perf_6m` dans le calcul du score — les pondérations déclarées (30%) restent inchangées.

## Pondération Inverse-Volatilité Top 10 (v1.1)

Chaque signal Top 10 reçoit un champ `suggested_weight_pct` calculé comme `(1/σ_i) / Σ(1/σ_j) × 100`.

- `σ` = écart-type des rendements journaliers sur 63 jours de bourse.
- Informatif uniquement — ne modifie pas le classement. Permet au trader d'équilibrer le risque du portefeuille.
- Justification : L'équipondération surexpose aux titres les plus nerveux. L'inverse-volatilité est le schéma de pondération le plus simple qui réduit mécaniquement cette exposition sans biais de momentum.

## Gates de Qualité (Filtres d'Exclusion)

Ces règles sont **non-scorées** — elles éliminent avant le classement :

| Condition                    | Exclusion                                                                                               |
| ---------------------------- | ------------------------------------------------------------------------------------------------------- |
| ROE 3 ans indisponible (FMP) | Exclu — ROE TTM interdit (biaisé par effets exceptionnels)                                              |
| `book_value_per_share ≤ 0`   | Exclu — ROE mathématiquement sans sens                                                                  |
| ROE < 0%                     | Exclu — business structurellement défaillant                                                            |
| EBITDA ≤ 0                   | Exclu — dette/EBITDA sans sens                                                                          |
| Dette/EBITDA > 6x            | Exclu — risque bilan excessif                                                                           |
| **ROE > 150% avec BVS < 5$** | Non exclu mais score ROE **plafonné au percentile 80** + flag `⚠️ ROE possiblement gonflé par buybacks` |

## Secteurs Atypiques (Exceptions Obligatoires)

| Secteur                 | Exception                         | Raison                                     |
| ----------------------- | --------------------------------- | ------------------------------------------ |
| Financials              | Dette/EBITDA exclu du scoring     | Passif = dépôts clients                    |
| Real Estate             | Dette/EBITDA exclu du scoring     | FFO ≠ EBITDA GAAP                          |
| **Utilities**           | **Dette/EBITDA exclu du scoring** | Levier réglementé structurel (5-7x normal) |
| Health Care (cap < 5B$) | Gate P/E négatif suspendu         | Biotechs pré-revenus                       |

## Revue de Signal

Avant de valider un signal Top 10, vérifier :

1. **P/E Forward cohérent** avec le secteur ? (Tech : jusqu'à 80x acceptable, Industrials : > 25x suspect)
2. **Momentum 6M soutenu par surperformance sectorielle réelle** ? (surperf vs ETF SPDR — pas juste la perf absolue)
3. **Earnings dans les 14 prochains jours** ? → tag `📅 Earnings à venir` obligatoire (informatif, non bloquant)
4. **Surprise earnings date** : si > 90 jours, le signal est déjà intégré → poids réduit à zéro automatiquement
5. **Données FMP fraîches** ? > 365 jours → flag `⚠️ données potentiellement périmées` ; > 450 jours → exclu du classement (`data_freshness_warning_days` et `data_freshness_exclusion_days` dans `config.yaml`)
6. **Concentration sectorielle** : max 3 tickers par secteur (mode défensif par défaut)

## Ranking Intra-Secteur vs Cross-Universe

- **Valorisation** (P/E, EV/EBITDA) et **Marge opérationnelle** : ranking **intra-secteur GICS**
- **ROE, FCF Yield, Dette/EBITDA, Momentum** : ranking **cross-universe**
- **Exception** : si un secteur a < 3 tickers dans la shortlist scorée → bascule automatique en cross-universe pour ce secteur (ranking sur 1-2 tickers = biais statistique total)

## Checklist de Validation PR (Obligatoire)

Toute pull request touchant `scanner/scoring/`, `scanner/filters.py`, ou `scanner/market_gate.py` doit inclure ce checklist rempli dans la description de PR.

### Pondérations & Configuration

- [ ] Les pondérations dans le code utilisent `CONFIG["scoring"]["weights"]` — pas de valeurs hardcodées
- [ ] `config.yaml` et le code sont cohérents (Qualité 35%, Valorisation 30%, Momentum 35%)
- [ ] `shortlist_size` est toujours 30 — si modifié, budget FMP recalculé et documenté

### Gates & Exclusions

- [ ] Les gates d'exclusion ROE (< 0, absent, BVPS ≤ 0) s'appliquent sur `roe_3y` brut, pas le composite
- [ ] Le flag buyback (ROE > 150% + BVPS < 5$) est préservé
- [ ] EBITDA ≤ 0 et Dette/EBITDA > 6x → exclusion inconditionnelle préservée
- [ ] Exceptions sectorielles intactes (Financials/Immobilier/Utilities = pas de Dette/EBITDA ; Biotech < 5B$ = gate P/E suspendue)

### Séparation des Sources

- [ ] `yfinance` utilisé uniquement pour prix/OHLCV (+ fallback `roe_3y` si FMP retourne `[]`)
- [ ] Aucune nouvelle métrique fondamentale ajoutée depuis yfinance
- [ ] Budget FMP non dépassé : `shortlist_size × 5 endpoints ≤ 150` nominaux

### Market Gate

- [ ] La cascade de priorité est intacte : Panique (VIX > 35) → Prudence → Bear Light → Normal
- [ ] VIX évalué avant EMA200 (VIX = indicateur avancé)

### Justification Financière

- [ ] Tout nouveau seuil ou pondération a une justification financière documentée
- [ ] La validation Expert Trader est enregistrée dans ce fichier sous "Validation Complète des Stratégies"

## Validation Complète des Stratégies

_Dernière mise à jour : 2026-06-05_

### ROE composite (0.6 × ROE_3y + 0.4 × ROIC_TTM)

**Verdict** : ✅ Confirmée

**Justification** : Le ROE 3 ans filtre les entreprises à moat structurel (Buffett). Le ROIC TTM capte l'allocation de capital en temps réel. La pondération 60/40 favorise la durabilité sur la performance récente, cohérente avec l'horizon position trading 3-6 mois. Le ROIC est récupéré gratuitement dans `key-metrics-ttm`, sans appel FMP supplémentaire.

**Date** : 2026-06-05

---

### Momentum ajusté à la volatilité (perf_6m / σ_daily_6M)

**Verdict** : ✅ Confirmée

**Justification** : Daniel & Moskowitz (2016) démontrent que le momentum non ajusté génère des crashes périodiques. Diviser par la volatilité journalière 6M filtre les hausses spéculatives à haute volatilité. Résultat : favorise les tendances régulières (Quality Momentum) sur les bull runs instables. Plancher 0.05% σ = prévention division quasi-zéro sur actifs illiquides.

**Date** : 2026-06-05

---

### Pondération inverse-volatilité Top 10 (1/σ_63j)

**Verdict** : ✅ Confirmée — informatif uniquement

**Justification** : L'équipondération surexpose aux actifs les plus nerveux. L'inverse-volatilité est le schéma minimal qui réduit cette exposition mécaniquement. Le champ `suggested_weight_pct` est informatif — le trader garde la décision finale. Pas d'impact sur le classement.

**Date** : 2026-06-05

---

### Pénalités momentum extrême (-10 pts si perf_1m > +25%, -5 pts si < -20%)

**Verdict** : ✅ Confirmée

**Justification** : Perf 1M > +25% = probable surachat ou short squeeze — risque de retournement brutal dans la fenêtre de détention 3-6M. Perf 1M < -20% = pression de vente active non résolue — le signal momentum 6M peut être un "dead cat bounce". Les seuils sont conservateurs par rapport à la littérature (±30% typique) car l'univers est filtré sur liquidité institutionnelle (Cap > 2B$).

**Date** : 2026-06-05

---

### Market Gate — priorité VIX sur EMA200

**Verdict** : ✅ Confirmée

**Justification** : Cas empirique mars 2020 — VIX à 40-80 quand le SPY était encore au-dessus de son EMA200. L'EMA200 est un indicateur retardé de 2-3 semaines sur 252 jours de données. Le VIX est la mesure de panique systémique en temps réel. Ne pas déclencher Panique sur VIX > 35 à cause de l'EMA200 serait une erreur de type "lag bias".

**Date** : 2026-06-05

---

### Fraîcheur des données FMP (warning 365j, exclusion 450j)

**Verdict** : ✅ Confirmée

**Justification** : Les bilans annuels sont publiés tous les 12 mois. Un délai de 365j de tolérance permet de couvrir les entreprises dont le dernier trimestre FMP est légèrement en retard. 450j (15 mois) est la limite réelle au-delà de laquelle les données bilancières ont subi au moins 1 exercice complet non reflété — le scoring Qualité devient non fiable.

**Date** : 2026-06-05

---

### Plafond sectoriel shortlist (shortlist_sector_cap = 5)

**Verdict** : ✅ Confirmée

**Justification** : Sans plafond, un secteur surperformant (ex. semi-conducteurs en 2023-2024) peut accaparer 15-20 des 30 slots shortlist, privant le Sniper de diversité sectorielle pour le scoring final. 5 tickers/secteur = diversification minimale tout en permettant au secteur dominant d'être représenté.

**Date** : 2026-06-05
