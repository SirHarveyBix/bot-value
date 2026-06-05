<!--
SYNC IMPACT REPORT — 2026-06-05
Version change: 1.2.0 → 1.3.0 (MINOR: 3 nouveaux principes + corrections divergences code/doc)

Divergences corrigées (config.yaml vs constitution v1.2.0) :
- Principe II : fraîcheur données corrigée 120j → 365j (warning) et 180j → 450j (exclusion)
- Principe II : formule ROE composite documentée (0.6 × ROE_3y + 0.4 × ROIC_TTM) — était absente
- Principe V : momentum ajusté volatilité documenté (Daniel & Moskowitz 2016) — était absent
- Principe VII : règles de sortie portfolio documentées (exit_rank=15, exit_score=70, maturation=3j) — étaient absentes

Principes ajoutés :
- IX. Lisibilité & Interdiction des Abréviations — pas de variables/fonctions/messages cryptiques
- X. Validation Obligatoire Expert Trader — chaque règle métier validée avant merge
- XI. Règles Anti-Régressions Agents IA — invariants critiques pour les agents Claude Code

Templates mis à jour :
- ✅ .specify/memory/constitution.md (ce fichier)
- ✅ .specify/templates/plan-template.md — Constitution Check ligne II corrigée (freshness 365/450)
- ⏳ .agents/roles/trader.md — ajouter section "Validation Complète des Stratégies" + checklist PR
- ⏳ CLAUDE.md — ajouter section "Règles Anti-Régressions"
- ⏳ README.md — aligner pondérations avec config.yaml
- ⏳ specs/contracts/spec.md — documenter ROE composite, momentum ajusté volatilité, poids inverse-vol

Constants ajoutées :
- exit_rank_threshold (15), exit_score_threshold (70.0), maturation_days (3), earnings_window_days (14)

Historique des amendements précédents :
- v1.2.0 (2026-06-02) : ROE yfinance fallback + shortlist_sector_cap + Principe VIII Simplicity First
- v1.1.3 (2026-06-02) : Principe VIII ajouté (Simplicity First)
- v1.1.2 (2026-05-22) : BF-010 FMP budget + mode dégradé FMP free tier

Follow-up TODOs :
- Backtest framework (v1.1 roadmap) : validation hors-échantillon des signaux sur horizon 6 mois
- Si upgrade plan FMP : réactiver earnings-surprises + analyst-estimates, supprimer fallback yfinance
- Mettre à jour .agents/roles/trader.md avec checklist PR et section validation stratégies
-->

# ValueMomentum Scanner Constitution

<!-- Scanner quantitatif quotidien : Qualité, Valorisation, Momentum — Position Trading 3-6 mois -->

## Principes Fondamentaux

### I. Architecture en Entonnoir & Séparation Stricte FMP / yfinance

Le scanner DOIT fonctionner en deux étapes pour équilibrer l'échelle et la précision.

- **Étape 1 (Chalutier)** : Screening technique large (~700 tickers) en utilisant `yfinance` exclusivement pour les prix, volumes, et momentum (données OHLCV). `yfinance` NE DOIT PAS être utilisé pour des ratios ou métriques fondamentales, à l'exception du fallback `roe_3y` décrit ci-dessous.
- **Étape 1b (Plafond Sectoriel Shortlist)** : Après le classement momentum, avant l'Étape 2, appliquer `shortlist_sector_cap` (défaut 5) tickers maximum par secteur. Empêche la concentration sectorielle systématique (exemple : semi-conducteurs accaparant les 30 slots). Secteur lu depuis le cache `fundamentals`. Implémenté dans `filters.py::cap_sector_shortlist()`.
- **Étape 2 (Sniper)** : Analyse fondamentale approfondie sur une shortlist de exactement **`shortlist_size` = 30 tickers** via l'API officielle FMP. Cette valeur est non-négociable : 30 × 5 endpoints FMP = 150 appels nominaux + 25 de marge retry = **limite stricte 175** face à un quota de 250 appels/jour (BF-010). Dépasser 30 tickers requiert un audit budgétaire préalable.
- **Indisponibilité FMP** (clé manquante ou 5xx persistant après 2 retries) : Envoyer alerte Telegram `⚠️ Sniper FMP indisponible` et arrêter le scan. Pas de fallback — un signal sans aucune donnée FMP est pire qu'aucun signal.
- **Lacune Plan FMP** (endpoints IS/BS retournent `[]` sur le plan gratuit) : Ce n'est PAS un événement d'indisponibilité. Le fallback vers yfinance `get_income_stmt(pretty=False)` + `get_balance_sheet(pretty=False)` (annuel) est autorisé **exclusivement pour le calcul de `roe_3y`**. Toutes les autres métriques FMP (P/E, EV/EBITDA, ROIC, FCF, marges) restent `None` et sont gérées par la logique de fallback du moteur de scoring. Cette distinction est critique : le disjoncteur (5xx) et la lacune de plan (réponse `[]` vide) sont deux modes de défaillance distincts.
- Le fallback yfinance pour `roe_3y` est une exception documentée — PAS un précédent pour d'autres métriques.
- **Pipeline ETF** : Les ETF utilisent un pipeline de scoring **momentum uniquement** (Performance 6 mois 50% + Surperformance vs SPY 50%). Les ETF n'ont pas de P/E, ROE, ni bilan — formuler les signaux ETF comme "sous-évalué" est incorrect. Le cadrage correct est **rotation sectorielle momentum** (identifier les secteurs avec une accélération de prix). Les ETF à levier ou inverses DOIVENT être exclus par pattern de nom avant le scoring.

### II. Qualité & Stabilité (Le Fossé Concurrentiel)

Les signaux d'investissement DOIVENT reposer sur une qualité structurelle.

- **Formule ROE composite** : Le Retour sur Capitaux Propres utilisé dans le scoring est calculé comme `0.6 × ROE_3y + 0.4 × ROIC_TTM` lorsque les deux valeurs sont disponibles. Si `ROIC_TTM` est absent, le fallback est `roe_3y` seul. Cette formule combine la stabilité historique (ROE 3 ans) avec l'efficacité capitale courante (ROIC TTM) sans appel FMP supplémentaire.
- **Gates ROE** (appliquées sur `roe_3y` brut, pas le composite) : `roe_3y < 0` = exclusion inconditionnelle. `roe_3y is None` après FMP et fallback yfinance = exclusion inconditionnelle. `book_value_per_share ≤ 0` = exclusion (ROE mathématiquement indéfini). `ROE > 150%` avec `book_value_per_share < 5$` = score ROE plafonné au percentile 80 + flag `⚠️ ROE possiblement gonflé par buybacks` (levier par rachats d'actions, pas excellence opérationnelle).
- **Source du ROE** : Priorité (1) FMP `income-statement` + `balance-sheet-statement` sur 3 ans annuels ; (2) yfinance `get_income_stmt(pretty=False)` + `get_balance_sheet(pretty=False)` quand FMP retourne `[]` (lacune de plan). `yf.info["returnOnEquity"]` (TTM) n'est **jamais** autorisé comme source.
- **Exclusions dettes/EBITDA** : Financials (dépôts = passif ≠ dette normale), Immobilier (FFO ≠ EBITDA GAAP), et **Services aux Collectivités** (levier structurel réglementé 5-7x, non prédictif du risque) NE DOIVENT PAS inclure la dette/EBITDA dans le scoring Qualité. Pour ces secteurs, le pilier Qualité utilise 3 sous-critères : ROE, marge opérationnelle, rendement FCF.
- EBITDA ≤ 0 → exclusion inconditionnelle (ratio dette/EBITDA sans signification ; entreprise déficitaire). Dette nette / EBITDA > 6x → exclusion inconditionnelle (risque bilan excessif).
- **Fraîcheur des données fondamentales** : Les données de plus de 365 jours déclenchent un flag `⚠️ données potentiellement périmées`. Les données de plus de 450 jours entraînent une exclusion automatique du classement final. Ces seuils sont configurables via `data_freshness_warning_days` et `data_freshness_exclusion_days` dans `config.yaml`.
- Les tickers avec `sector = None` (GICS manquant) sont exclus du pipeline Actions — aucune comparaison intra-sectorielle n'est possible sans label sectoriel valide.

### III. Market Gate (Priorité Survie — Cascade en Priorité)

La préservation du capital est la priorité absolue. Le Market Gate DOIT évaluer les conditions dans un ordre de priorité strict (premier match gagne) :

1. **Panique** (Priorité 1) : `VIX > 35` — quelle que soit la position du SPY. Le scan DOIT être annulé. Alerte Telegram envoyée. Une entrée écrite dans la table `scans` avec `regime='panic'`. Aucune entrée écrite dans `signals`.
2. **Prudence** (Priorité 2) : `SPY < EMA200 ET VIX entre 25 et 35`. Le scan tourne. Chaque signal reçoit le flag `⚠️ RÉGIME DE PRUDENCE`.
3. **Bear Light** (Priorité 3) : `SPY < EMA200 ET VIX ≤ 25`. Le scan tourne normalement. Avertissement log interne uniquement — pas de flag sur les signaux Telegram.
4. **Normal** (Priorité 4) : `SPY ≥ EMA200 ET VIX ≤ 25`. Scan complet, émission de signaux sans restriction.

Le VIX prime sur l'EMA200 car le VIX est un indicateur avancé de panique ; l'EMA200 est un indicateur retardé de plusieurs semaines. Un crash en cours (VIX > 35) DOIT déclencher Panique même si le SPY n'a pas encore croisé sous son EMA200.

### IV. Liquidité Institutionnelle & Exécution

Pour garantir la négociabilité et minimiser le glissement de prix, le scanner NE DOIT considérer que des instruments de qualité institutionnelle.

- Seuils minimaux (appliqués quotidiennement avant le scoring) : Capitalisation boursière > 2 milliards de dollars, Volume Dollar Journalier Moyen (20 jours) > 5 millions de dollars, Prix > 5 dollars, Coté sur NYSE/NASDAQ/AMEX uniquement.
- L'univers est strictement américain en v1.0. Les tickers non-américains (par exemple suffixe `.NS`) NE DOIVENT PAS figurer dans `tickers_universe.json`.
- Les penny stocks, instruments OTC, et micro-caps peu liquides sont exclus inconditionnellement.

### V. Momentum Quantitatif (Le Catalyseur — 5 Sous-Critères)

La stratégie se concentre sur la convergence du momentum de prix et de l'accélération fondamentale :

- **Signaux primaires** (prix) : Performance 6 mois (30%) et surperformance sectorielle 6 mois vs benchmark SPDR (30%).
- **Calcul du momentum ajusté à la volatilité** (Daniel & Moskowitz 2016) : `perf_6m / écart_type_journalier_6M` où `écart_type_journalier_6M` est l'écart-type des rendements journaliers sur 126 jours de bourse. Un plancher de volatilité (`VOLATILITY_FLOOR = 0.0005`, soit 0.05% de sigma journalier) prévient la division par quasi-zéro. Lorsque disponible, ce ratio ajusté remplace le classement brut de `perf_6m` dans le calcul du score momentum, en préservant les pondérations déclarées. Justification : filtre les faux momentum sur actifs à très faible volatilité, favorise les mouvements de prix significatifs relativement au risque.
- **Signal confirmatoire** (prix) : Performance 3 mois (15%).
- **Accélération fondamentale — historique** (FMP) : Surprise Résultats % via `earnings-surprises` (15% de poids nominal, avec décroissance temporelle : poids → 0 linéairement sur 90 jours post-publication ; le poids libéré est redistribué proportionnellement aux 4 autres critères). **Mode dégradé — plan gratuit FMP** : `earnings-surprises` retourne HTTP 404 ; le critère score 0 pour tous les tickers (symétrique — le classement relatif est préservé). Le poids 15% est effectivement redistribué aux 3 autres critères prix à l'exécution.
- **Accélération fondamentale — prospective** (FMP) : Révisions estimations analystes 3 mois via `analyst-estimates` (10% de poids nominal, sans décroissance — les révisions reflètent une conviction soutenue). **Mode dégradé — plan gratuit FMP** : `analyst-estimates` retourne HTTP 402 ; le critère score 0 pour tous les tickers (symétrique). Le poids 10% est effectivement redistribué à l'exécution.
- Les extrêmes court terme DOIVENT être pénalisés : performance 1 mois > +25% → -10 pts sur le score momentum ; performance 1 mois < -20% → -5 pts.

### VI. Intégrité Sectorielle GICS

Le classement percentile intra-sectoriel est le fondement d'une comparaison de valorisation équitable (P/E, EV/EBITDA, marge opérationnelle).

- Source de vérité pour le label sectoriel : yfinance `.info["sector"]`. Les labels sectoriels FMP sont secondaires et peuvent diverger.
- Si `sector = None` : ticker exclu du scoring Actions (journalisé comme `sector_missing`).
- Si un secteur a **moins de 3 tickers** dans la shortlist scorée : ces tickers DOIVENT utiliser le classement cross-univers pour toutes les métriques intra-sectorielles. Un percentile intra-sectoriel sur 1-2 tickers est statistiquement inepte (le ticker unique obtient toujours le 100e percentile).
- **`min_universe_size` = 100 tickers** DOIT être vérifié sur **l'univers complet éligible après les filtres Chalutier** (avant la shortlist à 30). La shortlist est toujours ≤ 30 par conception — vérifier `min_universe_size` sur la shortlist échouera toujours. Si l'univers post-éligibilité (pré-shortlist) tombe sous 100, le classement percentile perd sa validité statistique et le scan DOIT être annulé.

### VII. Persistance des Signaux & Règles de Sortie Portfolio

Le modèle de scoring — pas le temps — décide quand un signal expire.

- `first_seen_date` dans SQLite n'est JAMAIS réinitialisé lorsqu'un ticker réapparaît dans le Top 10 après une absence. Il enregistre la date de signal originale pour la traçabilité historique.
- Les tickers présents 90+ jours consécutifs dans le Top 10 représentent un signal de conviction, pas un échec de rotation. Pas d'exclusion forcée par calendrier.
- Un ticker quitte le Top 10 uniquement lorsque son `score_global` tombe sous le 10e seuil dans l'univers classé.
- **Règles de sortie** : Un ticker en portfolio est étiqueté `exits_today` quand son rang dépasse `exit_rank_threshold` (défaut 15) OU que son `score_global` tombe sous `exit_score_threshold` (défaut 70.0). Ces seuils sont configurables dans `config.yaml`.
- **Cycle de maturité** : Un nouveau signal passe par 3 états : `ACHAT` (nouveau signal, jour 1), `MATURATION` (jours 2-3, pendant `maturation_days`), puis `HOLD` (signal confirmé, jours 4+). Cette progression donne au trader le contexte temporel sans forcer une action mécanique.

### VIII. Simplicité en Premier (NON-NÉGOCIABLE)

Tout code ajouté doit avoir un besoin prouvé. Pas de spéculation sur des besoins futurs.

- **Pas d'overengineering** : aucune abstraction, helper, ou pattern architectural sans cas d'usage immédiat démontré.
- **Pas de redondances** sauf si explicitement requises : résilience prouvée (exemple : circuit-breaker retry déjà en place), ou séparation de responsabilités qui impose une duplication minimale documentée.
- **YAGNI** (You Ain't Gonna Need It) : supprimer le code inutilisé plutôt que le commenter ou le garder "au cas où".
- Trois lignes similaires sont meilleures qu'une abstraction prématurée. Une abstraction ne se justifie que lorsque la quatrième occurrence identique apparaît, ou qu'un couplage fort le nécessite.
- Toute complexité ajoutée doit être justifiée dans le message de commit ou l'amendement de constitution.

### IX. Lisibilité & Interdiction des Abréviations

Le code, la documentation, et les messages Telegram DOIVENT être compréhensibles sans déchiffrage.

- **Noms de variables et de fonctions** : Utiliser des noms complets et descriptifs. Interdit : `sq`, `mv`, `dt`, `tmp`, `val`, `res`, `cfg`. Autorisé : `score_qualite`, `valeur_marche`, `date_publication`, `valeur_temporaire`, `configuration`.
- **Acronymes financiers standard autorisés** : ROE (Return on Equity), ROIC (Return on Invested Capital), FCF (Free Cash Flow), EPS (Earnings Per Share), P/E (Price-to-Earnings), EV (Enterprise Value), PEG (Price/Earnings-to-Growth), EBITDA, BVPS (Book Value Per Share), VIX (Volatility Index), EMA (Exponential Moving Average), ETF (Exchange-Traded Fund), FMP (Financial Modeling Prep), OHLCV (Open/High/Low/Close/Volume), GICS (Global Industry Classification Standard), SPY, NYSE, NASDAQ, AMEX, API (Application Programming Interface), URL (Uniform Resource Locator), TTM (Trailing Twelve Months).
- **Documentation** : Pas d'abréviations non-standard dans README, spec.md, trader.md, ou tout document de référence. "doc" → "documentation", "config" → "configuration" dans les titres de sections (mais `config.yaml` reste le nom du fichier).
- **Messages Telegram** : Les abréviations dans les messages envoyés à l'utilisateur DOIVENT être compréhensibles par un lecteur non-technique. Tags autorisés : `ROE`, `P/E`, `EMA200`, `VIX`. Tags à éviter : acronymes internes du code.
- **Commentaires de code** : Les commentaires DOIVENT expliquer le POURQUOI (contrainte cachée, invariant subtil, contournement de bug), pas le QUOI. Pas de blocs multi-lignes. Un commentaire qui redit ce que le nom de la fonction dit déjà doit être supprimé.

### X. Validation Obligatoire de l'Expert Trader

Toute règle métier doit être validée par le rôle Expert Trader avant d'être mergée.

- **Périmètre de validation** : Toute modification des pondérations des piliers (Qualité / Valorisation / Momentum), des sous-pondérations, des seuils de gates d'exclusion, des exceptions sectorielles, ou des seuils du Market Gate DOIT recevoir une validation documentée du rôle Expert Trader.
- **Format de validation** dans `.agents/roles/trader.md` : Chaque règle validée DOIT inclure : description exacte de la règle, verdict (Confirmée / Corrigée — avec proposition alternative / Infirmée — requiert rollback), justification financière (référence académique ou pratique de terrain), et date de validation.
- **Checklist de revue PR** : Toute pull request touchant `scanner/scoring/`, `scanner/filters.py`, ou `scanner/market_gate.py` DOIT inclure dans sa description un checklist trader rempli couvrant : cohérence pondérations `config.yaml` / code, règles de gates inchangées ou justifiées, exceptions sectorielles vérifiées, impact sur le budget FMP calculé.
- **En cas d'infirmation** : La stratégie infirmée ne déclenche pas de suppression immédiate en production — elle ouvre une issue documentée avec délai de dépréciation explicite (maximum 2 sprints).
- Le rôle Expert Trader est défini dans `.agents/roles/trader.md`. Ce rôle est endossé par un agent IA spécialisé ou un humain selon le contexte — la documentation de la validation est obligatoire dans les deux cas.

### XI. Règles Anti-Régressions pour Agents IA

Les agents Claude Code opérant sur ce projet DOIVENT respecter les invariants critiques suivants avant toute modification :

- **Séparation des sources de données** : `yfinance` = données prix/OHLCV uniquement. `FMP` = toutes les données fondamentales (bilan, compte de résultat, ratios). Toute exception DOIT être documentée dans ce document (voir Principe I, exception `roe_3y`).
- **Budget FMP non-négociable** : `shortlist_size = 30` est un plafond strict lié au budget FMP de 175 appels/jour. Toute modification doit déclencher un recalcul du budget.
- **Ordre d'exécution linter** : Toujours exécuter `./venv/bin/ruff check --fix . && ./venv/bin/ruff format .` AVANT `git add` et `git commit`. Le hook pre-commit bloque le commit si le code ne passe pas ruff — ne jamais utiliser `--no-verify`.
- **Tests d'intégration** : Tous les tests réseau DOIVENT utiliser des cassettes VCR.py. Aucun appel API réel par défaut.
- **Modification des pondérations** : Modifier uniquement dans `config.yaml`. Ne jamais hardcoder des pondérations dans le code source — utiliser `CONFIG["scoring"]["weights"]`.
- **Validation Expert Trader requise** : Avant tout merge touchant le scoring, les filtres, ou le market gate, consulter et compléter le checklist trader (voir Principe X).
- **Branche feature obligatoire** : Ne jamais committer directement sur `main`. Toujours créer une branche feature.

## Standards Techniques

### Contraintes Fondamentales

- **SQLite WAL** : Obligatoire pour les accès concurrents (bot en écriture + dashboard en lecture).
- **Asynchrone natif** : `asyncio` natif (APScheduler 4.x async) pour toutes les entrées/sorties, la planification, et les notifications. Pas de blocage synchrone dans la boucle d'événements.
- **Résilience API** : Délai avec gigue (0.8s–1.5s) entre tous les appels externes. FMP : 2 retries maximum (pattern circuit-breaker). yfinance : 3 retries avec backoff exponentiel.
- **Telegram** : Mode de parsing HTML. Toutes les données chaînes DOIVENT passer par `html.escape()` avant l'envoi. Les messages DOIVENT être tronqués à 4096 caractères maximum (limite API Telegram). Limite de débit : 1.5s entre les messages.

### Constantes Configurables (config.yaml — source de vérité)

| Constante                       | Défaut | Contrainte                                                       |
| ------------------------------- | ------ | ---------------------------------------------------------------- |
| `shortlist_size`                | 30     | Maximum strict 30 (budget FMP)                                   |
| `shortlist_sector_cap`          | 5      | Plage [3, 10] — max tickers/secteur dans la shortlist            |
| `vix_panic_threshold`           | 35     | Plage [30, 45]                                                   |
| `vix_warning_threshold`         | 25     | Plage [20, 30]                                                   |
| `max_tickers_per_sector`        | 3      | 10 = mode alpha-pur (risque) — filtre de scoring                 |
| `max_workers_universe`          | 4      | Maximum strict 6 (risque de bannissement IP yfinance)            |
| `fmp_max_retries`               | 2      | Maximum strict 2 (limite budgétaire 175 appels)                  |
| `min_universe_size`             | 100    | En dessous = scan annulé                                         |
| `telegram_max_chars`            | 4096   | Fixe (limite API)                                                |
| `data_freshness_warning_days`   | 365    | Plage [120, 500] — flag données périmées                         |
| `data_freshness_exclusion_days` | 450    | Plage [180, 730] — exclusion du classement                       |
| `earnings_window_days`          | 14     | Jours avant résultats → tag `📅 Earnings à venir`                |
| `exit_rank_threshold`           | 15     | Rang au-delà duquel un signal portfolio est étiqueté exits_today |
| `exit_score_threshold`          | 70.0   | Score en dessous duquel un signal est étiqueté exits_today       |
| `maturation_days`               | 3      | Jours en état MATURATION avant passage en HOLD                   |
| `fmp_call_budget_hard_limit`    | 175    | 30 × 5 endpoints = 150 nominaux + 25 marge retry (BF-010)        |

> **[2026-05-22 BF-010]** `fmp_call_budget_hard_limit` = 175. `earnings-surprises` et `analyst-estimates` retirés du plan gratuit FMP. Le Principe V fonctionne en mode dégradé symétrique (voir détail Principe V ci-dessus).

## Validation & Portes de Qualité

- **Tests d'intégration hermétiques** : Tous les tests d'intégration DOIVENT utiliser des cassettes `VCR.py`. L'enregistrement de première exécution requiert un opt-in explicite. Les tests NE DOIVENT PAS effectuer d'appels API réels par défaut.
- **Déterminisme temporel** : `Freezegun` est obligatoire pour toute logique sensible au temps (calendrier NYSE, fenêtres résultats, fraîcheur des données, décroissance surprise résultats).
- **Validation des données sans risque de None** : Toutes les données externes DOIVENT passer une validation protégée contre None avant d'entrer dans le moteur de scoring. Utiliser `data.get("cle")` avec vérification de valeur, jamais `"cle" in data` seul.
- **Surveillance budget FMP** : La suite de tests DOIT inclure un compteur d'appels simulés vérifiant qu'un run Sniper complet de 30 tickers reste dans 175 appels FMP (30 × 5 endpoints = 150 nominaux + 25 marge retry — BF-010).
- **Nommage des tests** : Les fonctions de test DOIVENT avoir des noms descriptifs complets (exemple : `test_quality_gate_excludes_negative_roe`, pas `test_qg_neg_roe`). Principe IX appliqué aux tests.

## Gouvernance

La Constitution du ValueMomentum Scanner est la source de vérité souveraine pour les décisions architecturales et stratégiques.

- **Résolution des conflits** : Toute implémentation qui viole l'Architecture en Entonnoir (Principe I), la cascade de priorité du Market Gate (Principe III), ou la séparation FMP/yfinance (Principe I) est une défaillance critique requérant un rollback immédiat.
- **Amendements** : Les modifications des pondérations principales, des seuils, ou du calcul du budget FMP DOIVENT être documentées avec leur justification financière, un bump de version, et la date d'amendement ajoutée à la table des Constantes. Les modifications des Principes I à VII requièrent également une validation Expert Trader (Principe X).
- **Alignement des Specs** : `specs/contracts/spec.md` est la référence d'implémentation authoritative. Les principes de la Constitution prévalent toujours sur les détails des specs en cas de conflit. Les mises à jour des specs qui introduisent des contradictions avec cette Constitution DOIVENT déclencher un amendement de Constitution.
- **Cadence de révision** : La Constitution DOIT être relue et synchronisée avec le code source à chaque changement significatif (nouveau pilier de scoring, modification des pondérations, nouvelles règles d'exclusion). Le rapport de synchronisation dans l'en-tête HTML DOIT lister toutes les divergences corrigées.

**Version** : 1.3.0 | **Ratifiée** : 2026-05-18 | **Dernier Amendement** : 2026-06-05
