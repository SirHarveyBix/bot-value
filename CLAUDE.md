<!-- SPECKIT START -->

For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan

<!-- SPECKIT END -->

## Principe de simplicité (NON-NÉGOCIABLE)

**Jamais d'overengineering. Jamais de redondances sauf nécessité explicite.**

- Pas d'abstractions prématurées : 3 lignes similaires sont mieux qu'une abstraction non justifiée
- Pas de feature flags, backward-compat shims, ou helpers "pour plus tard"
- Pas de gestion d'erreurs pour des cas impossibles — faire confiance aux garanties internes
- Pas de couches supplémentaires sans besoin prouvé
- Redondance autorisée uniquement si : résilience explicitement requise (ex: retry circuit-breaker), ou séparation de responsabilités impose duplication minimale

## Règles obligatoires avant chaque commit

**TOUJOURS exécuter le linter avant `git commit` :**

```bash
./venv/bin/ruff check --fix . && ./venv/bin/ruff format .
```

Le pre-commit hook exécute ruff automatiquement et bloque le commit si le code ne passe pas. Ne jamais utiliser `--no-verify`.

**Séquence commit correcte :**

1. `./venv/bin/ruff check --fix . && ./venv/bin/ruff format .`
2. `git add <fichiers modifiés par ruff>`
3. `git commit -m "..."`

## Règles Anti-Régressions (Invariants Critiques)

**Lire avant toute modification du scanner.**

### Séparation des sources de données (NON-NÉGOCIABLE)

- `yfinance` = **prix/OHLCV uniquement**
- `FMP` = **toutes les données fondamentales** (bilan, compte de résultat, ratios)
- Exception unique documentée : fallback yfinance pour `roe_3y` si FMP retourne `[]` (lacune plan gratuit) — voir `.specify/memory/constitution.md` Principe I

### Budget FMP (NON-NÉGOCIABLE)

- `shortlist_size = 30` est un plafond strict → 30 × 5 endpoints = 150 appels + 25 marge = **175 maximum/jour**
- Toute modification de `shortlist_size` requiert un recalcul du budget et un amendement de constitution

### Pondérations du scoring

- **Ne jamais hardcoder** des pondérations dans le code — utiliser `CONFIG["scoring"]["weights"]`
- Source de vérité : `config.yaml` → Qualité 35%, Valorisation 30%, Momentum 35%
- Toute modification de pondération requiert une validation Expert Trader dans `.agents/roles/trader.md`

### Gates d'exclusion qualité

Les règles suivantes sont **non-scorées** — elles éliminent avant le classement et ne doivent jamais être affaiblies sans validation trader :

| Condition                   | Comportement                                            |
| --------------------------- | ------------------------------------------------------- |
| `roe_3y < 0`                | Exclusion inconditionnelle                              |
| `roe_3y is None`            | Exclusion inconditionnelle                              |
| `book_value_per_share ≤ 0`  | Exclusion                                               |
| `EBITDA ≤ 0`                | Exclusion                                               |
| `dette_nette / EBITDA > 6x` | Exclusion                                               |
| `ROE > 150%` et `BVPS < 5$` | Non exclu — percentile ROE plafonné à 80 + flag buyback |

### Validation Expert Trader avant merge

Toute pull request touchant `scanner/scoring/`, `scanner/filters.py`, ou `scanner/market_gate.py` doit :

1. Inclure le checklist de validation trader dans la description de PR (voir `.agents/roles/trader.md`)
2. Avoir une entrée dans la section "Validation Complète des Stratégies" de `.agents/roles/trader.md`

### Branche feature obligatoire

Ne jamais committer directement sur `main`. Créer une branche : `git checkout -b NNN-nom-de-la-feature`
