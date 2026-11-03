"""
Harmonisation des descriptions des spots Park4Night par Claude.

C'est une transformation POST-CHARGEMENT (voir agents/__init__.py) :
  extract -> transform -> load -> transformation post-chargement (ce fichier)

LE PROBLÈME
Les descriptions des spots sont écrites par des utilisateurs, chacun à sa façon :
récits ("nous avons dormi ici..."), notes de trois mots, textes publicitaires
de campings, fautes d'orthographe... Impossible à harmoniser avec du SQL.

LA SOLUTION : HARMONISER
Pour chaque spot, Claude lit la description et la réécrit en ne gardant que ce
qui est utile à un voyageur en van. Le résultat est rangé dans la colonne
`description_ia`, À CÔTÉ de la description d'origine.

Le nom affiché sur le site, lui, ne passe pas par Claude : il est construit à
partir des données Park4Night (voir spot_name_label dans utils/display_utils.py).

Ce n'est PAS de l'enrichissement : aucune source externe n'est utilisée, tout
ce qui sort vient du texte du contributeur.

DEUX RÈGLES À NE JAMAIS CASSER
  1. La colonne `description` n'est JAMAIS modifiée : on garde toujours le
     texte original de Park4Night, pour pouvoir tout refaire si besoin.
  2. Claude ne doit rien inventer.

ON NE REFAIT PAS LE TRAVAIL DEUX FOIS
Chaque spot traité garde dans `prompt_version` la version des consignes utilisée.
Un spot est à (re)faire s'il n'a jamais été traité (NULL) ou s'il l'a été avec
une version plus ancienne que PROMPT_VERSION.

UTILISATION (dans le conteneur backend, depuis /usr/src/app)
  Avec l'API Anthropic (clé ANTHROPIC_API_KEY) :
    python -m agents.harmonize_spots --sample 20     # teste sur 20 spots
    python -m agents.harmonize_spots --submit        # envoie tous les spots en un lot
    python -m agents.harmonize_spots --collect <id>  # récupère les résultats du lot

  Avec l'abonnement Claude (programme `claude`, jeton CLAUDE_CODE_OAUTH_TOKEN) :
    python -m agents.harmonize_spots --engine claude-code --sample 20
    python -m agents.harmonize_spots --engine claude-code --all
    python -m agents.harmonize_spots --engine claude-code --id 31  # un spot précis
"""
import argparse
import json
from datetime import date

from agents.llm_config import ENGINE_API, ENGINE_CLAUDE_CODE, engine, make_llm_service
from agents.llm_service import LLMUnavailable
from utils.db_utils import MySQLUtils
from utils.display_utils import HIDDEN_SPOT_TYPES
from utils.logger_util import LoggerUtil
from utils.review_utils import PROMPT_SELECTION, select_reviews
from utils.service_utils import SERVICE_CATEGORY_MAP, ServiceUtil

logger = LoggerUtil.get_logger("etl_harmonize_spots")


# =============================================================================
# 1. CE QU'ON DEMANDE À CLAUDE
# =============================================================================

# Version des consignes ci-dessous. À AUGMENTER À CHAQUE MODIFICATION DU PROMPT :
# tous les spots traités avec une version plus ancienne seront refaits.
#   1 à 4 : mises au point (nom, anecdotes, méta-commentaires, tags...)
#   5     : simplification, Claude ne renvoie plus que display_name et summary
#   6 et 7: résumé limité à 300 caractères, avec ordre de priorité
#   8     : plus de limite de longueur ; on filtre le contenu (utile en van ou non)
#   9     : question-test pour filtrer, exemples (entretien, Natura 2000, animations...),
#           majuscules corrigées aussi dans display_name
#   10    : plus de listes d'exemples ; on décrit le lecteur (la van life) et
#           Claude décide lui-même ce qui est utile
#   11    : plus de display_name (il n'améliorait aucun nom) : une seule tâche
#   12    : Claude ne reçoit plus que la description (le contexte provoquait des
#           déductions) ; catégories générales de bruit ; ne pas allonger ;
#           plus limité à la Bretagne
#   13    : tri par listes GARDER / SUPPRIMER ("en cas de doute, supprime"),
#           paragraphe "À savoir :" pour les avertissements, exemple inventé
#   14    : supprimer ce qui s'adresse aux clients sans véhicule (locations)
#   15    : les services ne sont plus listés dans le texte (les badges les
#           affichent) ; Claude renvoie les services cités pour compléter les badges
#   16    : a_verifier, vrai si le texte signale une situation temporaire ou datée
#           (fermeture, travaux...) à faire vérifier plus tard par un agent web
#   17    : ne pas citer un service absent ou interdit ; anecdotes de nouveau
#           supprimées ; harmonisation avec Opus 5.5 au lieu de Sonnet 5.5
#   18    : entrées enrichies (ouverture + 10 commentaires datés de voyageurs) ;
#           nuit_interdite ; description vide si rien au-delà du type ou du nom ;
#           ne pas signaler l'absence d'une date
#   19    : "À savoir" réservé à ce qui change la décision ou le séjour ;
#           a_verifier limité aux situations temporaires décisives ; on peut dater
#           une information mais pas commenter ses sources
#   20    : une interdiction de nuit saisonnière n'est pas nuit_interdite (le spot
#           reste visible hors saison, l'interdiction et sa période dans « À savoir »)
#   21    : doute_nuit, un fait rapporté sans certitude : le spot part en vérification
#   22    : date du jour reçue et règles sur les informations anciennes (nuisance, incident,
#           interdiction, minimum de nuits, panne récente)
PROMPT_VERSION = 22

# Services que Claude peut citer : la liste fermée des services Park4Night
# (les services exclus, comme "Belle balade à moto", n'y sont pas).
SERVICE_NAMES = sorted(SERVICE_CATEGORY_MAP.keys())

# Le "schéma JSON" décrit exactement la réponse attendue. Claude est obligé de
# le respecter : on reçoit toujours ces six champs, et rien d'autre. La liste
# "enum" empêche Claude d'inventer un service qui n'existe pas dans Park4Night.
SPOT_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "Description réécrite, limitée aux informations utiles en van, ou chaîne vide.",
        },
        "services": {
            "type": "array",
            "items": {"type": "string", "enum": SERVICE_NAMES},
            "description": "Services explicitement cités dans le texte, choisis dans la liste.",
        },
        "a_verifier": {
            "type": "boolean",
            "description": "Vrai si le texte signale une situation temporaire ou datée qui a pu changer.",
        },
        "nuit_interdite": {
            "type": "boolean",
            "description": "Vrai si on ne peut pas passer la nuit sur place (interdiction, fermeture définitive).",
        },
        "doute_nuit": {
            "type": "boolean",
            "description": "Vrai si un fait rapporté laisse penser qu'on ne peut peut-être pas dormir sur place.",
        },
        "doute_nuit_raison": {
            "type": "string",
            "description": "Le fait à l'origine du doute, ou chaîne vide.",
        },
    },
    "required": ["description", "services", "a_verifier", "nuit_interdite", "doute_nuit", "doute_nuit_raison"],
    "additionalProperties": False,
}

# Les consignes données à Claude. Elles sont les mêmes pour tous les spots.
SYSTEM_PROMPT = """Tu harmonises des fiches de stationnement Park4Night pour Randovango, une application
de voyage en van entre randonnées et nuits sur la route. Pour chaque lieu, tu reçois :
- la DESCRIPTION écrite par un contributeur (récit, note télégraphique ou texte marketing), parfois
  vide ou réduite à un nom ;
- la période d'OUVERTURE indiquée sur la fiche, si elle est renseignée ;
- des COMMENTAIRES de voyageurs, datés et notés sur 5, éventuellement en langue étrangère.

## Lecteur
Un voyageur en van ou camping-car qui consulte la fiche sur son téléphone pour décider vite :
puis-je dormir là, avec mon véhicule, et que dois-je savoir avant d'y aller ?

## Règle absolue : n'invente rien
Tu ne disposes que des informations reçues. Ne déduis rien, ne complète rien avec tes connaissances.

## Sources
- La description présente le lieu. Si elle est vide ou pauvre, construis la fiche à partir des
  commentaires.
- Les commentaires sont des témoignages. Retiens les faits concrets qu'ils rapportent (équipement,
  accès, calme, contrôles, fermeture). Les plus récents décrivent l'état actuel : en cas de
  contradiction avec la description, ils l'emportent.
- Une appréciation isolée ne devient pas un fait : ne la retiens que si plusieurs commentaires vont
  dans le même sens.
- Tu peux dater une information ("signalé en août 2026"), mais ne parle jamais des sources
  elles-mêmes ("un commentaire rappelle", "non confirmé par les commentaires").

## Tri : tu dois trancher
Passe chaque information au crible des deux listes. Ce qui n'est pas dans GARDER est supprimé.
En cas de doute, supprime.

GARDER (faits concrets uniquement) :
- type de lieu et cadre physique (bord de mer, forêt, parking goudronné, pelouse, vue)
- accès et gabarit : route, pente, hauteur, taille de véhicule acceptée
- statut : autorisé, toléré, interdit, période d'ouverture
- précisions sur les services : emplacement, conditions, restrictions ("eau derrière les WC",
  "wifi gratuit 1 h", "électricité interdite aux camping-cars"). La simple liste des services
  est affichée à part sous forme de badges : ne la répète pas dans le texte.
- commerces et ravitaillement sur place ou très proches
- calme ou bruit la nuit, éclairage, sécurité
- nature et activités accessibles à pied : plage, sentier, GR, spot de baignade ou de glisse
- avertissements : réglementation, chiens, marées, risques, verbalisations

SUPPRIMER :
- appréciations, superlatifs, notes et classements
- historique de l'établissement et informations sur les personnes (gérants, personnel)
- ce qui concerne la région plutôt que le lieu lui-même
- ce qui s'adresse aux clients sans véhicule (locations, mobil-homes, hébergements)
- remerciements, exclamations, justifications
- tarifs chiffrés et années, sauf la date d'une situation temporaire (voir a_verifier)
- anecdotes du séjour d'un contributeur ("nous étions seuls", "il pleuvait")

## Forme
- Paragraphe 1 : le lieu, son cadre et les précisions utiles. Si le lieu n'est pas ouvert toute
  l'année, indique la période en français ("Ouvert du 1er mai au 15 septembre").
- Paragraphe 2, « À savoir : », seulement pour ce qui change la décision de venir ou la façon de
  séjourner : interdictions, contrôles, sécurité, accès, équipement en panne, règles (chiens,
  horaires). Une nuisance mineure (coqs, passage en journée) n'y figure que si plusieurs voyageurs
  la signalent.
- Troisième personne, présent, phrases courtes et factuelles, aucun adjectif évaluatif.
- Chaque fait n'apparaît qu'une fois. N'ajoute aucune phrase d'explication ou de liaison.
- Rédige en français, même si des commentaires sont en langue étrangère.
- Corrige l'orthographe, mais garde tels quels les noms propres en langue régionale (breton,
  basque, occitan...) : ne les francise pas.
- Ne commente jamais la fiche ni les informations reçues ("non daté", "le texte ne précise pas").
- Si les informations ne contiennent rien d'utile au-delà du type de lieu, d'un nom ou d'une
  adresse, `description` vaut la chaîne vide : n'écris pas "Camping." ou "Parking.".

## services
Liste les services proposés sur place ou à proximité immédiate et EXPLICITEMENT cités dans la
description ou les commentaires, choisis dans la liste imposée. Liste vide si aucun n'est cité. Ne
déduis jamais un service d'un type de lieu ("camping" n'implique pas des douches). Ne cite jamais un
service signalé comme absent, interdit ou hors service ("pas de vidange" n'est pas un service de
vidange).

## a_verifier
Vrai seulement si les informations signalent une situation temporaire qui changerait la décision
de venir et qui a pu évoluer depuis : fermeture, travaux, interdiction récente, équipement hors
service. Une information simplement datée (bruit signalé en 2025) ne suffit pas. Faux sinon. Dans ce cas, garde la
date dans la description : sans elle, on ne peut pas savoir si l'information est périmée. S'il n'y a
pas de date, n'en signale pas l'absence.

## nuit_interdite
Vrai si on ne peut JAMAIS passer la nuit sur place : stationnement interdit la nuit toute l'année,
lieu fermé définitivement, réservé à d'autres usagers. Faux sinon, et faux en cas de doute.
Une restriction limitée à une période n'en fait pas partie : fermeture saisonnière (indiquée par la
période d'ouverture) ou interdiction de nuit en saison seulement ("interdit jusqu'en septembre",
verbalisations signalées uniquement en été). Dans ce cas, le spot reste proposé hors saison :
indique l'interdiction et sa période dans « À savoir ».

## doute_nuit
nuit_interdite reste réservé aux certitudes. doute_nuit couvre le doute : vrai si un fait rapporté laisse
penser qu'on ne peut peut-être pas dormir sur place, même hors saison, sans que ce soit certain :
panneau interdisant la nuit, voyageurs réveillés ou renvoyés par la police ou un gardien, verbalisations,
même anciens, sans démenti plus récent.
Faux si :
- nuit_interdite est vrai ;
- l'interdiction est limitée à une période (elle va dans « À savoir ») ;
- ce n'est qu'une crainte sans fait précis ("on a eu peur de se faire déloger") ;
- un commentaire plus récent dément (nuit passée sans problème depuis, contrôle sans suite).
doute_nuit_raison : le fait, en une phrase avec sa date si elle est connue ; vide si faux.

## Informations anciennes
Compare chaque information à la DATE DU JOUR.
- Une nuisance mineure signalée une seule fois il y a plus de 2 ans n'a pas sa place dans
  « À savoir » : supprime-la.
- Un incident ponctuel (panne, accès, fermeture) : décris la situation actuelle, pas son histoire.
  Si un commentaire plus récent dit que c'est réparé ou rouvert, ce dernier l'emporte.
  Si des voyageurs sont passés depuis sans en parler et que l'incident date de plus de 6 mois,
  supprime-le.
- Si AUCUN commentaire n'est venu depuis et que l'incident bloque l'accès ou la nuit, ne conclus
  pas qu'il est résolu : garde-le daté, avec a_verifier à vrai.
- Une règle durable (interdiction, limite de séjour, gabarit, chiens) reste, même ancienne.
- Une interdiction ou une demande de partir (police, gardien, agents municipaux) sans aucun commentaire
  venu depuis : garde-la datée avec a_verifier à vrai, quel que soit son âge.
- Toute information ancienne que tu gardes conserve sa date ("signalé en 2019"). Ne la réécris jamais
  au présent : elle passerait pour un fait actuel.
- Un minimum de nuits imposé par le lieu ("minimum 2 nuits", "pas pour une seule nuit") est une règle durable
  qui change la décision de venir : garde-le toujours dans « À savoir », daté, même rapporté par un seul
  commentaire ancien, sauf si un commentaire plus récent le dément.
- Un équipement signalé hors service il y a moins de 6 mois ("ne fonctionne pas", "en panne"), sans commentaire
  venu depuis, même non bloquant et même peu clair : garde-le dans « À savoir », daté, avec a_verifier à faux.
  Ne conclus pas qu'il est réparé.

## Exemple
Entrée :
DESCRIPTION : "Superbe camping familial depuis 50 ans !! Accueil adorable par Marie. Emplacements
ombragés, sanitaires nickel 5/5, borne de vidange à l'entrée. Plage à 300 m à pied. Attention
route étroite, pas plus de 7 m. Prix 18€/nuit en 2023."
OUVERTURE : "open from may 1st to september 30th"
COMMENTAIRES :
- 12/08/2026, 4/5 : "Calme la nuit, mais la borne de vidange est en panne depuis juillet."
Sortie :
description : "Camping avec emplacements ombragés. Borne de vidange à l'entrée. Plage à 300 m
à pied. Calme la nuit. Ouvert du 1er mai au 30 septembre.

À savoir : route d'accès étroite, véhicules de 7 m maximum. Borne de vidange signalée en panne
depuis juillet 2026."
services : ["Toilettes"]
a_verifier : true
nuit_interdite : false

Réponds en français."""


def build_user_message(spot: dict) -> str:
    """
    Écrit le message envoyé à Claude pour un spot : la date du jour, sa description, sa
    période d'ouverture et ses commentaires sélectionnés (voir fetch_spots_to_harmonize).

    Pas de contexte géographique (commune, type de lieu...) : Claude pourrait en
    tirer des informations qui ne sont écrites nulle part.
    """
    lines = [
        f"DATE DU JOUR : {date.today():%d/%m/%Y}",
        f'DESCRIPTION : "{(spot.get("description") or "").strip()}"',
        f'OUVERTURE : "{spot.get("opening_period") or "non renseignée"}"',
        "COMMENTAIRES :",
    ]
    reviews = spot.get("reviews") or []
    if not reviews:
        lines.append("(aucun)")
    for review in reviews:
        review_date = review["review_date"].strftime("%d/%m/%Y") if review.get("review_date") else "date inconnue"
        rating = f"{review['rating']}/5" if review.get("rating") is not None else "sans note"
        text = (review.get("text") or "").replace("\n", " ").strip()
        lines.append(f'- {review_date}, {rating} : "{text}"')
    return "\n".join(lines)


def harmonize_one(service, spot: dict) -> dict:
    """
    Demande à Claude d'harmoniser UN spot et renvoie sa réponse (un dict).

    `service` est soit un LLMService (API), soit un ClaudeCodeLLMService
    (abonnement) : les deux ont la même méthode `complete_json`.
    """
    return service.complete_json(SYSTEM_PROMPT, build_user_message(spot), SPOT_SCHEMA)


# =============================================================================
# 2. LIRE ET ÉCRIRE DANS LA BASE MYSQL
# =============================================================================

# Colonnes d'une ancienne version de l'harmonisation, plus utilisées par personne.
OBSOLETE_COLUMNS = [
    "tags", "noise_level", "access_difficulty", "services_inferred",
    "stale_info", "confidence", "source_hash", "display_name",
]


def update_spots_columns(cursor, database: str) -> None:
    """
    Met la table `spots` à jour pour ce script :
      - renomme `enriched_at` en `harmonized_at` (ancien nom de la colonne) ;
      - ajoute les colonnes `prompt_version`, `a_verifier` et `nuit_interdite` si elles manquent ;
      - supprime les colonnes obsolètes si elles existent encore.
    On peut l'appeler plusieurs fois sans risque : ce qui est déjà fait est ignoré.
    """
    cursor.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = 'spots'",
        (database,),
    )
    existing_columns = [row[0] for row in cursor.fetchall()]

    if "enriched_at" in existing_columns:
        # RENAME COLUMN garde les valeurs déjà enregistrées.
        cursor.execute("ALTER TABLE spots RENAME COLUMN enriched_at TO harmonized_at")
        logger.info("[harmonize] Colonne spots.enriched_at renommée en harmonized_at")

    if "prompt_version" not in existing_columns:
        cursor.execute("ALTER TABLE spots ADD COLUMN prompt_version INT")
        logger.info("[harmonize] Colonne spots.prompt_version ajoutée")

    if "a_verifier" not in existing_columns:
        cursor.execute("ALTER TABLE spots ADD COLUMN a_verifier TINYINT(1)")
        logger.info("[harmonize] Colonne spots.a_verifier ajoutée")

    if "nuit_interdite" not in existing_columns:
        cursor.execute("ALTER TABLE spots ADD COLUMN nuit_interdite TINYINT(1)")
        logger.info("[harmonize] Colonne spots.nuit_interdite ajoutée")

    for column in OBSOLETE_COLUMNS:
        if column in existing_columns:
            cursor.execute(f"ALTER TABLE spots DROP COLUMN {column}")
            logger.info(f"[harmonize] Colonne obsolète spots.{column} supprimée")


def update_spot_service_table(cursor, database: str) -> None:
    """
    Ajoute à `spot_service` la colonne `source` si elle manque : 'p4n' pour les
    services cochés sur Park4Night (valeur par défaut, donc toutes les lignes
    existantes), 'ia' pour ceux ajoutés par l'harmonisation.
    On peut l'appeler plusieurs fois sans risque.
    """
    cursor.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = 'spot_service' AND column_name = 'source'",
        (database,),
    )
    if not cursor.fetchall():
        cursor.execute("ALTER TABLE spot_service ADD COLUMN source VARCHAR(10) NOT NULL DEFAULT 'p4n'")
        logger.info("[harmonize] Colonne spot_service.source ajoutée")


def fetch_spots_to_harmonize(cursor, limit: int = None, spot_ids: list = None, only_new: bool = False) -> list:
    """
    Renvoie les spots à harmoniser : jamais traités, ou traités avec une ancienne
    version du prompt. `limit` permet de n'en prendre que les N premiers.

    Les spots jamais affichés sur le site sont ignorés, inutile de dépenser des
    appels à Claude pour eux : les types masqués (HIDDEN_SPOT_TYPES, ex : robinet
    d'eau seul) et les doublons marqués par dedupe_spots.

    On n'harmonise qu'un spot dont les informations complémentaires ont été
    récupérées (details_scraped_at) et qui a une description OU des commentaires.

    `spot_ids` (option --id) : renvoie ces spots-là, qu'ils soient déjà
    harmonisés ou non. Sert à tester le prompt sur un cas précis.

    `only_new` (ETL) : seulement les spots jamais traités. Repasser les anciens
    sur une nouvelle version du prompt reste une décision, pas un effet du scraping.

    Chaque spot renvoyé contient aussi ses commentaires sélectionnés ("reviews").
    """
    columns = "id, description, opening_period"

    if spot_ids:
        id_placeholders = ",".join(["%s"] * len(spot_ids))
        cursor.execute(
            f"SELECT {columns} FROM spots WHERE id IN ({id_placeholders}) ORDER BY id",
            tuple(spot_ids),
        )
    else:
        # Un "%s" par type masqué, pour la clause NOT IN (...).
        type_placeholders = ",".join(["%s"] * len(HIDDEN_SPOT_TYPES))
        query = f"""
            SELECT {columns}
            FROM spots
            WHERE {"prompt_version IS NULL" if only_new else "(prompt_version IS NULL OR prompt_version < %s)"}
              AND details_scraped_at IS NOT NULL
              AND ((description IS NOT NULL AND description <> '')
                   OR EXISTS (SELECT 1 FROM spot_reviews WHERE spot_reviews.spot_id = spots.id))
              AND duplicate_of_spot_id IS NULL
              AND p4n_removed = 0
              AND type IS NOT NULL
              AND type NOT IN ({type_placeholders})
            ORDER BY id
        """
        params = HIDDEN_SPOT_TYPES if only_new else (PROMPT_VERSION, *HIDDEN_SPOT_TYPES)
        if limit:
            query += " LIMIT %s"
            params = (*params, limit)
        cursor.execute(query, params)

    # On transforme chaque ligne (un tuple) en dict : {"id": 1, "type": ..., ...}
    column_names = [column[0] for column in cursor.description]
    spots = []
    for row in cursor.fetchall():
        spots.append(dict(zip(column_names, row)))

    attach_reviews(cursor, spots)
    logger.info(f"[harmonize] {len(spots)} spot(s) à harmoniser")
    return spots


def attach_reviews(cursor, spots: list) -> None:
    """
    Ajoute à chaque spot ses commentaires, réduits à l'échantillon envoyé à
    Claude (PROMPT_SELECTION : récents + mauvais + bons, voir utils/review_utils.py).
    """
    if not spots:
        return
    placeholders = ",".join(["%s"] * len(spots))
    cursor.execute(
        f"SELECT spot_id, review_date, rating, text FROM spot_reviews WHERE spot_id IN ({placeholders})",
        tuple(spot["id"] for spot in spots),
    )
    by_spot = {}
    for spot_id, review_date, rating, text in cursor.fetchall():
        by_spot.setdefault(spot_id, []).append({"review_date": review_date, "rating": rating, "text": text})
    for spot in spots:
        spot["reviews"] = select_reviews(by_spot.get(spot["id"], []), *PROMPT_SELECTION)


def normalize(payload: dict) -> dict:
    """
    Met la réponse de Claude au format des colonnes de la base.
    - Une description vide devient None (NULL en base) : le site affichera alors
      la description d'origine.
    - a_verifier et nuit_interdite deviennent 1 ou 0 (MySQL n'a pas de vrai type booléen).
    - Un doute sur la nuit passe par a_verifier : verify_spots tranche, puis /supervision.
    """
    description = (payload.get("description") or "").strip()
    return {
        "description_ia": description or None,
        "a_verifier": 1 if payload.get("a_verifier") or payload.get("doute_nuit") else 0,
        "nuit_interdite": 1 if payload.get("nuit_interdite") else 0,
    }


def write_harmonization(cursor, spot_id: int, payload: dict) -> None:
    """
    Enregistre en base le résultat de Claude pour un spot, avec la version du
    prompt utilisée. La colonne `description` n'apparaît pas dans la requête :
    elle n'est jamais touchée.

    Garde-fou : a_verifier et nuit_interdite ne repassent jamais de 1 à 0 ici. Si
    l'agent ne confirme plus une interdiction de nuit, elle reste et le spot part en
    vérification. MySQL applique le SET dans l'ordre : a_verifier doit donc venir
    avant nuit_interdite, pour lire son ancienne valeur.
    """
    fields = normalize(payload)
    cursor.execute(
        """
        UPDATE spots
        SET description_ia = %s,
            a_verifier = GREATEST(COALESCE(a_verifier, 0), %s, COALESCE(nuit_interdite, 0) > %s),
            nuit_interdite = GREATEST(COALESCE(nuit_interdite, 0), %s),
            harmonized_at = NOW(),
            prompt_version = %s
        WHERE id = %s
        """,
        (fields["description_ia"], fields["a_verifier"], fields["nuit_interdite"], fields["nuit_interdite"],
         PROMPT_VERSION, spot_id),
    )
    write_services(cursor, spot_id, payload.get("services") or [])


def write_services(cursor, spot_id: int, service_names: list) -> None:
    """
    Complète les badges du spot avec les services cités dans le texte.

    - On efface d'abord les services ajoutés par une harmonisation précédente
      (source 'ia') : en cas de nouveau prompt, on repart de zéro.
    - On ajoute ensuite les services cités, avec source 'ia'. INSERT IGNORE ne
      fait rien si le service est déjà lié au spot : un service coché sur
      Park4Night garde donc sa source 'p4n'.
    Les lignes 'p4n' ne sont jamais touchées.
    """
    cursor.execute("DELETE FROM spot_service WHERE spot_id = %s AND source = 'ia'", (spot_id,))
    for name in service_names:
        service_id = ServiceUtil.get_or_create_service_with_category(cursor, name)
        cursor.execute(
            "INSERT IGNORE INTO spot_service (spot_id, service_id, source) VALUES (%s, %s, 'ia')",
            (spot_id, service_id),
        )


def _database_name() -> str:
    """Nom de la base MySQL, lu dans le .env."""
    ServiceUtil.load_env()
    return ServiceUtil.get_env("DB_NAME")


# =============================================================================
# 3. LES TROIS FAÇONS DE LANCER L'HARMONISATION
# =============================================================================

def run_sample(sample: int = None, service=None, spot_ids: list = None, only_new: bool = False) -> None:
    """
    Harmonise les spots UN PAR UN (une requête à Claude par spot).

    - sample = 20         -> seulement les 20 premiers spots à harmoniser (pour tester)
    - sample = None       -> tous les spots à harmoniser
    - spot_ids = [31, 44] -> exactement ces spots (option --id)
    - only_new = True     -> seulement les spots jamais traités (ETL)

    On enregistre en base (commit) après chaque spot : si le script s'arrête en
    route (Ctrl+C, quota atteint...), rien n'est perdu, et au prochain lancement
    les spots déjà faits sont passés grâce à leur `prompt_version`.
    """
    if service is None:
        service = make_llm_service("harmonize_spots")

    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    update_spots_columns(cursor, _database_name())
    update_spot_service_table(cursor, _database_name())
    connection.commit()

    for spot in fetch_spots_to_harmonize(cursor, limit=sample, spot_ids=spot_ids, only_new=only_new):
        try:
            payload = harmonize_one(service, spot)
        except (LLMUnavailable, json.JSONDecodeError) as error:
            # Un échec sur un spot ne doit pas arrêter tout le traitement.
            logger.warning(f"[harmonize] Spot {spot['id']} ignoré : {error}")
            continue

        write_harmonization(cursor, spot["id"], payload)
        connection.commit()
        logger.info(
            f"[harmonize] #{spot['id']} {payload.get('description') or '(rien d’utile)'}"
            f" | services cités : {', '.join(payload.get('services') or []) or 'aucun'}"
            f"{' | ⚠ À VÉRIFIER' if payload.get('a_verifier') else ''}"
            f"{' | ⛔ NUIT INTERDITE' if payload.get('nuit_interdite') else ''}"
            f"{' | ❓ DOUTE NUIT : ' + payload.get('doute_nuit_raison', '') if payload.get('doute_nuit') else ''}"
        )

    cursor.close()
    MySQLUtils.disconnect(connection)


def submit_backfill() -> str:
    """
    Envoie TOUS les spots à harmoniser en un seul lot (Batch API, 50 % moins cher).
    Anthropic traite le lot en arrière-plan. Renvoie l'identifiant du lot, à
    réutiliser ensuite avec --collect.
    """
    service = make_llm_service("harmonize_spots", chosen_engine=ENGINE_API)

    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    update_spots_columns(cursor, _database_name())
    update_spot_service_table(cursor, _database_name())
    connection.commit()
    spots = fetch_spots_to_harmonize(cursor)
    cursor.close()
    MySQLUtils.disconnect(connection)

    if not spots:
        logger.info("[harmonize] Rien à harmoniser")
        return ""

    # Une requête par spot. L'étiquette "spot-<id>" permettra de retrouver
    # à quel spot correspond chaque réponse.
    requests = []
    for spot in spots:
        requests.append(service.build_batch_request(
            custom_id=f"spot-{spot['id']}",
            system=SYSTEM_PROMPT,
            user=build_user_message(spot),
            schema=SPOT_SCHEMA,
        ))

    batch_id = service.submit_batch(requests)
    logger.info(f"[harmonize] Lot {batch_id} envoyé : relancer avec --collect {batch_id}")
    return batch_id


def collect_backfill(batch_id: str) -> int:
    """
    Récupère les réponses d'un lot envoyé avec --submit et les enregistre en base.
    Renvoie le nombre de spots harmonisés (0 si le lot n'est pas encore terminé).

    Attention : ne pas modifier le prompt entre --submit et --collect, sinon les
    réponses (faites avec l'ancien prompt) seraient enregistrées avec la nouvelle version.
    """
    service = make_llm_service("harmonize_spots", chosen_engine=ENGINE_API)
    if not service.batch_finished(batch_id):
        logger.info(f"[harmonize] Lot {batch_id} encore en cours, réessayer plus tard")
        return 0

    payloads = service.fetch_batch_results(batch_id)  # {"spot-12": {...}, ...}

    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    for custom_id, payload in payloads.items():
        spot_id = int(custom_id.removeprefix("spot-"))  # "spot-12" -> 12
        write_harmonization(cursor, spot_id, payload)
    connection.commit()
    cursor.close()
    MySQLUtils.disconnect(connection)

    logger.info(f"[harmonize] {len(payloads)} spot(s) harmonisé(s) depuis le lot {batch_id}")
    return len(payloads)


# =============================================================================
# 4. LANCEMENT EN LIGNE DE COMMANDE
# =============================================================================

def main():
    # argparse lit les options tapées après le nom du script (--sample 20, etc.).
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, help="Harmoniser N spots, un par un")
    parser.add_argument("--all", action="store_true", help="Harmoniser tous les spots, un par un")
    parser.add_argument("--id", type=int, nargs="+", metavar="SPOT_ID",
                        help="Harmoniser ces spots précis, même déjà faits (ex : --id 31 44)")
    parser.add_argument("--submit", action="store_true", help="Envoyer tous les spots en un lot (API)")
    parser.add_argument("--collect", metavar="BATCH_ID", help="Récupérer les résultats d'un lot (API)")
    parser.add_argument(
        "--engine", choices=[ENGINE_API, ENGINE_CLAUDE_CODE],
        help="api : clé ANTHROPIC_API_KEY ; claude-code : programme `claude` + abonnement (défaut : LLM_ENGINE)",
    )
    parser.add_argument("--model", help="Modèle à utiliser (par défaut : celui du service choisi)")
    args = parser.parse_args()

    # Choix de la façon d'appeler Claude, et éventuellement du modèle.
    chosen_engine = args.engine or engine()
    service = make_llm_service("harmonize_spots", chosen_engine=chosen_engine, model=args.model)

    # Les lots n'existent qu'avec l'API.
    if chosen_engine == ENGINE_CLAUDE_CODE and (args.submit or args.collect):
        parser.error("--submit et --collect ne marchent qu'avec l'API (--engine api)")

    if args.id:
        run_sample(None, service, spot_ids=args.id)
    elif args.sample:
        run_sample(args.sample, service)
    elif args.all:
        run_sample(None, service)
    elif args.submit:
        submit_backfill()
    elif args.collect:
        collect_backfill(args.collect)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
