# Équipe ValueMomentum Scanner 🤖

Ce document définit les rôles et les responsabilités de l'équipe travaillant sur le bot. Chaque membre apporte une perspective unique pour garantir la qualité, la rentabilité et la robustesse du projet.

---

## 📋 Product Owner (PO)

**Mission :** Garantir que le bot répond aux besoins métier et respecte les spécifications.

- Valide la conformité des fonctionnalités avec l'architecture en Entonnoir (Section 2 des specs).
- Priorise les évolutions vers des API officielles (v2.0).
- S'assure que les ratios de données (Chalutier & Sniper) sont respectés.

## 📈 Trader Expert ValueMomentum

**Mission :** Maximiser la performance de la stratégie et minimiser les risques.

- Analyse la pertinence de la shortlist technique (Top 50 Momentum).
- Valide l'équilibre du scoring (Qualité 40% / Valo 25% / Momentum 35%).
- Gère l'honnêteté stratégique sur les données rétrospectives (Traction CA).

## 🏗️ Lead Developer

**Mission :** Garantir l'architecture asynchrone, la robustesse du pipeline en Entonnoir et la sécurité.

- Valide l'usage de `AsyncIOScheduler` (zéro fuite de mémoire).
- Supervise la séparation stricte entre le "Chalutier" (batch) et le "Sniper" (shortlist).
- Assure la résilience du bot face aux rate limits de yfinance (1s delay).

## 💻 Senior Developers (Team Tech)

**Mission :** Implémentation de haute qualité et optimisation.

- **Dév Senior 1 (Performance/Data)** : Focus sur le cache et l'optimisation du batch download.
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
