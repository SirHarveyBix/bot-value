# Tasks: Mise à Jour Documentation & Validation Trader Expert

**Feature Branch**: `009-doc-update-trader-validation`

**Input**: Design documents from `specs/009-doc-update-trader-validation/`

**Références** :
- Spec : `specs/009-doc-update-trader-validation/spec.md`
- Constitution : `.specify/memory/constitution.md` (v1.3.0)
- Rôle trader : `.agents/roles/trader.md`
- Instructions agent : `CLAUDE.md`

## Format: `[ID] [P?] [Story] Description`

- **[P]** : Peut s'exécuter en parallèle (fichiers différents, pas de dépendances)
- **[Story]** : User story correspondante (US1..US4)
- **[x]** : Tâche complétée dans la session courante (2026-06-05)

---

## Phase 1 : Exploration (Prérequis Bloquant)

**Objectif** : Comprendre l'écart entre code et documentation avant toute modification.

- [x] T001 Lire `scanner/scoring/engine.py`, `quality.py`, `momentum.py`, `valuation.py`, `config.yaml` pour identifier toutes les divergences doc/code
- [x] T002 Lire `scanner/filters.py` pour lister toutes les règles non documentées (sanity_check_gate, earnings_calendar_check, data_freshness_check, check_data_ratio)
- [x] T003 Lire `README.md`, `.agents/roles/trader.md`, `CLAUDE.md`, `.specify/memory/constitution.md` pour identifier les sections obsolètes

**Checkpoint** : Liste des divergences établie → toutes les phases suivantes peuvent commencer.

---

## Phase 2 : US1 — Documentation synchronisée avec le code (P1)

**Objectif** : Tout document de référence décrit exactement le comportement du code en production.

**Test indépendant** : Un développeur qui lit uniquement README + trader.md + constitution peut décrire correctement les pondérations, les gates, et les règles d'exclusion sans consulter le code.

### Implémentation US1

- [x] T004 [P] [US1] Mettre à jour `README.md` — section Stratégie (pondérations 35%/30%/35%, ROE/ROIC composite, momentum ajusté volatilité, poids inverse-volatilité, budget FMP 175)
- [x] T005 [P] [US1] Mettre à jour `.specify/memory/constitution.md` vers v1.3.0 — corriger fraîcheur données 120/180→365/450, documenter ROE composite, momentum ajusté, inverse-vol, exit rules
- [x] T006 [P] [US1] Mettre à jour `.specify/templates/plan-template.md` — Constitution Check ligne II (freshness 365/450), ligne V (momentum ajusté volatilité), ligne VII (exit rules), ajouter lignes IX/X/XI
- [x] T007 [US1] Vérifier `specs/spec.md` — confirmer que ROE composite, momentum ajusté volatilité, poids inverse-vol sont déjà documentés (v1.1) — aucun changement requis
- [ ] T008 [US1] Ajouter section explicite dans `CLAUDE.md` et `trader.md` distinguant comportements **configurables** (`config.yaml`) vs **hardcodés non-négociables** (shortlist_size=30, séparation yfinance/FMP)

**Checkpoint US1** : Zéro divergence entre pondérations documentées et `config.yaml`. Vérifiable par `grep -r "35%\|30%\|40%\|20%" README.md trader.md`.

---

## Phase 3 : US2 — Stratégies validées par l'expert trader (P1)

**Objectif** : Toute règle métier du code a une validation documentée (confirmée/corrigée/infirmée) avec justification financière.

**Test indépendant** : Prendre n'importe quel seuil dans le code (`scanner/scoring/`, `scanner/filters.py`) → la section "Validation Complète des Stratégies" de `trader.md` a une entrée correspondante.

### Implémentation US2

- [x] T009 [P] [US2] Ajouter section "Validation Complète des Stratégies" à `.agents/roles/trader.md` avec entrées pour : ROE composite, momentum ajusté volatilité, inverse-vol, pénalités momentum, Market Gate priorité VIX, fraîcheur données, plafond sectoriel shortlist
- [ ] T010 [P] [US2] Ajouter entrées de validation manquantes dans `.agents/roles/trader.md` pour : `sanity_check_gate` (-45%/+50% daily return exclusion), `earnings_calendar_check` (fenêtre 14j informatif), `check_data_ratio` (min_valid_data_ratio=0.60)
- [ ] T011 [P] [US2] Ajouter entrée de validation dans `.agents/roles/trader.md` pour : P/E Forward seuils sectoriels (50x standard, 80x Tech/Healthcare, gate P/E négatif suspendu Biotech < 5B$)
- [ ] T012 [US2] Vérifier SC-001 : cross-checker `scanner/scoring/` + `scanner/filters.py` vs section "Validation Complète des Stratégies" — confirmer 100% de couverture

**Checkpoint US2** : Chaque fonction de `scanner/scoring/` et `scanner/filters.py` qui implémente une règle métier a son entrée dans `trader.md`.

---

## Phase 4 : US3 — Instructions agent anti-régressions (P2)

**Objectif** : Un agent Claude Code vierge qui lit uniquement `CLAUDE.md` et `trader.md` cite spontanément ≥ 4 invariants critiques avant toute modification du scoring.

**Test indépendant** : Décrire à un agent fraîchement initialisé une modification du fetcher.py — il cite les règles yfinance/FMP, shortlist=30, ruff avant commit, branche obligatoire.

### Implémentation US3

- [x] T013 [P] [US3] Ajouter section "Règles Anti-Régressions" à `CLAUDE.md` — séparation yfinance/FMP, budget FMP, interdiction hardcoding pondérations, table des gates d'exclusion, checklist trader avant merge, branche obligatoire
- [x] T014 [P] [US3] Ajouter Principe XI à `.specify/memory/constitution.md` — invariants anti-régressions pour agents IA
- [ ] T015 [US3] Mettre à jour `AGENTS.md` — enrichir section "Workflow de Validation" avec critères de blocage explicites par niveau (Trader : pertinence financière — bloque si seuil/pondération modifié sans justification ; Lead Dev : intégrité technique — bloque si budget FMP dépassé ou séparation yfinance/FMP violée ; PO : conformité architecture — bloque si entonnoir Chalutier/Sniper altéré)

**Checkpoint US3** : `AGENTS.md` et `CLAUDE.md` donnent à un agent les informations suffisantes pour éviter les 7 classes de bugs récurrents (voir historique git).

---

## Phase 5 : US4 — Checklist PR trader (P2)

**Objectif** : Toute PR touchant scoring/filtres/market gate inclut un checklist trader rempli dans sa description.

**Test indépendant** : Simuler une PR modifiant une pondération dans `config.yaml` — le checklist couvre pondérations, gates, sources de données, Market Gate, justification financière.

### Implémentation US4

- [x] T016 [US4] Ajouter "Checklist de Validation PR" à `.agents/roles/trader.md` — 5 sections : pondérations/configuration, gates/exclusions, séparation des sources, market gate, justification financière
- [ ] T017 [US4] Vérifier que le checklist PR dans `trader.md` couvre explicitement les cas révélés par les bugs récurrents : hardcoding pondérations, yfinance pour données fondamentales, shortlist_size modifié sans recalcul budget, gate ROE sur composite vs brut

**Checkpoint US4** : Le checklist peut être copié-collé directement dans une description de PR sans modification.

---

## Phase 6 : Polish & Vérifications Finales

**Objectif** : Validation croisée de cohérence sur l'ensemble des documents.

- [ ] T018 [P] Vérification SC-002 : `grep -r "quality.*0\.\|momentum.*0\.\|valuation.*0\." README.md trader.md constitution.md` — confirmer cohérence avec `config.yaml` (Qualité 0.35, Valorisation 0.30, Momentum 0.35)
- [ ] T019 [P] Vérification FR-008 : Confirmer que `CLAUDE.md` et `trader.md` distinguent explicitement les constantes configurables (`config.yaml`) des invariants hardcodés (shortlist_size, séparation yfinance/FMP, ruff pre-commit)
- [ ] T020 Vérification finale des 8 FR : passer chaque FR-001 à FR-008 et confirmer implémenté ou documenter gap restant

---

## Dépendances & Ordre d'Exécution

### Dépendances entre phases

- **Phase 1 (Exploration)** : Aucune dépendance — commence immédiatement
- **Phase 2 (US1)** : Dépend Phase 1 — T004 à T008 peuvent s'exécuter en parallèle entre eux
- **Phase 3 (US2)** : Dépend Phase 1 — peut démarrer en parallèle avec Phase 2
- **Phase 4 (US3)** : Dépend Phase 1 — peut démarrer en parallèle avec Phases 2 et 3
- **Phase 5 (US4)** : Dépend Phase 3 (T009 requis avant T017)
- **Phase 6 (Polish)** : Dépend Phases 2, 3, 4, 5

### Tâches restantes (non complétées)

Ordre suggéré pour la session suivante :

1. T010 + T011 en parallèle (`trader.md` — entrées validation manquantes)
2. T008 (`CLAUDE.md`/`trader.md` — configurable vs hardcodé)
3. T015 (`AGENTS.md` — critères de blocage)
4. T012 (vérification couverture complète SC-001)
5. T017 (vérification checklist PR)
6. T018 + T019 en parallèle (vérifications finales)
7. T020 (validation FR complets)

---

## Exemple Exécution Parallèle (Phase 3)

```bash
# T010 et T011 peuvent s'exécuter ensemble (même fichier mais sections différentes):
T010: sanity_check_gate + earnings_calendar + data_ratio → .agents/roles/trader.md
T011: P/E seuils sectoriels + exception Biotech → .agents/roles/trader.md
```

---

## Stratégie d'Implémentation

### MVP (US1 + US2 seulement)

1. Compléter Phase 1 ✅
2. Compléter Phase 2 (US1) — T008 reste
3. Compléter Phase 3 (US2) — T010, T011, T012 restent
4. **STOP et VALIDER** : SC-001 (couverture 100%) et SC-002 (zéro divergence pondérations)
5. Livrer si critères US1/US2 satisfaits

### Livraison Complète

1. MVP ci-dessus → valider
2. Phase 4 (US3) — T015 reste
3. Phase 5 (US4) — T017 reste
4. Phase 6 (Polish) — T018, T019, T020
5. Commit final sur branche `009-doc-update-trader-validation`

---

## Statut

**Session 2026-06-05** :
- Tâches complétées : T001–T009, T013, T014, T016 (15 tâches)
- Tâches restantes : T008, T010, T011, T012, T015, T017, T018, T019, T020 (9 tâches)
- Blocage : Aucun — toutes les tâches restantes sont indépendantes

---

## Notes

- `[P]` = fichiers différents, pas de dépendances entre tâches marquées
- Chaque user story est testable indépendamment
- Pas de tests unitaires dans ce périmètre (documentation uniquement)
- `specs/spec.md` déjà à jour v1.1 — aucune modification requise
