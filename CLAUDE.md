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
