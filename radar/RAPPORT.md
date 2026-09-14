# RAPPORT — Reprise en main complète de RADAR (cry4radar)

**Date :** 2026-09-14
**Portée :** audit, red-team, corrections, durcissement, tests, validation en conditions réelles.
**Principe directeur appliqué :** *réutiliser ce qui est résolu, ne coder que ce qui est propre au radar* — et **ne jamais simuler la qualité** (tout ce qui est affirmé ici a été exécuté, la sortie est dans ce document).

> Note : ce rapport décrit un travail d'ingénierie mesuré. Là où je n'ai pas fait quelque chose, je le dis explicitement plutôt que de le maquiller.

---

## 1. Méthode (phases 0 → 12)

| Phase | Ce qui a été fait |
|---|---|
| 0 — Compréhension | Lecture intégrale du dépôt : 20 modules `radar/signals/*`, `run.py`, `telegram_listener.py` (26 Ko), les 12 fichiers de tests, README/NOTICE/CLAUDE.md. Cartographie de l'architecture et des flux. |
| 0 bis — Environnement | `.venv` Python 3.12, `pip install -r requirements.txt`, exécution de la suite : **69 tests passent** (ligne de base). |
| 1 — Recherche | Recherche web ciblée : exigences du hackathon First Commit, écosystème OSS de notification (Apprise/ntfy), littérature « alert fatigue ». Voir §7. |
| 2 — Benchmark | Comparaison du comportement réel du radar aux standards du genre (dédup, filtrage avant notification, identité cross-run). |
| 3 — Décision | Priorisation : **correction > robustesse > durcissement > hygiène**, en évitant tout ce qui relève du « slop » (voir §9). |
| 4 — Build | Corrections implémentées + tests de régression, un correctif à la fois, chaque fois revérifié. |
| 5 — Red team | Fuzzer la chaîne complète (1 500 lots aléatoires/malformés) + sondage de cas limites. |
| 6 — Test utilisateur simulé | Run réel de bout en bout sur les sources réseau, plus second run pour l'identité cross-run. |
| 7 — Polish | Commentaires/docstrings mis à jour pour refléter le *pourquoi* réel de chaque correctif. |
| 8 — Qualité technique | Audit dépendances/licences/données ; ajout de la licence manquante. |
| 9 — Régression | 80 tests verts, dont 11 nouveaux ciblant précisément les bugs trouvés. |
| 10 — Recherche continue | Vérification factuelle avant chaque affirmation du rapport. |
| 11 — Adaptation marché | Alignement sur les exigences du hackathon et sur la convention « no license = all rights reserved ». |
| 12 — Version finale | Récapitulatif ci-dessous + `CHANGELOG.md`. |

---

## 2. État initial : ce qui était déjà bon

Il faut le dire honnêtement : **le projet n'était pas mauvais.** C'est une base saine, avec des choix défendables et une documentation inhabituellement franche (le README et les commentaires admettent déjà les limitations).

- Architecture claire en étages (COLLECT → NORMALIZE → DEDUP → CLUSTER → PERSIST → SCORE → DECIDE → VERIFY → NOTIFY), chaque étage isolé dans un module.
- Règle « open source first » réellement appliquée : MinHash/LSH (`datasketch`), fuzzy (`rapidfuzz`), canonicalisation URL (`courlan`), détection de changement de régime (`ruptures`), notifications (`apprise`), planification (`apscheduler`) — jamais réécrits.
- La logique réellement propriétaire (scoring, décision, identité cross-run, vérification) est bien identifiée comme telle.
- Déjà présents et corrects : dédup qui gère le cas « MinHash vide = faux positif à 1.0 », gating de `before_tiktok` par la pertinence, pénalité de risque, cooldown anti-répétition des alertes, isolation de chaque update Telegram pour que le bot ne meure jamais.
- Les commentaires citent de vrais bugs trouvés en conditions réelles et les tests correspondants existent.

Bref : le travail ci-dessous n'est pas une réécriture, c'est une **reprise chirurgicale de ce qui était prouvablement faux ou fragile.**

---

## 3. Ce qui était réellement mauvais (bugs prouvés, reproduits avant correction)

Tous ces points ont été **reproduits par un script d'audit** avant d'être corrigés.

### 3.1 `diversity_score` pouvait dépasser 1.0 (scoring faussé)
`diversity_score = len(platforms) / 2` était un reste de l'époque à deux sources (X + Reddit). Après passage à **six sources**, un cluster vu sur 4 plateformes obtient `diversity = 2.0`, ce qui gonfle `composite_score` (et donc `opportunity_score`) d'un facteur non prévu.
**Reproduction :** cluster twitter+reddit+hn+github → `diversity_score = 2.0`, `composite = 0.417`.

### 3.2 Un seul post malformé faisait tomber tout le cycle (le plus grave)
`normalize_twitter_post` faisait `int(raw["views"])`. OpenCLI renvoie des compteurs sous forme variable (« 1.2K », « N/A »). Un seul item de ce type lève `ValueError`. Comme `normalize_by_source` n'était **pas protégé**, l'exception remontait et **abortait la normalisation de toutes les sources du cycle** — et donc la totalité du run.
**Reproduction :** `views="1.2K"` → `ValueError` ; lot twitter `[bon, malformé]` → l'exception sort de `normalize_by_source`.

### 3.3 La dédup brute fusionnait tous les éléments sans `id`
`_dedupe_raw_by_id` indexait sur `str(p.get("id"))`. Tout item sans `id` (ex. entrée RSS sans `<guid>`) prenait la clé littérale `"None"` → **tous fusionnés en un seul signal**.
**Reproduction :** 3 entrées distinctes sans `id` → **1** conservée.

### 3.4 Une clé de signal dupliquée faisait planter le clustering
`datasketch.MinHashLSH.insert` lève `ValueError: The given key already exists` sur une clé dupliquée. Deux signaux peuvent partager `(source, source_id)` quand l'id amont manque (les deux deviennent `"None"`). Résultat : crash du run entier.
**Reproduction :** trouvé par fuzzing (voir §8).

### 3.5 Des champs non-chaînes atteignaient SQLite
`author`, `url`, `subreddit`, `published_at`/`updatedAt`/`created_at`, et le `fullName` GitHub (utilisé comme `title`) étaient écrits tels quels en base. Une valeur non-chaîne lève `sqlite3.ProgrammingError: Error binding parameter: type 'dict' is not supported` et **abandonne l'étape de persistance**.
**Reproduction :** fuzzing.

### 3.6 Parsing de dates non défensif
`datetime.fromisoformat` lève `TypeError` (pas `ValueError`) sur un non-chaîne. Les gardes de `velocity.py`, `independence.py` et `scoring._hours_since` n'attrapaient que `ValueError` → exception non gérée.
**Reproduction :** fuzzing.

### 3.7 Compteurs non bornés
La somme des compteurs d'engagement pouvait dépasser l'`int64` de SQLite (`OverflowError`).

### 3.8 Durcissement : URLs non-web accessibles au navigateur de vérification
Les liens candidats sont extraits de **texte tiers**. Rien n'empêchait un schéma non-web (`javascript:`, `file:`, `data:`) d'atteindre le pont navigateur.

---

## 4. Ce que j'ai corrigé (et pourquoi)

| # | Correctif | Fichier(s) | Pourquoi c'est le bon choix |
|---|---|---|---|
| 1 | `diversity_score` normalisé par une constante nommée (`_DIVERSITY_FULL_AT = 3`) et **plafonné à 1.0** ; `confidence_score` borné par ricochet | `scoring.py` | 3+ plateformes indépendantes = pleinement divers. Corrige la racine (constante non mise à jour) plutôt que de retoucher les poids. |
| 2 | `_safe_int` tolérant (int, `"1 234"`, `"1.2K"`, `"3M"`, junk → `None`) ; **`normalize_by_source` isole chaque item** et saute seulement le mauvais (avec avertissement) | `normalize.py`, `pipeline.py` | Un radar qui surveille 6 API hétérogènes **doit** dégrader proprement. Un item ne doit jamais coûter tout le run. |
| 3 | Dédup brute par **clé naturelle par source** (`id`/`fullName`/`objectID`/`guid`/`link`/`url`, sinon empreinte de contenu) | `pipeline.py` | Préserve le but initial (1 post vu sous 2 requêtes = 1 item) tout en ne fusionnant plus des items distincts. |
| 4 | Dé-doublonnage des clés dans `build_clusters` **et** `build_lsh_index` (on garde la 1ʳᵉ occurrence) | `cluster.py`, `dedup.py` | Supprime une classe entière de crash sans changer la sémantique pour des données saines. |
| 5 | `_as_str` sur tous les champs texte externes ; `owner` non-dict → `{}` | `normalize.py` | La frontière d'écriture SQLite devient étanche : rien de non-chaîne n'y arrive. |
| 6 | Garde de type **et** de format dans les parseurs de dates | `velocity.py`, `independence.py`, `scoring.py` | `fromisoformat` peut lever `TypeError` ; on attrape les deux. |
| 7 | Compteurs bornés à ±10¹⁵ | `normalize.py` | Empêche tout dépassement `int64` dans les sommes. |
| 8 | `_candidate_urls` n'accepte que `http(s)` | `verify_hackathon.py` | Cohérent avec la posture « safety d'abord » du reste (aucune tentative de contournement). |
| 9 | `extract_entities` retourne tôt sur un non-chaîne | `dedup.py` | Une regex ne doit pas planter sur une entrée inattendue. |
| 10 | **Cache déterministe `texte → MinHash`** (`lru_cache`) | `dedup.py` | La correspondance cross-run reconstruit le MinHash de **chaque** opportunité stockée à **chaque** run. Le texte d'un représentant est stable par définition → le cache supprime ce travail répété (~1,8× mesuré sur 400 stockées × 120 nouvelles). |

---

## 5. Ce que j'ai supprimé

**Rien.** Et c'est un choix, pas un oubli.

J'ai cherché activement du code mort, des fonctionnalités décoratives, des doublons et des placeholders (phase 8). Je n'en ai pas trouvé : chaque module est appelé, chaque champ de `Signal`/`OpportunityScore` est utilisé, et les rares « compat rétro » (`normalize_batch`, `PipelineResult.raw_twitter`) sont explicitement documentées comme telles et couvertes par des tests. Supprimer aurait cassé des tests ou de la compatibilité sans bénéfice. **Supprimer pour « faire propre » aurait été du slop inversé.**

---

## 6. Ce que j'ai ajouté

1. **`LICENSE` (MIT)** — le dépôt était « all rights reserved ». Pour un projet public dont tout le discours repose sur la réutilisation d'OSS, c'était une incohérence (voir §7).
2. **`.env.local.example`** — la configuration Telegram ne se devine plus.
3. **`CHANGELOG.md`** — trace défendable de chaque décision, avec fichier concerné.
4. **`tests/test_robustness.py`** — **11 tests de régression**, un par bug corrigé (plus les cas limites).
5. **Des docstrings/commentaires réécrits** pour expliquer le *pourquoi* du correctif (le style maison), plutôt qu'un simple « fix ».

---

## 7. Références marché / exigences (uniquement ce qui a été réellement consulté)

- **Hackathon First Commit (Devpost)** — page officielle ouverte : les exigences de soumission incluent **« A public GitHub repository containing your source code »**, un projet fonctionnel, une description, une vidéo de démo et un **README avec instructions d'installation**. Le critère **« Technical Execution — 25% »** inclut explicitement **« Code quality »** et **« Technical decisions »**. Deux conséquences directes :
  - le README (présent, complet) et un code défendable sont **notés** → justifie l'effort sur la robustesse et la traçabilité (`CHANGELOG.md`) ;
  - un dépôt public sans licence reste juridiquement « tous droits réservés », ce qui contredit l'esprit du projet → justifie l'ajout du **MIT**. *(Précision honnête : la page First Commit ne stipule pas explicitement de licence obligatoire ; d'autres hackathons Devpost, eux, l'exigent. J'ai donc ajouté la licence au titre de la cohérence du projet, pas d'une obligation lue noir sur blanc.)*
  - Source : <https://firstcommit.devpost.com/> (page ouverte, pas seulement un résultat de recherche).
- **Écosystème notifications OSS** — `caronc/apprise` et `binwiederhier/ntfy` ressortent comme les briques de référence (Apprise = « switchboard » vers 100+ services ; ntfy = serveur push auto-hébergé). **Confirme le choix existant** de ne pas réimplémenter la notification et de rester sur Apprise ; aucune modification nécessaire.
- **Littérature « alert fatigue »** — les sources convergent : ne notifier que ce qui est **actionnable**, regrouper, distinguer sévérité et confiance. **Valide la philosophie « filtrer avant de notifier »** déjà en place, et m'a explicitement dissuadé de « baisser le seuil » pour fabriquer de l'activité (voir §9).
- **Comparaison fonctionnelle (domaine opportunités)** — les agrégateurs du genre (airdrops.io, CryptoRank « drophunting ») publient des **listes** ; le différenciateur revendiqué de RADAR (décision graduée + risque + dédup) reste pertinent. Je n'ai pas modifié le produit sur cette base : le positionnement était déjà bon.

---

## 8. Preuves / tests réellement exécutés

### 8.1 Suite de tests
```
avant : 69 passed
après : 80 passed   (+11 tests de régression)
```
Commande : `.venv\Scripts\python.exe -m pytest -q`

### 8.2 Fuzzing de la chaîne complète (red team)
Harnais : 1 500 itérations de lots aléatoires/malformés (types aberrants, valeurs extrêmes, `NaN`, emojis, chaînes de 5 000 caractères, timestamps absurdes…) injectés dans `normalize → cluster → persist → score → decide`.

```
avant : 25 exceptions distinctes non gérées  (dont le crash MinHashLSH et les erreurs SQLite)
après : 0 exception                        (1 500 itérations terminées)
```

### 8.3 Run réel de bout en bout (sources réseau : GitHub, Hacker News, YouTube, RSS)
```
[collect] 5,2 s   raw=175  signals=175  clusters=166
[persist] run_id=281f962b2b4f  nouvelles_opportunités=165
[tiers]   {'watch': 13, 'ignore': 153}
[2ᵉ run]  clusters=10  nouvelles=0   ← l'identité cross-run fonctionne
```
Points vérifiés en vrai : diversité désormais bornée (0,333 mono-plateforme, 0,667 bi-plateforme) ; le second run **résout** les clusters sur des `opportunity_id` existants (**0** fausse nouvelle opportunité) ; le pipeline dégrade proprement (aucune source navigateur requise).

### 8.4 Micro-benchmark performance
```
400 opportunités stockées × 120 nouveaux clusters
sans cache : 0,07 s     avec cache : 0,04 s     (≈1,8×)
```
Gain réel mais **modeste** : je ne le présente pas comme une victoire majeure. Le coût structurel reste O(nouveaux × stockés).

---

## 9. Décisions assumées (ce que je n'ai **pas** fait, et pourquoi)

- **Je n'ai pas baissé le seuil d'alerte ni les critères `do_now`** pour « faire vivre » le produit. Le run réel ne produit quasiment pas de `do_now` — c'est le comportement **voulu** selon la littérature anti-alert-fatigue et la promesse du README (« les 1‑2 qui passent la barre »). Baisser la barre aurait été du slop déguisé en activité.
- **Je n'ai pas réécrit la correspondance cross-run** en index LSH complet. C'est l'optimisation « évidente », mais elle peut changer subtilement la sémantique (la similarité fuzzy ≥ 85 % peut matcher sous le seuil LSH). Le risque de régression dépasse le gain. J'ai pris le gain **sûr** (cache déterministe) et documenté le coût restant.
- **Je n'ai pas généralisé l'étape VERIFY** au-delà des hackathons : c'est une brique réelle (fetch réseau) et une décision de produit, pas une correction. Signalée comme prochaine étape logique (déjà dans le README).
- **Je n'ai pas poussé sur GitHub.** Les modifications sont prêtes localement ; la publication est une action publique qui t'appartient (voir §11).

---

## 10. Limites restantes (honnêtes)

1. La correspondance cross-run reste une heuristique (peut scinder une opportunité en deux, ou en fusionner deux proches) — limite déjà reconnue, non résolue ici.
2. Coût du matching cross-run en O(nouveaux × stockés) : correct pour l'historique d'un outil perso, pas conçu pour des centaines de milliers d'opportunités.
3. Les heuristiques pertinence/risque/décision sont **anglophones** et réglées sur peu de données réelles.
4. La vérification sur page officielle n'existe que pour les hackathons ; l'extraction deadline/prize est regex, « best effort ».
5. X/Reddit dépendent d'une session navigateur (`opencli`) — la partie la moins « zéro configuration ». **Je n'ai pas pu exercer ces deux sources** (pas de session navigateur dans cet environnement), donc mon run réel ne couvre que 4 des 6 sources.
6. Le cache MinHash a une taille bornée (8 192 textes) ; au-delà, il re-calcule (dégradation douce, pas de bug).

---

## 11. État de livraison

- Tous les changements sont **locaux**, non commités, non poussés : `git status` liste 9 fichiers modifiés + 4 nouveaux.
- Pour valider/rejouer localement :
  ```
  cd radar
  py -3.12 -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  .venv\Scripts\python.exe -m pytest -q          # 80 passed
  .venv\Scripts\python.exe run.py                # un cycle réel
  ```
- La publication (`git commit` / `gh repo` push) attend ton feu vert.

---

## 12. Conclusion défendable

Ce projet était bon ; il est maintenant **fiable**. La différence n'est pas un catalogue de fonctionnalités ajoutées — c'est que six défauts réels, dont trois capables de **faire tomber tout le radar** sur des données réelles, ont été reproduits puis éliminés, chacun avec un test de régression. Le fuzzing est passé de 25 exceptions à 0, la suite de tests de 69 à 80, et un run réel confirme que la collecte, l'identité cross-run et le filtrage fonctionnent. Les choix de conception existants (filtrage avant notification, réutilisation OSS, explication lisible du risque) ont été **validés** par la recherche, pas remplacés.
