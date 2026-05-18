# Expression de Besoin : Moteur de Screening Quantitatif "ValueMomentum"

### Vision Stratégique du Trader

Je ne cherche pas un gadget d'analyse technique ni un scanner intraday pour générer des alertes de scalping bruyantes. Mon besoin est la construction d'un **moteur de screening institutionnel automatisé**, conçu pour le Position Trading (horizon 2 à 8 mois).

L'objectif est d'extraire mécaniquement l'Alpha du marché en identifiant la convergence exacte entre la **Qualité fondamentale intrinèque** d'une entreprise et l'**Accélération de son prix (Momentum)**. Ce système doit tourner de manière autonome et asynchrone en environnement local, sans jamais sacrifier la fiabilité des données au profit de la quantité. Si le marché est en régime de panique, le système doit me l'indiquer et couper les signaux acheteurs. La préservation du capital prime sur le rendement.

---

### Évaluation Absolue des Actifs (La Logique Cœur)

Un actif financier n'est pas jugé sur la composition actuelle de mon portefeuille, mais sur ses mérites intrinsèques stricts :

- **Survie et Qualité :** Une entreprise qui détruit de la valeur (ROE < 0) ou qui est surendettée (Dette/EBITDA > 6x) est disqualifiée d'office, peu importe son action de prix.
- **Valorisation :** L'actif doit présenter une asymétrie de valorisation (P/E et PEG rationnels vis-à-vis de son secteur).
- **Catalyseur (Momentum) :** Une action fondamentalement sous-évaluée peut le rester des années (Value Trap). L'entrée en position n'est justifiée que si un Momentum fort (sur 3 à 6 mois) valide que le flux de capitaux institutionnels est déjà en train de se positionner.

---

### Contraintes Non Négociables : L'Entonnoir d'Acquisition des Données

En tant que trader quantitatif, ma matière première est la donnée. Or, les données gratuites sont corrompues et les données institutionnelles sont coûteuses et limitées en volume. L'architecture doit donc impérativement suivre une logique d'entonnoir asymétrique pour garantir la viabilité du bot sans exploser les quotas.

| Critères                        | Phase 1 : Le Chalutier (`yfinance`)                                                                        | Phase 2 : Le Sniper (API FMP)                                                                               |
| :------------------------------ | :--------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------- |
| **Rôle**                        | Filtrage massif de liquidité et calcul du momentum prix.                                                   | Extraction chirurgicale des métriques bilancielles.                                                         |
| **Cible & Volume**              | Univers large (~700 à 1000 tickers).                                                                       | Shortlist stricte (Top 50 maximum).                                                                         |
| **Avantages**                   | Gratuit, excellent pour l'OHLCV (prix/volumes) et le calcul des rendements relatifs.                       | Qualité institutionnelle, données auditées, pas de valeurs aberrantes sur les ratios.                       |
| **Inconvénients (Contraintes)** | **Instable**. Scraping agressif interdit. Données fondamentales (P/E, FCF) souvent manquantes ou erronées. | **Quotas stricts**. Appels limités (ex: 250/jour selon le tier). Interdiction de requêter l'univers entier. |
| **Risques potentiels**          | Bannissement IP immédiat (Erreur 429) si absence de _rate limiting_ ou de requêtes asynchrones espacées.   | Épuisement du quota API en cas de boucle infinie ou de mauvaise gestion du cache local.                     |
| **Vecteur de temps**            | Quotidien, nécessite un "jitter" (délai aléatoire) entre chaque requête.                                   | Quotidien, uniquement sur les survivants de la Phase 1. Mise en cache des données sur 24h.                  |

> **Synthèse de la Règle d'Or :** `yfinance` est utilisé _exclusivement_ pour regarder le comportement du marché (prix, volume, momentum, dates d'earnings). Dès qu'il s'agit de lire le bilan comptable d'une entreprise pour valider sa viabilité, le système doit basculer sur **FMP**. Toute tentative de calculer un ROE ou un FCF via `yfinance` est un non-sens absolu qui invalide la stratégie.

---

### Analyse d'Impact Bifurquée (Déploiement Structurel)

Pour que ce système soit résilient au quotidien depuis le serveur local, la structuration de l'architecture implique deux niveaux d'impact à maîtriser d'emblée.

**Vecteur Court Terme (Fiabilité et Exécution) :**

- **Concurrence Asynchrone :** L'utilisation de threads pour `yfinance` couplée à l'asynchronisme natif d'API FMP et de Telegram (via `APScheduler`) est critique. Le moindre blocage synchrone fera rater la fenêtre de scan ou plantera l'Event Loop, rendant le rapport quotidien caduc.
- **Gestion des Erreurs :** Les API tierces vont inévitablement échouer (timeouts, 502, etc.). Le système doit implémenter un backoff exponentiel silencieux et ne jamais crasher. Un ticker sans données est ignoré, le reste du scan doit survivre.

**Incidence Long Terme (Scalabilité et Historisation) :**

- **Rotation Stratégique :** Le stockage via SQLite (en mode WAL) permettra de conserver une trace indélébile des scores générés. À terme, cela nous offrira la capacité de backtester nos propres signaux "out-of-sample" pour vérifier si le top 10 généré aujourd'hui surperforme réellement le SPY dans 6 mois.
- **Indépendance aux Fournisseurs :** Si la structure HTML de Yahoo Finance évolue et casse le wrapper `yfinance`, la couche "Chalutier" doit pouvoir être interchangée (vers AlphaVantage ou un autre flux) avec un minimum de refactoring. Le code métier (Scoring Engine) doit être strictement découplé du code d'acquisition (Data Fetcher).
