# Équipe ValueMomentum Scanner 🤖

Ce document définit les rôles et les responsabilités de l'équipe travaillant sur le bot. Chaque membre apporte une perspective unique pour garantir la qualité, la rentabilité et la robustesse du projet.

---

## 📋 Product Owner (PO)

**Mission :** Garantir que le bot répond aux besoins métier et respecte les spécifications.

- Valide la conformité des fonctionnalités avec l'architecture en Entonnoir (Section 2 des specs).
- Supervise la qualité des données via l'API FMP (Sniper).
- S'assure que les ratios de données (Chalutier & Sniper) sont respectés.

## 📈 Trader Expert ValueMomentum

**Mission :** Maximiser la performance de la stratégie et minimiser les risques.

- Pilote le **Market Gate (SPY MA200)** pour protéger le capital.
- Valide les seuils de liquidité institutionnels (Cap 2B$, Volume 5M$).
- Analyse le **ROE 3 ans** pour confirmer le Moat structurel des entreprises.

## 🏗️ Lead Developer

**Mission :** Garantir l'architecture, la performance et l'intégrité des données.

- Assure la transition vers **SQLite** pour sécuriser le stockage concurrent.
- Supervise la séparation asynchrone (yfinance vs httpx).
- Valide l'exactitude du calcul ROE multi-années.

## 💻 Senior Developers (Team Tech)

**Mission :** Implémentation de haute qualité et optimisation.

- **Dév Senior 1 (Performance/Data)** : Focus sur l'intégration de l'API FMP pour le Sniper et l'optimisation du batch download yfinance.
- **Dév Senior 2 (Algorithmes)** : Focus sur le scoring asymétrique (Momentum technique vs Qualité fondamentale).
- **Dév Senior 3 (Système/Ops)** : Focus sur la résilience du scheduler et le déploiement PM2.

## 🐣 Beginner Developer

**Mission :** Apprentissage et maintenance de premier niveau.

- S'occupe de l'installation (venv, requirements).
- Effectue les tests de bout en bout (`python3 main.py --now`).
- Documente les procédures de redémarrage du service (PM2).

---

## 🤝 Workflow de Validation

Tout changement majeur doit être validé par :

1. Le **Trader** (pertinence financière).
2. Le **Lead Dev** (intégrité technique / async).
3. Le **PO** (conformité architecture funnel).
