"""
Le bilan de la supervision : combien il reste à trancher, file par file.

Il compte aussi les notes données aux propositions des agents (count_ratings, carte #201), pour vérifier que la
notation sert au jeu d'évaluation (#114).

Les chiffres sont comptés avec les règles mêmes des pages Spots et Services
(spots_review.spot_status, services_review._pending) : le bilan ne peut pas
annoncer ce que ces pages ne montreraient pas. Un lieu présent dans deux files compte
une fois dans chacune, comme le filtre « Problème » de la page Services, dont « Tous » fait la somme.
"""
from collections import Counter
from datetime import date

from services.supervision import rating, services_edit, services_review, spots_edit, spots_review
from utils.db_utils import MySQLUtils
from utils.display_utils import HIDDEN_SPOT_TYPES, spot_category
from utils.geo_utils import town_choices, town_key

# Les files des services (services_review.TAB_SIGNALS), avec le libellé et l'ordre du filtre
# « Problème » de la page Services (TABS dans supervision_services.js).
SERVICE_TABS = {
    "fermetures": "Doute sur le nom",
    "liens": "Liens",
    "saison": "Saison",
    "doublons": "Doublons",
    "confirmer": "À confirmer",
}
NO_CITY = "Ville inconnue"
NO_TYPE = "Type inconnu"

# Les catégories des notes : les spots, puis les onglets de l'étape 4 (services_review.step4_tab), avec les libellés
# du filtre « Type » de la page Services (SERVICE_TABS dans supervision_services.js).
RATING_CATEGORIES = {
    "spot": "Spots", "eau": "Eau", "vidange": "Vidange", "gasoil": "Carburant", "supermarche": "Supermarché",
    "commerce": "Commerce", "restauration": "Restauration", "cafe": "Café, bar", "toilettes": "Toilettes",
    "hygiene": "Hygiène", "laverie": "Laverie", "culture": "Culture & Loisirs", "urgence": "Urgences",
    "hors_etape4": "Hors étape 4",
}

# Les décisions notées et encore valables, avec la catégorie de leur lieu : un spot, ou le service d'un lieu.
RATED_DECISIONS = """
    SELECT d.objet_type, d.pertinence, d.raison,
           (SELECT MIN(s.category) FROM poi_service ps JOIN services s ON s.id = ps.service_id
            WHERE d.objet_type = %s AND ps.poi_id = d.objet_id) AS service_category
    FROM decisions d
    WHERE d.pertinence IS NOT NULL AND d.annulee_at IS NULL AND d.objet_type IN (%s, %s)
"""


def count_spots(states: dict) -> dict:
    """{statut: nombre} pour les spots qui ont une vérification ou une décision."""
    statuses = Counter(spots_review.spot_status(verification, decision)
                       for verification, decision in states.values())
    return {"a_relire": statuses["propose"], "gardes": statuses["garde"], "retires": statuses["retire"]}


def ranked(counter: Counter) -> list:
    """[{label, n}], du plus chargé au moins chargé, puis par ordre alphabétique."""
    return [{"label": label, "n": n} for label, n in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def rating_category(row: dict) -> str:
    """La catégorie d'une décision notée : « spot », ou l'onglet de l'étape 4 du lieu (« restauration »)."""
    if row["objet_type"] == spots_review.SPOT:
        return "spot"
    return services_review.step4_tab(row.get("service_category"))


def count_ratings(rows: list) -> list:
    """
    Les notes des propositions, par catégorie : [{label, n, pertinences: [{label, n}], raisons: [{label, n}]}].
    Les trois pertinences sont toujours là, dans l'ordre (0 si aucune), les raisons de la plus fréquente à la plus rare.
    Les catégories viennent dans l'ordre de RATING_CATEGORIES ; celles sans note n'apparaissent pas.
    """
    by_category = {}
    for row in rows:
        by_category.setdefault(rating_category(row), []).append(row)
    counts = []
    for category, label in RATING_CATEGORIES.items():
        rated = by_category.get(category)
        if not rated:
            continue
        pertinences = Counter(row["pertinence"] for row in rated)
        reasons = Counter(rating.RAISONS.get(row["raison"], row["raison"]) for row in rated if row["raison"])
        counts.append({
            "label": label,
            "n": len(rated),
            "pertinences": [{"label": name, "n": pertinences[value]} for value, name in rating.PERTINENCES.items()],
            "raisons": ranked(reasons),
        })
    return counts


def summarize(states: dict, spot_cities: dict, groups: dict, pois: dict, openings: int, decisions: int,
              unverified: list = ()) -> dict:
    """
    Assemble le bilan à partir de ce que la base a donné (sans y toucher : testable seul).
    unverified : les spots proposés au voyageur avec le badge « non vérifié » (spots_review._unverified_ids), à
    confirmer comme les retraits proposés sont à relire (page Spots, problème « Non vérifié »).
    """
    spots = {**count_spots(states), "non_verifies": len(unverified)}
    pending_spots = [spot_id for spot_id, (verification, decision) in states.items()
                     if spots_review.spot_status(verification, decision) == "propose"] + list(unverified)

    files = Counter(tab for tab, _ in groups)
    by_type = Counter((pois.get(poi_id) or {}).get("service") or NO_TYPE for _, poi_id in groups)
    by_city = Counter(spot_cities.get(spot_id) or NO_CITY for spot_id in pending_spots)
    by_city.update((pois.get(poi_id) or {}).get("commune") or NO_CITY for _, poi_id in groups)

    services_pending = sum(files.values())
    return {
        "total": spots["a_relire"] + spots["non_verifies"] + services_pending,
        "decisions": decisions,
        "spots": {**spots, "ouvertures": openings},
        "services": {
            "a_relire": services_pending,
            "files": [{"tab": tab, "label": label, "n": files[tab]} for tab, label in SERVICE_TABS.items()],
            "par_type": ranked(by_type),
        },
        "par_ville": ranked(by_city),
    }


# LE FILTRE DU BILAN (carte #186, 14 novembre 2026) : une ville de l'appli ou une commune, rien d'autre. La catégorie
# et le problème sont déjà les lignes du bilan (par type, par file) : un filtre ne ferait que les répéter.
# Une ville filtre ce qui reste à trancher et ce qui a été tranché sur ses spots ; le nombre total de décisions et
# les notes des propositions restent ceux de toutes les villes (la page le dit).
# Chaque page garde sa règle : un spot se range comme sur la page Spots (spots_review.spot_city), un service comme sur
# la page Services (la ville de l'étape 1 qui l'a trouvé, ou la commune de son adresse).


def spot_places(spot_labels: dict, cities: list) -> dict:
    """{numéro de spot : (identifiant de sa ville de l'appli ou None, nom de sa ville ou de sa commune)}."""
    names = {city["id"]: city["name"] for city in cities}
    places = {}
    for spot_id, spot in spot_labels.items():
        fields = spots_review._place_fields(spot, cities)
        places[spot_id] = (fields["ville_id"], names.get(fields["ville_id"]) or fields["commune"])
    return places


def spot_in_place(place: tuple, city: dict | None, town: str | None) -> bool:
    """Le spot est-il dans la ville ou la commune choisie ? Sans filtre, oui."""
    city_id, name = place
    if city:
        return city_id == city["id"]
    if town:
        return city_id is None and town_key(name) == town_key(town)
    return True


def city_search_choices(places: dict, pending_spots: list, pois: dict, cities: list) -> tuple:
    """
    Ce que la recherche de ville propose : les villes de l'appli et les communes qui ont quelque chose à trancher,
    spots et services réunis, avec leurs codes postaux (supervision_ville.js).
    """
    by_name = {city["name"]: city for city in cities}
    city_names = {places[spot_id][1] for spot_id in pending_spots if places.get(spot_id, (None,))[0] is not None}
    city_names |= {poi["commune"] for poi in pois.values() if poi.get("commune")}
    town_names = {places[spot_id][1] for spot_id in pending_spots
                  if spot_id in places and places[spot_id][0] is None and places[spot_id][1]}
    city_codes, address_towns = town_choices([poi["address"] for poi in pois.values() if poi.get("address")],
                                             [{**city, "id": city["name"]} for city in cities])
    offered = [{"id": by_name[name]["id"], "name": name, "codes": city_codes.get(name, [])}
               for name in sorted(city_names) if name in by_name]
    towns = {town_key(town["nom"]): town for town in address_towns}
    for name in town_names:
        towns.setdefault(town_key(name), {"nom": name, "codes": []})
    return offered, [town for _, town in sorted(towns.items())]


# LE BILAN DE CE QU'IL Y A (14 novembre 2026) : le bilan dit aussi ce que la base a, pas seulement ce qui reste à
# trancher ; dans toute la base, ou dans la ville ou la commune choisie. Les spots et les services sont ceux que l'onglet « Modifier » trouve pour cette
# ville (spots_edit._search_rows, services_edit._search_rows) : la commune de l'adresse, sinon la ville la plus proche.
# Les catégories des spots proposés au voyageur. « Autres » n'y figure pas : depuis que les aires de pique-nique sont
# masquées (14 novembre 2026), tous les spots de cette catégorie sont des lieux où l'on ne dort pas, donc masqués.
SPOT_CATEGORY_LABELS = {"gratuit": "Gratuit", "payant": "Payant"}


# Pourquoi un spot n'est pas proposé au voyageur, dans l'ordre où l'étape 3 l'écarte (proposable_spots) : son type
# (on n'y dort pas : services d'appoint, aire de services sans stationnement, parking de jour, ou pas de type), la nuit
# interdite, puis une décision (retiré par un humain, ou dont l'agent propose le retrait, à relire). Un spot dont
# l'agent doute (« incertain ») reste proposé, avec le badge « non vérifié » : il compte dans les non vérifiés.
HIDDEN_SPOT_REASONS = {"sans_nuit": "On n'y dort pas (services, parking de jour, pique-nique)",
                       "nuit_interdite": "Nuit interdite", "decision": "Retirés ou à relire"}


def spot_hidden_reason(row: dict, hidden_ids: set) -> str | None:
    """La raison pour laquelle l'étape 3 ne propose pas ce spot (HIDDEN_SPOT_REASONS), None s'il est proposé."""
    if not row.get("type") or row["type"] in HIDDEN_SPOT_TYPES:
        return "sans_nuit"
    if row.get("nuit_interdite"):
        return "nuit_interdite"
    if row["id"] in hidden_ids:
        return "decision"
    return None


def inventory(spot_rows: list, service_rows: list, place: str, hidden_ids: set) -> dict:
    """
    Ce qu'il y a dans la ville choisie (ou toute la base), compté à partir des lignes lues en base (testable seul).
    hidden_ids : les spots qu'une décision écarte aujourd'hui (spots_review.hidden_spot_ids). Les catégories et la
    vérification ne comptent que les spots proposés au voyageur ; les dates d'ouverture, qui dépendent de la nuit du
    voyage, ne sont pas comptées.
    """
    reasons = Counter(spot_hidden_reason(row, hidden_ids) for row in spot_rows)
    proposed = [row for row in spot_rows if spot_hidden_reason(row, hidden_ids) is None]
    categories = Counter(spot_category(row.get("type")) for row in proposed)
    verified = sum(1 for row in proposed if row.get("verifie"))
    tabs = Counter(services_review.step4_tab(row.get("service_category")) for row in service_rows)
    # Un service masqué, ou rangé hors de l'étape 4 (lavoir, église, fortification : aucun onglet ne le montre),
    # n'est pas vu du voyageur : les deux comptent dans les masqués.
    masked = sum(1 for row in service_rows
                 if row.get("masque") or services_review.step4_tab(row.get("service_category")) == services_review.NO_TAB)
    return {
        "lieu": place,
        "spots": {
            "total": len(spot_rows),
            "proposes": len(proposed),
            "par_categorie": [{"label": label, "n": categories[code]} for code, label in SPOT_CATEGORY_LABELS.items()],
            "verifies": verified,
            "non_verifies": len(proposed) - verified,
            "masques": len(spot_rows) - len(proposed),
            "masques_par_raison": [{"label": label, "n": reasons[code]} for code, label in HIDDEN_SPOT_REASONS.items()],
        },
        "services": {
            "total": len(service_rows),
            "affiches": len(service_rows) - masked,
            "masques": masked,
            "saisonniers": sum(1 for row in service_rows if row.get("statut_saison")),
            "par_type": ranked(Counter({RATING_CATEGORIES.get(tab, tab): n for tab, n in tabs.items()})),
        },
    }


ALL_PLACES = "toute la base"


def city_inventory(cursor, city: dict | None, town: str | None, cities: list, hidden_ids: set) -> dict:
    """Ce qu'il y a dans la ville ou la commune choisie ; sans filtre, dans toute la base."""
    spot_rows = spots_edit._search_rows(cursor, city, "", cities)
    if not city and not town:
        return inventory(spot_rows, services_edit._search_rows(cursor, None, "", cities), ALL_PLACES, hidden_ids)
    if not city:
        # Une commune qui n'est pas une ville de l'appli : les spots dont c'est la commune.
        spot_rows = [row for row in spot_rows if town_key(spots_review.spot_town(row)) == town_key(town)]
    service_rows = services_edit._search_rows(cursor, city, "", cities, town)
    return inventory(spot_rows, service_rows, city["name"] if city else town, hidden_ids)


def get_summary(city_id: int | None = None, town: str | None = None) -> dict:
    """
    Le bilan lu en base : ce qui reste à trancher, file par file, et le compte des notes des propositions.
    city_id : une ville de l'appli ; town : une commune qui n'en est pas une. Une ville inconnue est refusée.
    """
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, name, commune, latitude, longitude FROM cities ORDER BY name")
        cities = cursor.fetchall()
        city = next((row for row in cities if row["id"] == city_id), None)
        if city_id is not None and not city:
            raise ValueError(f"Ville inconnue : {city_id}")
        all_states = spots_review._spot_states(cursor)
        all_unverified = spots_review._unverified_ids(cursor, all_states)
        places = spot_places(spots_review._spot_labels(cursor, list({*all_states, *all_unverified})), cities)
        all_groups, all_pois = services_review._pending(cursor, None, None)
        pending_spots = [spot_id for spot_id, (verification, decision) in all_states.items()
                         if spots_review.spot_status(verification, decision) == "propose"] + all_unverified
        choices = city_search_choices(places, pending_spots, all_pois, cities)

        states = {spot_id: state for spot_id, state in all_states.items()
                  if spot_in_place(places.get(spot_id, (None, None)), city, town)}
        unverified = [spot_id for spot_id in all_unverified
                      if spot_in_place(places.get(spot_id, (None, None)), city, town)]
        spot_cities = {spot_id: places.get(spot_id, (None, None))[1] for spot_id in [*states, *unverified]}
        groups, pois = services_review._pending(cursor, None, city["name"] if city else None, town=town)
        cursor.execute("SELECT objet_id FROM decisions WHERE objet_type = %s AND annulee_at IS NULL",
                       (spots_review.OPENING_OBJECT,))
        openings = sum(1 for row in cursor.fetchall()
                       if spot_in_place(places.get(row["objet_id"], (None, None)), city, town))
        cursor.execute("SELECT COUNT(*) AS n FROM decisions WHERE annulee_at IS NULL")
        decisions = cursor.fetchone()["n"]
        # Le service n'est cherché que pour un lieu (poi) : un numéro de spot n'est pas un numéro de lieu.
        cursor.execute(RATED_DECISIONS, (services_review.POI, spots_review.SPOT, services_review.POI))
        ratings = count_ratings(cursor.fetchall())
        hidden_ids = spots_review.hidden_spot_ids(connection, cursor, date.today())
        place = city_inventory(cursor, city, town, cities, hidden_ids)
        cursor.close()
        cities_offered, towns = choices
        return {**summarize(states, spot_cities, groups, pois, openings, decisions, unverified), "notation": ratings,
                "cities": cities_offered, "towns": towns, "ville": place}
    finally:
        MySQLUtils.disconnect(connection)
