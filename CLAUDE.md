# Règles du projet RADAR

## OPEN SOURCE FIRST — RÈGLE BINAIRE (NON NÉGOCIABLE)

Avant d'écrire du code pour une fonctionnalité, pose obligatoirement cette question :

> Existe-t-il déjà un projet open source fonctionnel qui fait cette fonctionnalité ou au moins 70 % de celle-ci ?

**SI OUI :**
- NE PAS recoder la fonctionnalité from scratch.
- Évaluer les meilleurs repos existants.
- Vérifier la licence.
- Prendre le meilleur candidat.
- L'intégrer, le forker ou l'adapter selon ce que sa licence autorise.
- Construire notre logique spécifique au-dessus.

**SI NON :** coder nous-mêmes.

### Seuil de décision

- ≥ 70 % de couverture + licence compatible + projet suffisamment maintenu → **RÉUTILISER**
- 40–70 % → **ÉVALUER** : réutiliser si l'adaptation est plus rapide que le développement from scratch
- < 40 % → **CODER**
- Fonction critique déjà mature dans un projet open source → **interdiction de la réimplémenter sans raison technique documentée**

### Règle de temps

- Intégrer/adapter prend **moins de la moitié** du temps de reconstruction → **intégration obligatoire**
- Le projet existant est plus complexe à intégrer que ce qu'il ferait économiser → **coder nous-mêmes**

### Domaines où "ne pas réinventer" s'applique particulièrement

Scraping, collecte X/Reddit, crawlers, RSS, recherche web, trend detection, velocity analysis, clustering, semantic dedup, classification, OSINT, notifications, scoring, historique, monitoring, scheduling, stockage.

Philosophie : assembler 5 excellents composants open source + écrire 1 000 lignes de logique propriétaire, plutôt que réécrire 20 000 lignes de composants déjà existants.

### Obligations légales — "open source" ≠ "copier n'importe quoi"

Toujours :
- vérifier la licence ;
- respecter les obligations de copyright/attribution ;
- conserver les notices nécessaires (NOTICE, headers, etc.) ;
- ne jamais supprimer les auteurs ou une mention de licence ;
- ne pas intégrer de code dont la licence est incompatible avec le projet.

### Process avant codage (grosses fonctionnalités)

```
FEATURE
→ SEARCH EXISTING OPEN SOURCE
→ COMPARE
→ CHECK LICENSE
→ ESTIMATE INTEGRATION TIME
→ DECIDE REUSE vs BUILD
→ puis seulement coder
```

Limite de temps de recherche : quelques minutes pour une petite fonctionnalité ; plus de temps seulement pour une brique importante. Ne jamais chercher indéfiniment "le repo parfait".

## Application spécifique au RADAR

Philosophie : `EXISTANT → RÉUTILISER` · `MANQUANT → ADAPTER` · `UNIQUE AU RADAR → CODER`
(jamais `EXISTANT → RECODER PENDANT 3 JOURS`)

Domaines à chercher en priorité en open source : social listening, trend detection, X/Twitter monitoring, Reddit monitoring, keyword velocity, semantic deduplication, clustering, opportunity detection, web crawling, RSS aggregation, notifications, scoring, OSINT, market intelligence, alerting, historical trend analysis.

Notre valeur ajoutée à coder nous-mêmes par-dessus les briques réutilisées : scoring, déduplication, vérification, early detection, velocity, saturation, "Before-TikTok" detection, historique, alertes.

Préférer les projets réellement fonctionnels et maintenus aux repos abandonnés ou démos marketing.

### Autonomie sur les dépendances

Ne pas demander d'autorisation pour chaque dépendance open source normale : faire la recherche, vérifier la licence, prendre la décision technique raisonnable. Mais ne pas ajouter de dépendances inutilement — le RADAR doit rester essentiellement notre intelligence/orchestration au-dessus des meilleurs composants existants, pas un empilement de dépendances.

### Avant de démarrer une grosse brique, fournir uniquement

- projet choisi
- lien GitHub
- ce qu'il apporte
- licence
- pourquoi réutiliser plutôt que coder

Puis implémenter.
