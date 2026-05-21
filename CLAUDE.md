<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->

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
