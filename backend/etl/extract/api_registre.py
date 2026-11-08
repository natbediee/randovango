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

Le nom d'un entrepreneur individuel n'est jamais gardé : c'est celui d'une personne.
Si un registre ne répond pas, la recherche continue sans lui.
"""
import json
import re
import time

import requests

from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("agent_restaurants")

COMMUNE_URL = "https://geo.api.gouv.fr/communes"
SIRENE_URL = "https://recherche-entreprises.api.gouv.fr/search"
BODACC_URL = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"

ACTIVITIES = ("56.10A", "56.10B", "56.10C", "56.21Z", "56.29A", "56.29B", "56.30Z", "55.10Z")
INDIVIDUAL_FORM = "1000"        # nature juridique d'un entrepreneur individuel
CLOSED_YEARS_KEPT = 5           # une enseigne fermée depuis plus longtemps n'aide plus personne
TIMEOUT_SECONDS = 30
PAUSE_SECONDS = 0.2             # l'API limite à 7 requêtes par seconde
COLLECTIVE_NOTICES = "Procédures collectives"
SALE_NOTICES = "Ventes et cessions"
STRIKE_OFF_NOTICES = "Radiations"


def _get(url: str, params: dict) -> dict:
    time.sleep(PAUSE_SECONDS)
    response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS, headers={"User-Agent": "randovango"})
    response.raise_for_status()
    return response.json()


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


def read_register(code: str, activities: tuple = ACTIVITIES) -> dict:
    """Le registre d'une commune, page après page, pour ces codes d'activité (ceux des restaurants par défaut)."""
    register = {"actifs": [], "enseignes_fermees": [], "radies": []}
    oldest_closure = str(time.gmtime().tm_year - CLOSED_YEARS_KEPT)
    notices, page = {}, 1
    while True:
        data = _get(SIRENE_URL, {"code_commune": code, "activite_principale": ",".join(activities), "per_page": 25,
                                 "page": page, "limite_matching_etablissements": 100, "minimal": "true",
                                 "include": "matching_etablissements"})
        for firm in data["results"]:
            for establishment in firm.get("matching_etablissements") or []:
                if establishment.get("commune") != code or establishment.get("activite_principale") not in activities:
                    continue
                notice = {}
                if establishment.get("etat_administratif") == "A":
                    notice = notices.setdefault(firm["siren"], last_notice(firm["siren"]))
                add_establishment(register, establishment, firm, notice, oldest_closure)
        if page >= data.get("total_pages", 1):
            return register
        page += 1


def load_register(city: dict, activities: tuple = ACTIVITIES) -> dict | None:
    """Le registre de la commune, ou None s'il n'a pas pu être lu : la recherche se passe alors de lui."""
    try:
        code = city.get("insee") or commune_code(city["latitude"], city["longitude"])
        return read_register(code) if code else None
        code = commune_code(city["latitude"], city["longitude"])
        return read_register(code, activities) if code else None
    except (requests.RequestException, ValueError, KeyError) as error:
        logger.warning(f"[registre] {city['name']} : registre illisible ({error})")
        return None
