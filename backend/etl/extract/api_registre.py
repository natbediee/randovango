"""
Ce que les registres officiels disent des restaurants d'une commune : SIRENE, puis le BODACC.
Les commerces (agents/find_commerces.py) lisent le même registre avec leurs propres codes d'activité.

UN INDICE POUR LES AGENTS, JAMAIS UNE PREUVE
Test du 3 novembre 2026 sur Plougonvelin et Le Conquet, même prompt, 3 recherches avec et 3 sans : NOUS, Riboul et
La Maison du Phare ne sortent qu'avec le registre. Mais il ne sait pas tout : La Balise et Bistrot 1954 n'y figurent pas
sous ces noms, « actif » ne prouve pas qu'un lieu soit ouvert, et une société fermée n'est pas toujours un lieu fermé
(CHADI R a fermé, la table La Corniche continue). L'absence d'un lieu ne prouve donc rien.

SIRENE GARDE DES ÉTABLISSEMENTS ACTIFS À TORT
Le 18 rue Saint-Yves y reste actif, alors que le BODACC publie sa radiation en 2023. On lit donc la dernière annonce
de chaque société encore active, hors dépôts des comptes : Breizh Crépier a une radiation en 2022 et une création en 2024.

LE FILTRE « ACTIF » EST FAIT ICI, ÉTABLISSEMENT PAR ÉTABLISSEMENT
Celui de l'API porte sur l'entreprise : une entreprise active peut avoir un établissement fermé.

PARIS, LYON ET MARSEILLE SE LISENT AUTOUR DE LEURS ZONES
Le registre range chaque établissement sous le code de son arrondissement, jamais sous celui de la commune. Lu avec
13055, le registre de Marseille était vide (12 novembre 2026) : la ville, prise pour une petite commune, a été cherchée
sans zones, et n'a reçu que 34 restaurants. Le 1er arrondissement seul (13201) en compte 1 150 au registre.
Le lire en entier ne sert à rien : Marseille compte 20 900 sociétés aux codes des restaurants, et seuls les abords des
spots sont cherchés. Le registre y est donc lu autour de chaque zone (près de 450 sociétés pour une zone du 8e), puis réuni.
Au centre, une zone de 1,5 km en compte encore 7 100, alors que l'agent n'en lit que les 40 lignes les plus proches du
spot : le rayon de lecture y est réduit de moitié tant qu'il reste plus de NEAR_CAP sociétés (near_radius). Un lieu
trouvé plus loin dans la zone n'a alors pas sa ligne du registre : sa preuve est cherchée sur le web.

UN APPEL QUI ÉCHOUE EST REPRIS
Le registre d'une grande ville, ce sont des milliers d'appels (une annonce du BODACC par société) : un seul échec
faisait abandonner tout le registre. Un appel sans réponse, ou refusé pour le moment (429, 5xx), est repris après une
attente de plus en plus longue (RETRY_PAUSES).

Le nom d'un entrepreneur individuel n'est jamais gardé : c'est celui d'une personne.
Si un registre ne répond toujours pas, une petite commune est cherchée sans lui ; une grande ville ne l'est pas
(service_chain.must_have_register).
"""
import json
import re
import time

import requests

from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("agent_restaurants")

COMMUNE_URL = "https://geo.api.gouv.fr/communes"
SIRENE_URL = "https://recherche-entreprises.api.gouv.fr/search"
NEAR_URL = "https://recherche-entreprises.api.gouv.fr/near_point"      # les mêmes réponses, autour d'un point
BODACC_URL = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"

ACTIVITIES = ("56.10A", "56.10B", "56.10C", "56.21Z", "56.29A", "56.29B", "56.30Z", "55.10Z")
INDIVIDUAL_FORM = "1000"        # nature juridique d'un entrepreneur individuel
CLOSED_YEARS_KEPT = 5           # une enseigne fermée depuis plus longtemps n'aide plus personne
TIMEOUT_SECONDS = 30
PAUSE_SECONDS = 0.2             # l'API limite à 7 requêtes par seconde
RETRY_PAUSES = (2, 10, 30)      # les attentes avant de reprendre un appel qui a échoué
NEAR_CAP = 500                  # autour d'une zone, le rayon de lecture est réduit tant qu'il reste plus de sociétés
MIN_RADIUS_KM = 0.2             # en dessous, on ne réduit plus : il faut encore de quoi lire les lignes proches du spot
COLLECTIVE_NOTICES = "Procédures collectives"
SALE_NOTICES = "Ventes et cessions"
STRIKE_OFF_NOTICES = "Radiations"
# Les trois communes à arrondissements : {code de la commune : codes de ses arrondissements}.
BOROUGHS = {"75056": tuple(f"751{number:02d}" for number in range(1, 21)),
            "69123": tuple(f"6938{number}" for number in range(1, 10)),
            "13055": tuple(f"132{number:02d}" for number in range(1, 17))}


def _get(url: str, params: dict) -> dict:
    """Un appel à un registre, repris s'il reste sans réponse ou s'il est refusé pour le moment. Lève à la dernière reprise."""
    for pause in (PAUSE_SECONDS, *RETRY_PAUSES):
        time.sleep(pause)
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS, headers={"User-Agent": "randovango"})
        except (requests.ConnectionError, requests.Timeout) as error:
            failure = error
            continue
        if response.status_code == 429 or response.status_code >= 500:
            failure = requests.HTTPError(f"{response.status_code} pour {url}", response=response)
            continue
        response.raise_for_status()
        return response.json()
    raise failure


def commune_code(latitude: float, longitude: float) -> str | None:
    """Le code INSEE de la commune qui contient ce point, pour une ville dont cities ne le garde pas encore."""
    rows = _get(COMMUNE_URL, {"lat": latitude, "lon": longitude, "fields": "code"})
    return rows[0]["code"] if rows else None


def last_notice(siren: str) -> dict:
    """La dernière annonce qui dit quelque chose d'une société : (famille, date, nature du jugement)."""
    rows = _get(BODACC_URL, {"where": f'registre like "{siren}" AND familleavis_lib != "Dépôts des comptes"',
                             "limit": 1, "order_by": "dateparution desc",
                             "select": "dateparution,familleavis_lib,jugement"})["results"]
    if not rows:
        return {}
    judgment = json.loads(rows[0]["jugement"]).get("nature") if rows[0].get("jugement") else None
    return {"famille": rows[0]["familleavis_lib"], "date": rows[0]["dateparution"], "jugement": judgment}


def place_name(establishment: dict, firm: dict) -> str | None:
    """L'enseigne, sinon le nom commercial, sinon le nom de la société. Jamais le nom d'une personne."""
    signs = establishment.get("liste_enseignes") or []
    name = (signs[0] if signs else None) or establishment.get("nom_commercial")
    if name or str(firm.get("nature_juridique")) == INDIVIDUAL_FORM:
        return name
    return firm.get("nom_raison_sociale") or firm.get("nom_complet")


def add_establishment(register: dict, establishment: dict, firm: dict, notice: dict, oldest_closure: str) -> None:
    """Range un établissement : actif avec son signal, radié, enseigne fermée récente, ou rien."""
    line = {"nom": place_name(establishment, firm), "adresse": establishment.get("adresse"),
            "activite": establishment.get("activite_principale")}
    # La position découpe une grande ville en zones (find_restaurants.py) ; l'agent ne la lit pas. Un établissement
    # non diffusible donne « [NON-DIFFUSIBLE] » à la place : sa ligne reste, sans position (Brest, 6 novembre 2026).
    position = establishment.get("latitude"), establishment.get("longitude")
    if all(re.fullmatch(r"-?\d+(\.\d+)?", str(value or "")) for value in position):
        line["position"] = [float(value) for value in position]
    if establishment.get("etat_administratif") != "A":
        closed_on = establishment.get("date_fermeture") or ""
        if line["nom"] and closed_on >= oldest_closure:
            register["enseignes_fermees"].append({**line, "ferme_le": closed_on})
        return
    if notice.get("famille") == STRIKE_OFF_NOTICES:
        register["radies"].append({**line, "radie_le": notice["date"]})
        return
    if notice.get("famille") in (COLLECTIVE_NOTICES, SALE_NOTICES):
        line["derniere_annonce"] = f"{notice['jugement'] or notice['famille']} ({notice['date']})"
    register["actifs"].append({**line, "actif_depuis": establishment.get("date_creation")})


def read_register(code: str, activities: tuple = ACTIVITIES, near: tuple | None = None) -> dict:
    """
    Le registre d'une commune, page après page, pour ces codes d'activité (ceux des restaurants par défaut).
    `near` : (latitude, longitude, rayon en km), pour ne lire que les établissements de la commune autour de ce point.
    """
    register = {"actifs": [], "enseignes_fermees": [], "radies": []}
    oldest_closure = str(time.gmtime().tm_year - CLOSED_YEARS_KEPT)
    # Les établissements d'une commune à arrondissements portent le code de leur arrondissement.
    codes = BOROUGHS.get(code, (code,))
    url, where = (NEAR_URL, {"lat": near[0], "long": near[1], "radius": near[2]}) if near else (SIRENE_URL, {"code_commune": code})
    notices, page = {}, 1
    while True:
        data = _get(url, {**where, "activite_principale": ",".join(activities), "per_page": 25,
                          "page": page, "limite_matching_etablissements": 100, "minimal": "true",
                          "include": "matching_etablissements"})
        for firm in data["results"]:
            for establishment in firm.get("matching_etablissements") or []:
                if establishment.get("commune") not in codes or establishment.get("activite_principale") not in activities:
                    continue
                notice = {}
                if establishment.get("etat_administratif") == "A":
                    notice = notices.setdefault(firm["siren"], last_notice(firm["siren"]))
                add_establishment(register, establishment, firm, notice, oldest_closure)
        if page >= data.get("total_pages", 1):
            return register
        page += 1


def near_radius(zone: dict, activities: tuple, radius_km: float) -> float:
    """
    Le rayon de lecture du registre autour d'une zone : radius_km, réduit de moitié tant que le registre y compte plus de
    NEAR_CAP sociétés. Autour du Vieux-Port de Marseille : 7 100 sociétés à 1,5 km, 3 000 à 750 m, 700 à 375 m, 200 à 190 m.
    """
    while radius_km > MIN_RADIUS_KM:
        found = _get(NEAR_URL, {"lat": zone["latitude"], "long": zone["longitude"], "radius": radius_km,
                                "activite_principale": ",".join(activities), "per_page": 1, "page": 1, "minimal": "true"})
        if found.get("total_results", 0) <= NEAR_CAP:
            break
        radius_km /= 2
    return radius_km


def load_register(city: dict, activities: tuple = ACTIVITIES, zones: list | tuple = (), radius_km: float = 0) -> dict | None:
    """
    Le registre de la commune, ou None s'il n'a pas pu être lu : la recherche se passe alors de lui.
    Une commune à arrondissements (BOROUGHS) est lue autour de chacune de ses zones de recherche, à radius_km ou moins
    si la zone est très dense (near_radius), puis réunie : un établissement vu de deux zones voisines n'est gardé qu'une fois.
    """
    try:
        code = city.get("insee") or commune_code(city["latitude"], city["longitude"])
        if not code:
            return None
        if code not in BOROUGHS:
            return read_register(code, activities)
        merged, seen = {"actifs": [], "enseignes_fermees": [], "radies": []}, set()
        for zone in zones:
            radius = near_radius(zone, activities, radius_km)
            if radius < radius_km:
                logger.info(f"[registre] {city['name']} : autour de « {zone.get('repere')} », lu à {round(radius * 1000)} m"
                            f" au lieu de {round(radius_km * 1000)} m")
            for kind, lines in read_register(code, activities, (zone["latitude"], zone["longitude"], radius)).items():
                for line in lines:
                    key = json.dumps(line, sort_keys=True, ensure_ascii=False)
                    if key not in seen:
                        seen.add(key)
                        merged[kind].append(line)
        return merged
    except (requests.RequestException, ValueError, KeyError) as error:
        logger.warning(f"[registre] {city['name']} : registre illisible ({error})")
        return None
