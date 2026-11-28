# Architecture des agents et de la file des passages

Les agents de Randovango travaillent en chaînes, une ville à la fois : la chaîne des services cherche sur le web
les restaurants, commerces, supermarchés et laveries, avec une preuve pour chacun ; celle des spots harmonise,
date et vérifie les spots de la source des spots ; celle des pépites prépare les idées de Vany. Chaque chaîne
passe par la file des passages, qu'elle soit demandée par l'envoi d'une rando ou par l'administratrice depuis la
supervision. Les schémas suivent la chaîne des services ; les autres suivent le même chemin.

Le principe, pour tous les agents : **l'agent propose, le code contrôle, l'humain tranche.**

## Les schémas

### 1. D'où viennent les passages

Trois entrées remplissent la même file. Les demandes faites depuis le front par un compte admin (origines
`supervision` et `ajout`) sont prioritaires ; l'envoi en masse et les randos des contributeurs gardent l'ordre
d'envoi (origine `etl`).

```mermaid
flowchart LR
    ADD["Rando envoyée<br/>depuis la page d'ajout"] --> ETL["ETL de la rando<br/>lecture, chargement,<br/>météo"]
    BULK["Envoi en masse<br/>fichiers déposés dans<br/>le dossier d'attente,<br/>traités un à un en fond"] --> ETL
    ETL -- "nouvelle commune" --> ASK["Chaînes de la commune<br/>seulement ce qui n'a<br/>jamais été fait"]
    ASK --> FILE[["File des passages"]]
    ADMIN["Administratrice<br/>supervision : lancer,<br/>reprendre"] --> FILE
```

### 2. Le principe de la file

Chaque étape a sa propre file : elle prend une ville à la fois, les demandes prioritaires d'abord, puis dans l'ordre
d'envoi. Elle n'attend jamais les étapes qui viennent après elle.

```mermaid
flowchart TD
    ENV["Envoi de randos : villes dans l'ordre d'arrivée"]

    subgraph GRATUIT["Étapes gratuites : elles enchaînent les villes sans attendre la suite"]
        OSM["OSM et Wikidata : seul appel Overpass, une ville à la fois"]
        CARB["Carburants (fichier de l'État et stations OSM déjà chargées)"]
        FIN["FINESS (pharmacies)"]
        SRC["Lecture de la source des spots, un navigateur à la fois"]
    end

    subgraph PAYANT["Étapes payantes : elles attendent le quota ou le budget sans échouer"]
        HAR["Harmonisation des spots"] --> OUV["Lecture des ouvertures"] --> VER["Vérification des spots"]
        PEP["Pépites de la ville"]
        SER["Services : restaurants, commerces, supermarchés, laveries"]
    end

    ENV --> OSM
    ENV --> SRC
    OSM -->|"ville N prête"| CARB
    OSM -->|"ville N prête"| FIN
    OSM -->|"ville N prête"| PEP
    OSM -->|"ville N prête"| SER
    SRC -->|"ville N prête"| HAR

    OSM -.->|"N fini : prend N+1"| OSM
    SRC -.->|"N fini : prend N+1"| SRC
    CARB -.->|"N fini : prend N+1 si prête"| CARB
    FIN -.->|"N fini : prend N+1 si prête"| FIN
    PEP -.->|"N fini : prend N+1 si prête"| PEP
    SER -.->|"N fini : prend N+1 si prête"| SER
    HAR -.->|"N fini : prend N+1 si prête"| HAR
```

Les flèches pointillées : chaque étape, dès qu'elle a fini la ville N, prend la ville N+1 si celle-ci est prête pour
elle. Les étapes de tête (OSM, source des spots) n'attendent personne ; les autres attendent seulement que leur étape
d'avant ait fini cette ville-là.

Exemple dans le temps, trois villes envoyées ensemble (durées inventées, FINESS omis) :

```mermaid
gantt
    title Trois villes envoyées ensemble
    dateFormat HH:mm
    axisFormat %H:%M
    section OSM (Overpass)
    Ville 1 :o1, 00:00, 5m
    Ville 2 :o2, after o1, 5m
    Ville 3 :o3, after o2, 5m
    section Carburants
    Ville 1 :c1, after o1, 2m
    Ville 2 :c2, after o2, 2m
    Ville 3 :c3, after o3, 2m
    section Pépites (payant)
    Ville 1 :p1, after o1, 15m
    Ville 2 :p2, after p1, 15m
    Ville 3 :p3, after p2, 15m
    section Services (payant)
    Ville 1 :s1, after o1, 20m
    Ville 2 :s2, after s1, 20m
    Ville 3 :s3, after s2, 20m
    section Source des spots
    Ville 1 :r1, 00:00, 4m
    Ville 2 :r2, after r1, 4m
    Ville 3 :r3, after r2, 4m
    section Agents des spots (payant)
    Ville 1 :a1, after r1, 12m
    Ville 2 :a2, after a1, 12m
    Ville 3 :a3, after a2, 12m
```

OSM a fini les trois villes en un quart d'heure, pendant que les pépites et les services de la ville 1 tournent
encore : les étapes payantes prennent la ville suivante à leur rythme.

### 3. La chaîne des services, étape par étape

Pour chaque catégorie (restaurants, commerces, supermarchés, laveries), les agents et le code se relaient :
l'agent propose, le code contrôle, et ce qui reste douteux part en supervision, où l'humain tranche.

```mermaid
flowchart TB
    S1["1. Recherches en parallèle<br/>agent find_…"] --> S2["2. Contrôle des pages<br/>par le code"]
    S2 --> S3["3. Relecture de chaque lieu<br/>agent analyze_…"]
    S3 --> S4["4. Preuves par petits lots<br/>agent prove_…"]
    S4 --> S5["5. Contrôle des détails<br/>et lecture du registre, par le code"]
    S5 --> STORE["6. Enregistrement<br/>met à jour un service existant,<br/>n'en crée jamais un en double"]
    S3 -- "doute" --> SUP["Supervision<br/>l'humain tranche"]
    S5 -- "doute" --> SUP

    classDef agent fill:#E3EEF8,stroke:#2F6496,color:#22424B
    classDef code fill:#F0EEE3,stroke:#8A877A,color:#22424B
    class S1,S3,S4 agent
    class S2,S5,STORE code
```

En bleu, ce que fait un agent ; en gris, ce que fait le code.

### 4. Ce que chaque passage laisse derrière lui

```mermaid
flowchart TB
    RUN["Un passage"] --> PASS[("passages, passage_parts<br/>la demande, l'état,<br/>la raison d'un échec")]
    RUN --> CALLS[("llm_calls<br/>tokens, durée et coût<br/>de chaque appel")]
    RUN --> SERV[("Services<br/>ce que voit le voyageur")]
    RUN --> ITEMS[("passage_items<br/>ce que le passage a<br/>ajouté ou modifié")]
    RUN --> TRACE["Carnet de bord JSON<br/>reprise et rejeu<br/>sans repayer"]
```

L'espace Agents de la supervision lit ces traces (`GET /api/supervision/passages`) pour montrer l'état d'un passage,
ce qu'il a trouvé et ce qu'il a coûté.

**Le socle commun.** Tous les agents appellent le modèle de langage par un seul fichier, `agents/llm_service.py`,
et `agents/llm_config.py` dit quel modèle sert à chaque agent : changer de fournisseur ne touche que ces deux fichiers.

## Ce qu'il faut retenir

- **Lancer.** `POST /api/supervision/passages` reçoit la chaîne, la ville et les catégories
  (`{"chaine": "services", "ville_id": 12, "categories": ["restaurants"]}`). La demande est écrite dans `passages`, puis
  elle entre dans la file de son étape et part à son tour : la route répond tout de suite, une grande ville pouvant
  prendre des heures.
  C'est toujours une vraie mise à jour : l'essai et le rejeu restent des outils de la ligne de commande
  (`python -m agents.find_services --essai`, `--rejouer`).
- **Un seul passage à la fois par étape.** Deux passages des services en même temps créeraient le même service deux
  fois. Un verrou tenu par MySQL l'empêche, pour l'API comme pour la ligne de commande. Un second lancement de la même
  chaîne sur la même ville est refusé (409) avec un message qui nomme le passage déjà demandé ; sur une autre ville, il
  attend son tour dans la file.
- **Suivre.** L'état vient de deux tables : `passages` et `passage_parts` disent ce qui a été demandé et où en est
  chaque catégorie ; `llm_calls` donne le coût et l'étape de chaque appel d'agent, sous le même identifiant de passage.
- **Attendre le fournisseur.** Si le quota des agents est atteint, ou s'ils reçoivent trop d'appels à la fois, la
  catégorie en cours n'échoue pas. Le service d'accès au modèle (`agents/llm_service.py`), seul à connaître le
  fournisseur, en fait une limite neutre avec son heure de retour ; le passage retourne en file, et les étapes payantes
  attendent cette heure (`services/agents_pause.py`). Elles repartent seules, sans repayer ce qui est fait.
- **Échouer et reprendre.** Une autre erreur (délai dépassé, crédit de l'API épuisé) fait passer la catégorie en
  échec avec une raison lisible, et le passage s'arrête. Les catégories finies restent enregistrées. La reprise
  (`POST /api/supervision/passages/ID/reprise`) ne refait que les catégories non finies ; une grande ville reprend en
  plus ses zones finies depuis son fichier JSON. Elle est acceptée même quand la même étape tourne sur une autre ville.
  La reprise est un nouveau passage : dans l'échec, les catégories jamais commencées passent à « reprise », avec le
  lien vers le passage qui les refait (`refaite_par`) ; une catégorie « à faire » veut donc toujours dire qu'il reste
  du travail. Les passages repris avant cette règle sont rattrapés au démarrage de la file.
- **Une chaîne en paramètre.** Les chaînes (`CHAINS` dans `passage_service.py`) se lancent toutes par les mêmes
  routes : services, spots, pépites, et les chaînes gratuites de l'ajout d'une ville (OSM, carburants, FINESS).
- **Ce qu'un passage a trouvé.** Chaque service, spot ou pépite qu'un passage ajoute ou modifie est noté dans
  `passage_items`, avec la partie qui l'a écrit. `GET /api/supervision/passages/ID` donne la liste de ses trouvailles ;
  la liste des passages, filtrée sur un objet, dit quel passage a apporté une information. Un lancement en ligne de
  commande ou une action d'un voyageur y figure aussi, sous son identifiant, sans ligne dans `passages`.
- **Une écriture à la fois.** Les étapes de la file écrivent chacune à son tour : avant d'écrire, une étape demande à
  MySQL un verrou nommé commun à toutes (`randovango_ecriture_file`), et la suivante attend que la première ait fini,
  dix minutes au plus. Si MySQL annule malgré tout une écriture pour interblocage, elle est refaite, trois fois au
  plus ; le passage n'échoue plus pour cela. Les écritures du journal des passages passent sous le même verrou.
- **Les mesures.** `llm_calls` garde chaque appel, réussi ou non : son coût en dollars, sa durée, ses tokens,
  ses recherches web, son passage et son étape. C'est la source du suivi des coûts dans la supervision.

## La file des passages

Une ville ajoutée par l'envoi d'une rando demande ses chaînes à la file (`services/passage_queue.py`). Chaque étape
(`services/passage_steps.py`) a sa propre file et son propre fil de fond : elle prend une ville à la fois, dans l'ordre
d'envoi, et n'attend jamais les étapes qui viennent après elle.

| Étape | Elle attend, pour la ville | Payante |
|---|---|---|
| OSM et Wikidata (seul appel à Overpass) | rien | non |
| Lecture de la source des spots (un navigateur à la fois) | rien | non |
| Carburants, pharmacies FINESS | OSM et Wikidata | non |
| Pépites de la ville, services | OSM et Wikidata | oui |
| Agents des spots : harmonisation, puis ouvertures, puis vérification | la lecture de la source | oui |

- Une demande faite depuis le front avec un compte admin passe devant les envois en masse de l'ETL dans son étape :
  une demande ou une reprise depuis la supervision (origine `supervision`), une rando envoyée par un compte admin
  depuis la page d'ajout (origine `ajout`). Elle ne coupe pas le passage en cours : elle part juste après lui. Entre
  deux demandes admin, l'ordre d'envoi est gardé ; le budget et le quota s'appliquent comme aux autres. Une rando d'un
  compte contributeur, le dossier d'attente et les reprises faites seules par la file gardent l'origine `etl` et
  l'ordre d'envoi. La supervision le montre dans le champ `prioritaire` de chaque passage.
- Une ville pas prête pour une étape (son OSM pas fini, ou en échec) est sautée : l'étape prend la suivante, et
  seule cette ville attend.
- Quand le quota ou le budget des agents est atteint, seules les étapes payantes attendent ; les étapes
  gratuites continuent. Au retour, elles repartent de la ville la plus ancienne.
- Une partie gratuite en échec (OSM, carburants, FINESS, ou la lecture de la source des spots) est reprise seule un
  quart d'heure plus tard, deux fois au plus, sauf si la même chaîne est déjà en file ou en cours sur la ville, ou si
  cette partie a été refaite depuis. Un échec sur une partie payante attend toujours l'administratrice.
- Un passage resté « en cours » alors que plus rien ne le fait tourner (serveur redémarré, programme arrêté) est
  marqué « interrompu » par la file elle-même, chaque minute : sur une partie gratuite, il est ensuite repris seul, et
  les étapes de sa ville repartent. Un passage qui tourne tient un verrou MySQL à son identifiant
  (`randovango_passage_<identifiant>`) : « en cours » sans ce verrou tenu, il est coupé. Le verrou de la chaîne ne
  suffit pas à le dire, car les services, la source des spots et les agents des spots en ont un seul pour toutes les
  villes : un passage coupé paraîtrait tourner tant qu'une autre ville tient ce verrou.
- Seul le backend principal fait tourner la file. Un backend de branche (`docker-compose.branche.yml`) partage la
  base commune mais ne lance aucun thread (`PASSAGE_QUEUE_ENABLED=0`) : il ne prend pas les passages pour les faire avec
  le code de sa branche, et ne marque pas « interrompus » ceux que le principal fait tourner. Une ville ajoutée depuis
  une branche entre en file et part depuis le backend principal.

## Le coût en euros et le budget

- **En dollars dans la base.** Le fournisseur des agents facture en dollars : `llm_calls.cost_usd` garde le coût de
  chaque appel dans cette monnaie. Par l'abonnement, c'est ce qu'aurait coûté l'appel par l'API, donné par le
  programme du fournisseur installé sur la machine : un équivalent, pas une dépense. Par l'API, c'est
  une dépense réelle, calculée avec le tarif de chaque modèle (`agents/llm_prices.py`, à tenir à jour à la main).
- **En euros à l'écran.** La conversion se fait à la lecture, jamais dans `llm_calls` : dollars ÷ taux × 1,20 (TVA),
  au taux de référence de la Banque centrale européenne du jour de l'appel. C'est une estimation : la banque applique
  son propre taux et ses frais. Le taux est lu une fois par jour sur le fichier public de la BCE (90 derniers jours) et
  gardé dans `exchange_rates` (`services/exchange_rate_service.py`). Un jour sans taux (week-end, jour férié, taux du
  jour pas encore publié), le dernier taux connu sert, et le libellé le dit (« dernier connu »).
- **Ce qui s'affiche.** Le coût d'un passage et de chaque catégorie (`GET /api/supervision/passages/ID`) et les
  lignes du journal des agents donnent les dollars, les euros TTC, le taux avec sa date, et ce que vaut le coût :
  « dépense réelle » ou « équivalent API, abonnement ».
- **Le budget.** L'administratrice règle en euros TTC l'enveloppe du mois, le plafond du jour et la part gardée pour
  Vany (`GET` et `PUT /api/supervision/passages/reglage`). La dépense du jour et du mois est convertie jour par jour,
  chacun à son taux : le plafond ne bouge pas quand le dollar varie. Un passage payant ne part pas quand le budget
  est atteint (`services/budget_service.py`). Les montants sont aussi écrits en dollars dans `agent_settings`, pour le
  code qui lit encore les anciennes colonnes.
- **Le budget coupé, sur le poste de développement.** Par l'abonnement, la dépense n'est qu'un équivalent :
  `AGENT_BUDGET_ENABLED=0` coupe alors le plafond du jour et l'enveloppe du mois, et plus aucun passage n'attend à
  cause du budget. Les dépenses restent comptées et affichées, et `budget_actif` vaut `false` dans
  `GET /api/supervision/passages/reglage`. Sans ce réglage, le budget est actif (préprod, prod). Le réglage se lit
  au démarrage du conteneur de l'API : on le change avant un gros envoi, pas pendant un passage.
- **Sans aucun taux.** Si le site de la BCE n'a jamais pu être lu, la dépense ne peut pas se compter en euros : les
  passages payants attendent, un changement de montant est refusé (503), et les coûts gardent leurs seuls dollars.
