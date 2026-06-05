# Feature Specification: Mise à Jour Documentation & Validation Trader Expert

**Feature Branch**: `009-doc-update-trader-validation`

**Created**: 2026-06-05

**Status**: Draft

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Documentation synchronisée avec le code (Priority: P1)

Un développeur qui reprend le projet après une pause peut comprendre l'état exact du système en lisant la documentation sans avoir à fouiller le code source.

**Why this priority**: La documentation est en retard sur le code. Le README décrit des pondérations et comportements qui ont évolué (ROE composite, momentum ajusté volatilité, poids inverse-volatilité, market gate). Un développeur ou un agent IA qui lit la doc obtient une image incorrecte du système.

**Independent Test**: Donner la documentation seule à un développeur inconnu du projet — il doit pouvoir décrire le comportement exact du scoring (pondérations, gates, règles d'exclusion) sans avoir à lire le code.

**Acceptance Scenarios**:

1. **Given** un développeur lit le README, **When** il vérifie les pondérations des 3 piliers, **Then** il trouve exactement : Qualité 40%, Momentum 40%, Valorisation 20% (ou les valeurs config.yaml actuelles)
2. **Given** un agent IA consulte `trader.md`, **When** il cherche les règles du Market Gate, **Then** les 4 régimes décrits correspondent exactement au comportement de `market_gate.py`
3. **Given** un développeur lit `specs/contracts/spec.md`, **When** il vérifie le calcul ROE, **Then** il trouve la formule composite (0.6 × ROE_3y + 0.4 × ROIC_TTM) et non le ROE TTM pur

---

### User Story 2 — Stratégies validées par l'expert trader (Priority: P1)

Chaque stratégie implémentée dans le code a été examinée par l'expert trader, qui confirme, infirme ou ajuste avec justification financière documentée.

**Why this priority**: Des stratégies incorrectes ou sous-optimales peuvent générer des faux signaux et des pertes. La validation expert garantit que le code fait ce que la théorie financière recommande, et documente les décisions pour référence future.

**Independent Test**: Prendre n'importe quelle règle métier du code (ex: seuil Dette/EBITDA > 6x, decay earnings 90j, cap buyback percentile 80) — une justification financière claire doit exister dans la documentation.

**Acceptance Scenarios**:

1. **Given** l'expert trader examine le scoring Qualité, **When** il analyse le ROE composite (0.6 × ROE_3y + 0.4 × ROIC_TTM), **Then** il valide ou propose une pondération alternative avec justification académique ou pratique
2. **Given** l'expert trader examine le Momentum, **When** il analyse la pénalité -10 pts si perf_1m > 25%, **Then** il confirme ou corrige le seuil avec référence au momentum crash risk (Daniel & Moskowitz 2016)
3. **Given** l'expert trader examine le market gate, **When** il analyse la priorité VIX vs EMA200, **Then** il confirme la logique (VIX = signal avancé vs EMA200 = laggard) et documente les edge cases connus
4. **Given** l'expert trader examine les exceptions sectorielles, **When** il vérifie Biotech / Financials / Real Estate / Utilities, **Then** il confirme chaque exception avec une justification sectorielle spécifique

---

### User Story 3 — Instructions agent mises à jour pour prévenir régressions (Priority: P2)

Quand un agent Claude Code travaille sur ce projet, les instructions CLAUDE.md et les rôles `.agents/roles/` lui donnent assez de contexte pour éviter les erreurs fréquentes et les régressions connues.

**Why this priority**: Plusieurs bugs ont été corrigés en boucle (5 bugs relecture trader, 10 bugs code-review, 11 bugs multi-agents, 7 bugs récents). Les instructions agents doivent capturer les règles anti-régression pour que ces bugs ne reviennent pas.

**Independent Test**: Décrire à un agent Claude Code vierge une tâche de modification du scoring — il doit citer les règles critiques (yfinance = prix seulement, FMP = fondamentaux, shortlist 30 non-négociable, ruff avant commit) sans avoir besoin de les chercher dans le code.

**Acceptance Scenarios**:

1. **Given** un agent lit CLAUDE.md, **When** il veut modifier le fetcher.py, **Then** il sait que yfinance est interdit pour les données fondamentales (bilanciel) et que FMP est la source unique
2. **Given** un agent lit `.agents/roles/trader.md`, **When** il examine une PR qui modifie les seuils de scoring, **Then** il demande une justification financière avant de valider
3. **Given** un agent lit les instructions de déploiement, **When** il prépare un commit, **Then** il exécute ruff check + format avant git add (ordre correct)

---

### User Story 4 — Checklist de revue trader pour chaque PR (Priority: P2)

Avant de merger une PR qui touche le scoring, les filtres ou le market gate, un checklist de validation trader est consulté et complété.

**Why this priority**: Les régressions surviennent quand des changements techniques sont faits sans vérifier l'impact sur la logique financière. Un checklist oblige à vérifier les invariants critiques.

**Independent Test**: Simuler une PR qui modifie les pondérations Qualité/Momentum — le checklist doit couvrir tous les cas critiques (cohérence config.yaml, exceptions sectorielles, gates d'exclusion).

**Acceptance Scenarios**:

1. **Given** une PR modifie le scoring engine, **When** le trader expert l'examine, **Then** il consulte un checklist qui inclut : cohérence pondérations config.yaml / code, règles gates inchangées, exceptions sectorielles vérifiées
2. **Given** une PR ajoute un nouvel indicateur, **When** le trader expert l'examine, **Then** le checklist demande : référence académique ou pratique, comportement sur secteurs atypiques, impact sur le budget FMP

---

### Edge Cases

- Que se passe-t-il si `config.yaml` et le code source ont des pondérations divergentes ?
- Comment documenter une stratégie dont la justification est empirique (backtestée) plutôt qu'académique ?
- Que faire si l'expert trader infirme une stratégie déjà en production — processus de dépréciation progressive ?
- Comment maintenir la synchronisation doc/code au fil des commits suivants (prévenir la redérive) ?

---

## Requirements *(mandatory)*

### Functional Requirements

**FR-001**: La documentation principale (README.md) DOIT refléter exactement les pondérations actuelles du scoring (Qualité 40%, Momentum 40%, Valorisation 20%) et les détails des sous-indicateurs tels qu'implémentés dans `config.yaml` et `scanner/scoring/`.

**FR-002**: Le fichier `specs/contracts/spec.md` DOIT être mis à jour pour documenter le ROE composite (0.6 × ROE_3y + 0.4 × ROIC_TTM), le momentum ajusté volatilité (Daniel & Moskowitz 2016), le decay earnings linéaire 90j, et les poids inverse-volatilité du Top 10.

**FR-003**: Le rôle `.agents/roles/trader.md` DOIT contenir une section "Validation Complète des Stratégies" avec, pour chaque règle métier critique : description exacte, justification financière, décision (confirmée/corrigée/infirmée), et date de validation.

**FR-004**: `CLAUDE.md` DOIT inclure une section "Règles Anti-Régression" listant les invariants critiques que tout agent doit respecter avant toute modification (yfinance = prix uniquement, FMP = fondamentaux, SHORTLIST_SIZE = 30, budget FMP ≤ 175 calls).

**FR-005**: `.agents/roles/trader.md` DOIT inclure un checklist de revue PR applicable à toute modification touchant scoring, filtres, ou market gate.

**FR-006**: `AGENTS.md` DOIT décrire le workflow de validation à 3 niveaux (Trader → Lead Dev → PO) avec les critères de blocage pour chaque niveau.

**FR-007**: Les règles de l'expert trader DOIVENT couvrir au minimum : ROE composite, momentum ajusté volatilité, market gate 4 niveaux, exceptions sectorielles (Financials/Real Estate/Utilities/Biotech), gates d'exclusion qualité, decay earnings, poids inverse-volatilité.

**FR-008**: La documentation DOIT distinguer clairement les comportements configurables via `config.yaml` (pondérations, seuils modifiables) des règles hardcodées non-négociables (SHORTLIST_SIZE, budget FMP, source yfinance/FMP).

### Key Entities

- **Stratégie documentée** : règle métier avec justification financière, seuil, comportement sur exceptions sectorielles, statut de validation (confirmée/infirmée/sous-réserve)
- **Invariant critique** : règle non-négociable dont la violation entraîne soit une regression fonctionnelle, soit un dépassement de budget, soit un signal erroné
- **Checklist PR trader** : liste de vérification à exécuter avant chaque merge touchant le domaine financier
- **Document de référence** : fichier markdown (README, spec.md, trader.md, CLAUDE.md) avec son périmètre de responsabilité clairement défini

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

**SC-001**: 100% des stratégies implémentées dans `scanner/scoring/` et `scanner/filters.py` ont une entrée de validation dans `trader.md` (confirmée ou corrigée avec justification).

**SC-002**: Zéro divergence entre les pondérations documentées dans README/spec.md et les valeurs dans `config.yaml` + le code source.

**SC-003**: Un agent Claude Code fraîchement initialisé, après lecture seule de CLAUDE.md et `.agents/roles/trader.md`, cite spontanément au moins 4 invariants critiques avant toute modification du scoring.

**SC-004**: Le taux de régressions sur les règles métier (gates, exclusions, pondérations) est de 0 sur les 3 PRs suivant la mise à jour des instructions.

**SC-005**: Toute PR touchant scoring/filtres/market gate est accompagnée d'un checklist trader rempli, visible dans la description de PR.

---

## Assumptions

- Les pondérations actuelles (Qualité 40%, Momentum 40%, Valorisation 20%) sont celles de `config.yaml` — elles peuvent différer du README actuel qui mentionne encore 35%/35%/30%
- L'expert trader est le rôle IA défini dans `.agents/roles/trader.md`, pas un humain externe
- La validation "infirme une stratégie" ne supprime pas le code en production immédiatement — elle ouvre une issue documentée pour décision ultérieure
- `specs/contracts/spec.md` reste la source de vérité principale ; README est la version vulgarisée
- Le périmètre ne couvre pas la mise à jour des tests unitaires (couverture test = sujet séparé)
- La synchronisation future doc/code n'est pas automatisée dans cette itération — elle repose sur le workflow de revue PR mis à jour
