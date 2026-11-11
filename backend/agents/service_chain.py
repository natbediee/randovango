"""
La chaîne commune des agents qui cherchent les services d'une commune : écrite une fois, réglée par catégorie
(service_category.py ; find_restaurants.py et find_commerces.py en sont les réglages). Une règle corrigée ici l'est pour
toutes : avant le 11 novembre 2026, chaque catégorie avait sa copie, et la règle du badge « Vérifié » avait été écrite
deux fois.

LA CHAÎNE, POUR UNE COMMUNE OU POUR UNE ZONE D'UNE GRANDE VILLE (search_zone)
    1. les recherches de la catégorie partent en même temps, avec le registre comme indice, puis sont réunies ;
    2. le code contrôle les pages qu'elles ont trouvées ;
    3. l'analyste relit tous les lieux : fermeture, doublon, lieu inutile au voyageur, détails ;
    4. seuls les lieux que ni une page ni le registre ne prouvent partent chercher une preuve, par petits lots ;
    5. le code contrôle les détails, puis lit la preuve et la date « nouveau » dans le registre entier.
Chaque étape est gardée dans un fichier JSON (write_trace) : la relire ne coûte aucun appel.
Pourquoi plusieurs recherches, pourquoi la preuve vient après, pourquoi rien n'est jeté : voir find_restaurants.py, où ces
choix sont nés.

L'ANALYSTE EST UN AGENT À PART
Demander tout à la même recherche semblait lui coûter des adresses. Celui-ci part d'une liste : il ne cherche
aucun nouveau lieu, il lit ce qui existe sur chacun.

UN DÉTAIL SANS CITATION RETROUVÉE N'EST PAS ENREGISTRÉ
Personne ne relira 130 villes. Saison, distinction et jours d'un marché ne sont donc gardés que si le code retrouve la
phrase sur une page acceptée, et que cette phrase contient bien l'information. Le code vérifie ainsi que la page le dit,
pas qu'elle a raison : pour Keringar, la phrase « De mars à novembre » est bien sur la page de l'office de tourisme.
Le budget et les jours de fermeture d'un restaurant ne sont plus cherchés : sur 5 passages, un seul budget et un seul
jour de fermeture ont passé ce contrôle. Le lien du lieu reste le recours du voyageur.

UNE FERMETURE LUE PAR L'ANALYSTE RETIRE LE LIEU
Sauf si le code lit la page et n'y trouve pas la phrase citée. Quand les recherches se contredisent, c'est ici
que la fermeture est relue. Un annuaire ne suffit pas : le statut d'une société n'est pas celui du lieu.
Il faut une page : le registre seul ne retire aucun lieu. Une liquidation, ou une enseigne fermée sans successeur du même
nom, donne une "alerte_registre" : le lieu attend une relecture au lieu d'être montré.

LA PREUVE VIENT À PART, PAR PETITS LOTS
Au pilote du 3 novembre 2026, un seul appel pour 17 lieux n'a laissé qu'environ 9 s par lieu, et 8 sont restés sans page.
Seuls les lieux que le code n'a pas pu accepter passent par find_proofs.
Un lot qui dépasse son délai est relancé lieu par lieu : à Ploudalmézeau, le 7 novembre 2026, cinq bars sans page ont
fait échouer la commune trois fois, et les vrais restaurants du lot avec eux. Un lieu seul qui dépasse encore son délai
n'est pas écarté : il attend une relecture humaine (signal a_confirmer), car l'agent n'a rien conclu.

UN DOUBLON DOIT ÊTRE À LA MÊME ADRESSE, ET L'AGENT DIT LEQUEL
Le nom ne le montre pas : Laer-Mor était le nom des Boucaniers, Sainte-Barbe l'hôtel de La Corniche. L'adresse ne
suffit pas : l'Hostellerie et le Bistrot 1954 partagent la leur et sont deux tables. Elle reste une condition :
deux adresses différentes ne sont jamais fusionnées, quitte à garder un doublon plutôt que perdre un lieu.
"""
import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from agents.find_service_links import check_links_of, citation_found
from agents.llm_config import make_llm_service, model_of
from agents.llm_service import LLMTimeout, mesure_objet
from agents.pepite_common import is_excluded_site
from etl.extract import api_registre
from services import service_store
from utils.geo_utils import city_commune, haversine_distance_km

MAX_PLACES = 15
YEAR_SEARCHES = 3
SEARCH_PAGE_TYPES = ["site", "office_tourisme", "guide", "presse", "facebook", "instagram", "mairie", "agregateur"]
PROOF_PAGE_TYPES = ["site", "office_tourisme", "guide", "presse", "facebook", "instagram", "mairie"]
# Une grande ville, par zones autour de ses spots : le registre de Brest (733 lignes actives, 145 Ko) ne tenait pas
# dans la commande, et 15 lieux pour toute la ville auraient été pris au hasard. Le 6 novembre 2026, ses 44 spots
# font 10 zones de 1,5 km ; trois comptent 178 à 270 restaurants au registre, d'où les 40 lignes les plus proches du spot.
ZONE_FROM = 100      # au-delà de 100 lignes actives au registre, la commune est cherchée par zones
ZONE_KM = 1.5
ZONE_LINES = 40
PROOF_BATCH = 5
PROOF_TIMED_OUT = "preuve : l'agent n'a pas répondu à temps"
MONTHS = tuple(service_store.name_key(month) for month in service_store.FRENCH_MONTHS)
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

TEXT = {"type": ["string", "null"]}


# --- Les réponses attendues des agents ---

def search_schema(category) -> dict:
    """La réponse d'une recherche : les lieux retenus, chacun rangé dans la grille de la catégorie, et les écartés."""
    key, categories = category.key, category.categories
    return {
        "type": "object", "additionalProperties": False, "required": [key, "ecartes"],
        "properties": {
            key: {"type": "array", "maxItems": MAX_PLACES, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["nom", "genre", "categorie", "adresse", "ancien_nom", "pourquoi", "lien", "type_lien", "preuve_url",
                             "type_preuve", "preuve_citation", "preuve_date"],
                "properties": {
                    "nom": {"type": "string"}, "genre": {"type": "string"}, "categorie": {"enum": categories},
                    "adresse": TEXT, "ancien_nom": TEXT,
                    "pourquoi": {"type": "string"}, "lien": {"type": "string"}, "type_lien": {"enum": SEARCH_PAGE_TYPES},
                    "preuve_url": {"type": "string"}, "type_preuve": {"enum": SEARCH_PAGE_TYPES},
                    "preuve_citation": TEXT, "preuve_date": TEXT,
                }}},
            "ecartes": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["nom", "adresse", "raison", "ferme", "page"],
                "properties": {"nom": {"type": "string"}, "adresse": TEXT, "raison": {"type": "string"},
                               "ferme": {"type": "boolean"}, "page": TEXT}}},
        },
    }


def analysis_schema(category) -> dict:
    """La réponse de l'analyste, lieu par lieu, avec le champ qui retire un lieu inutile au voyageur."""
    not_for_travellers, detail_fields = category.not_for_travellers, list(category.detail_fields)
    return {
        "type": "object", "additionalProperties": False, "required": ["lieux"],
        "properties": {"lieux": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["numero", "ferme", "ferme_page", "ferme_citation", "doublon_de", "doublon_raison", not_for_travellers,
                         "alerte_registre", "adresse", "details"],
            "properties": {
                "numero": {"type": "integer"}, "ferme": {"type": "boolean"}, "ferme_page": TEXT, "ferme_citation": TEXT,
                not_for_travellers: {"type": "boolean"}, "alerte_registre": TEXT, "adresse": TEXT,
                "doublon_de": {"type": ["integer", "null"]}, "doublon_raison": TEXT,
                "details": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["champ", "valeur", "citation", "page", "type_page"],
                    "properties": {"champ": {"enum": detail_fields}, "valeur": TEXT, "citation": {"type": "string"},
                                   "page": {"type": "string"}, "type_page": {"enum": PROOF_PAGE_TYPES}}}},
            }}}},
    }


PROOF_TYPES = {"enum": [*PROOF_PAGE_TYPES, None]}
PROOF_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["lieux"],
    "properties": {"lieux": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["numero", "preuve_url", "type_preuve", "preuve_citation", "preuve_date", "lien", "type_lien", "adresse"],
        "properties": {"numero": {"type": "integer"}, "preuve_url": TEXT, "type_preuve": PROOF_TYPES, "preuve_citation": TEXT,
                       "preuve_date": TEXT, "lien": TEXT, "type_lien": PROOF_TYPES, "adresse": TEXT}}}},
}


# --- Les réponses des recherches, réunies ---

def found_pages(row: dict) -> list:
    """Les pages d'une réponse : le lien montré, puis la preuve, qui porte la citation et la date."""
    return [{"url": row["lien"], "type_page": row["type_lien"]},
            {"url": row["preuve_url"], "type_page": row["type_preuve"], "citation": row.get("preuve_citation"), "date_page": row.get("preuve_date")}]


def unique_pages(pages: list) -> list:
    """Chaque adresse une fois. La citation et la date d'une preuve complètent la même adresse citée en simple lien."""
    by_url = {}
    for page in pages:
        known = by_url.setdefault(page["url"].strip(), {**page, "url": page["url"].strip()})
        for field in ("citation", "date_page"):
            known[field] = known.get(field) or page.get(field)
    return list(by_url.values())


def merge_answers(category, *answers: dict) -> dict:
    """
    Les recherches, sans doublon : à nom égal, la première fiche est gardée, avec les pages de toutes. Un lieu retenu par
    une recherche et dit fermé par une autre porte "dit_ferme" pour que l'analyste tranche. Seule une fermeture compte :
    la recherche d'été écarte aussi les lieux ouverts toute l'année, qui restent de bonnes adresses.
    """
    closed = {category.place_key(row["nom"]): row for answer in answers for row in answer["ecartes"] if row["ferme"]}
    places = {}
    for row in (row for answer in answers for row in answer[category.key]):
        key = category.place_key(row["nom"])
        place = places.setdefault(key, {**row, "pages_vues": [], **({"dit_ferme": closed[key]} if key in closed else {})})
        place["pages_vues"] += found_pages(row)
    return {category.key: list(places.values()), "ecartes": [row for answer in answers for row in answer["ecartes"]]}


def merge_zones(category, answers: list) -> dict:
    """Un lieu vu depuis deux zones voisines n'est gardé qu'une fois, avec la fiche de la première."""
    places = {}
    for row in (row for answer in answers for row in answer[category.key]):
        places.setdefault(category.place_key(row["nom"]), row)
    return {category.key: list(places.values()), "ecartes": [row for answer in answers for row in answer["ecartes"]]}


def clean_name(name: str) -> str:
    """« Le Pêcheur (18 rue Saint-Yves) » ou « L'Archipel - Hôtel du Large » -> le nom seul : il reconnaît le lieu et s'affiche."""
    return re.split(r"\s+[-–/]\s+", re.sub(r"\s*\([^)]*\)\s*$", "", name).strip())[0] or name


# --- Le contrôle des pages par le code ---

def control_row(category, row: dict, commune: str) -> list:
    """Les pages d'un lieu contrôlées par le code : celles de toutes les recherches, ou de cette seule réponse."""
    commune_name, postcode = service_store.commune_of_address(row.get("adresse"), commune)
    place = {"name": row["nom"], "commune": commune_name, "cp": postcode, "telephone": None}
    pages = unique_pages(row.get("pages_vues") or found_pages(row))
    links = check_links_of({"liens": [{"url": page["url"], "type_page": page["type_page"]} for page in pages],
                                  "autre_nom": row.get("ancien_nom")}, place)
    for link, page in zip(links, pages):
        if page.get("citation") or page.get("date_page"):
            link["citation"] = page.get("citation")
            link["citation_trouvee"] = citation_found(page.get("citation"), page["url"])
            link["date_page"] = page.get("date_page")
    return links


def has_accepted_page(category, row: dict, commune: str) -> bool:
    return any(category.accepts(page, row, commune) for page in row["pages"])


def add_proofs(category, row: dict, proof: dict, commune: str) -> None:
    """Les pages de l'analyste s'ajoutent à celles déjà trouvées : aucune n'est jetée."""
    if proof.get("a_relire"):
        row["a_relire"] = proof["a_relire"]
    if proof.get("adresse") and not row.get("adresse"):
        row["adresse"] = proof["adresse"]
    if not proof.get("preuve_url"):
        return
    found = {"lien": proof.get("lien") or proof["preuve_url"], "type_lien": proof.get("type_lien") or proof["type_preuve"],
             "preuve_url": proof["preuve_url"], "type_preuve": proof["type_preuve"],
             "preuve_citation": proof.get("preuve_citation"), "preuve_date": proof.get("preuve_date")}
    known = {page["url"].strip() for page in row["pages"]}
    row["pages"] += [page for page in control_row(category, {**row, **found, "pages_vues": None}, commune) if page["url"].strip() not in known]


# --- Le message, le registre et les zones ---

def build_message(city: dict, register: dict | None, zone: dict | None = None) -> str:
    message = f"COMMUNE : {city_commune(city)}, {city.get('department') or 'France'}"
    if zone:
        message += f"\nZONE : à moins de {ZONE_KM} km de {zone['repere']} ({zone['latitude']:.5f}, {zone['longitude']:.5f})"
    return f"{message}\nREGISTRE : {json.dumps(register, ensure_ascii=False)}" if register else message


def is_big_city(register: dict | None) -> bool:
    return len((register or {}).get("actifs", [])) > ZONE_FROM


def commune_zones(city: dict, spots: list) -> list:
    """
    Une zone par groupe de spots d'une grande ville : un spot à moins de ZONE_KM d'une zone déjà faite en fait partie.
    Sans spot, une seule zone, autour du centre.
    """
    zones = []
    for spot in spots:
        latitude, longitude = float(spot["latitude"]), float(spot["longitude"])
        if not any(haversine_distance_km(latitude, longitude, zone["latitude"], zone["longitude"]) <= ZONE_KM for zone in zones):
            zones.append({"latitude": latitude, "longitude": longitude, "repere": spot["address"]})
    return zones or [{"latitude": float(city["latitude"]), "longitude": float(city["longitude"]), "repere": "le centre de la commune"}]


def register_for_agent(category, register: dict | None, zone: dict | None = None) -> dict | None:
    """
    Ce que l'agent lit du registre : sans les positions. Pour une zone, seulement les lignes à moins de ZONE_KM du repère,
    les ZONE_LINES plus proches, et celles de l'activité de la catégorie (zone_activity : un bar n'est pas montré à
    l'agent des restaurants). Le code garde le registre entier pour les preuves et la date « nouveau ».
    """
    if not register:
        return register

    def kept(lines: list) -> list:
        if zone is None:
            return lines
        placed = sorted(((haversine_distance_km(zone["latitude"], zone["longitude"], *line["position"]), number, line)
                         for number, line in enumerate(lines)
                         if line.get("position") and line.get("activite", "").startswith(category.zone_activity)))
        return [line for distance, _, line in placed if distance <= ZONE_KM][:ZONE_LINES]

    return {kind: [{key: value for key, value in line.items() if key != "position"} for line in kept(lines)]
            for kind, lines in register.items()}


# --- Les recherches d'une commune ---

def _cost(run: dict) -> str:
    return f"{(run.get('duration_ms') or 0) / 1000:.0f} s, {run.get('cost_usd') or 0:.2f} $ en équivalent API"


def ask(category, city: dict, label: str, prompt: str, message: str) -> dict:
    """Une recherche : les lieux retenus et les écartés, sous leur nom seul."""
    service = make_llm_service(category.find_agent)
    with mesure_objet("commune", city.get("id")):
        answer = service.complete_json(prompt, message, search_schema(category))
    for rows in answer.values():
        for row in rows:
            row["nom"] = clean_name(row["nom"])
    category.logger.info(f"[{category.key}] {city['name']} ({label}) : retenus {[row['nom'] for row in answer[category.key]]},"
                      f" fermés {[row['nom'] for row in answer['ecartes'] if row['ferme']]}, {_cost(service.last_run)}")
    return answer


def write_trace(category, city: dict, trace: dict) -> Path:
    """Tout ce qu'une commune a coûté : on peut relire et recontrôler sans repayer les recherches."""
    category.trace_dir.mkdir(parents=True, exist_ok=True)
    path = category.trace_dir / f"{city['name'].replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=1, default=str))
    return path


def search_zone(category, city: dict, register: dict | None, zone: dict | None, trace: dict, label: str = "") -> dict:
    """Les recherches d'une commune ou d'une de ses zones, en même temps, puis le contrôle et l'analyse."""
    name = city_commune(city)
    seen = register_for_agent(category, register, zone)
    message = build_message(city, seen, zone)
    searches = [(f"{label}{search}", prompt) for search, prompt in category.searches]
    with ThreadPoolExecutor(max_workers=len(searches)) as pool:
        answers = list(pool.map(lambda search: ask(category, city, search[0], search[1], message), searches))
    trace["recherches"] = answers
    answer = merge_answers(category, *answers)
    disputed = [row["nom"] for row in answer[category.key] if row.get("dit_ferme")]
    if disputed:
        category.logger.info(f"[{category.key}] {name} : retenus et dits fermés par une autre recherche {disputed}")
    for row in answer[category.key]:
        row["pages"] = control_row(category, row, name)
    trace["controle"] = [{"nom": row["nom"], "pages": row["pages"]} for row in answer[category.key]]
    rows = answer[category.key] = analyze_commune(category, city, answer[category.key], seen, trace)
    # L'alerte de l'analyste se vérifie dans le registre entier (service_store.alert_contradicted).
    service_store.clear_contradicted_alerts(category, rows, register, name)
    # Les preuves et la date « nouveau » se lisent dans le registre entier : un lieu peut y être inscrit hors de sa zone.
    missing = []
    for row in rows:
        if has_accepted_page(category, row, name) or category.register_proves(row, register):
            continue
        reason = category.review_before_proof(row, register, name)
        if reason:
            row["a_relire"] = reason
        else:
            missing.append(row)
    for row, proof in zip(missing, find_proofs(category, city, missing, trace)):
        add_proofs(category, row, proof, name)
    for row in rows:
        row |= control_details(category, row, name)
        row |= category.register_facts(row, register)
        reason = category.review_after_proof(row, register, name)
        if reason and not row.get("a_relire"):
            row["a_relire"] = reason
    return answer


def search_commune(category, city: dict) -> dict:
    """La commune entière, ou zone par zone pour une grande ville. Lève LLMUnavailable si l'agent n'a pas pu répondre."""
    name = city_commune(city)
    register = api_registre.load_register(city, category.register_activities)
    trace = {"commune": name, "version": category.prompt_version, "registre": register}
    try:
        if not is_big_city(register):
            answer = search_zone(category, city, register, None, trace)
        else:
            zones = commune_zones(city, service_store.commune_spots(name))
            category.logger.info(f"[{category.key}] {name} : {len(zones)} zones de {ZONE_KM} km autour des spots")
            trace["zones"] = [{"zone": zone} for zone in zones]
            answer = merge_zones(category, [search_zone(category, city, register, zone, zone_trace, f"zone {number} / {len(zones)}, ")
                                         for number, (zone, zone_trace) in enumerate(zip(zones, trace["zones"]), start=1)])
        trace["final"] = answer[category.key]
        return answer
    finally:
        # Même si une étape échoue : ce qui a déjà été payé reste lisible.
        category.logger.info(f"[{category.key}] {name} : réponses gardées dans {write_trace(category, city, trace)}")


def main(category, description: str):
    """Le lancement d'une catégorie : python -m agents.find_restaurants --ville Plougonvelin [--essai]."""
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ville", required=True, action="append", help="Commune de la table cities (répétable)")
    parser.add_argument("--essai", action="store_true", help="N'écrit rien en base : les réponses restent dans le fichier")
    args = parser.parse_args()
    searched = set()
    for name in args.ville:
        city = service_store.load_city(name)
        if not city:
            category.logger.error(f"[{category.key}] {name} : commune inconnue")
            continue
        if city["name"] != name:
            category.logger.info(f"[{category.key}] {name} : cherchée comme {city_commune(city)}, depuis la ville {city['name']}")
        # Une commune n'est cherchée qu'une fois : --ville Morgat --ville Le Fret ne paie qu'une recherche de Crozon.
        if service_store.commune_key(city) in searched:
            category.logger.info(f"[{category.key}] {name} : {city_commune(city)} déjà cherchée")
            continue
        searched.add(service_store.commune_key(city))
        answer = search_commune(category, city)
        if args.essai:
            print(json.dumps({"ville": name, "lieux": [row["nom"] for row in answer[category.key]]}, ensure_ascii=False))
            continue
        summary = service_store.save_commune(category, city, answer, category.prompt_version, model_of(category.find_agent))
        print(json.dumps({"ville": name, **summary}, ensure_ascii=False))


# --- L'analyste : fermeture, doublon, lieu inutile au voyageur, détails ---

def is_duplicate(category, number: int, rows: list, by_number: dict) -> bool:
    """Le lieu à garder existe, n'est pas lui-même un doublon, et se trouve à la même adresse."""
    target = by_number.get(number, {}).get("doublon_de")
    if target is None:
        return False
    row = rows[number - 1]
    address = service_store.compact_name(row.get("adresse") or "")
    if (target != number and 1 <= target <= len(rows) and not by_number.get(target, {}).get("doublon_de") and address
            and address == service_store.compact_name(rows[target - 1].get("adresse") or "")):
        return True
    category.logger.info(f"[{category.key}] {row['nom']} : doublon refusé par le code (numéro {target}, {row.get('adresse')})")
    # Deux adresses ne sont jamais fusionnées par le code, mais le doute part en relecture (« Doublons » de /supervision) :
    # Fumaisons d'Iroise, l'atelier, et Fumaison d'Iroise, son stand au port, restaient deux fiches (7 novembre 2026).
    if category.refused_duplicate_to_review and target != number and 1 <= target <= len(rows):
        row["doublon_possible"] = {"nom": rows[target - 1]["nom"], "adresse": rows[target - 1].get("adresse"),
                                   "raison": by_number[number].get("doublon_raison")}
    return False


def apply_analysis(category, rows: list, answer: dict) -> tuple:
    """(lieux gardés avec leurs détails, lieux fermés, doublons). Une phrase absente d'une page lue ne ferme rien."""
    by_number = {place["numero"]: place for place in answer["lieux"]}
    kept, closed, duplicates = [], [], []
    for number, row in enumerate(rows, 1):
        place = by_number.get(number, {})
        if (place.get("ferme") and place.get("ferme_page")
                and citation_found(place.get("ferme_citation"), place["ferme_page"]) is not False):
            closed.append(row["nom"])
        elif is_duplicate(category, number, rows, by_number):
            duplicates.append(row["nom"])
        else:
            kept.append({**row, "details": place.get("details", []),
                         category.not_for_travellers: bool(place.get(category.not_for_travellers)),
                         "alerte_registre": place.get("alerte_registre")})
    return kept, closed, duplicates


def fill_addresses(rows: list, answer: dict) -> None:
    """L'adresse vérifiée par l'analyste : c'est elle qui permet de reconnaître un doublon."""
    for place in answer["lieux"]:
        if 1 <= place["numero"] <= len(rows) and place.get("adresse"):
            rows[place["numero"] - 1]["adresse"] = place["adresse"]


def pages_to_read(row: dict) -> list:
    """Les pages trouvées par les recherches, sans les sites que l'analyste ne doit pas ouvrir."""
    urls = [page["url"] for page in row["pages"]] if "pages" in row else [row["lien"], row["preuve_url"]]
    return [url for url in dict.fromkeys(urls) if not is_excluded_site(url)]


def _place_for_agent(category, number: int, row: dict) -> dict:
    """Le début de ce que l'analyste lit d'un lieu : son numéro, son nom, et sa catégorie si elle change les consignes."""
    category = {"categorie": row.get("categorie")} if category.sends_category else {}
    return {"numero": number, "nom": row["nom"], **category, "adresse": row.get("adresse")}


def analyze_commune(category, city: dict, rows: list, register: dict | None = None, trace: dict | None = None) -> list:
    """Les lieux encore valables, avec les détails proposés. Lève LLMUnavailable si l'agent n'a pas pu répondre."""
    if not rows:
        return []
    places = [{**_place_for_agent(category, number, row), "pages": pages_to_read(row),
               **({"dit_ferme": {"raison": row["dit_ferme"].get("raison"), "page": row["dit_ferme"].get("page")}} if row.get("dit_ferme") else {})}
              for number, row in enumerate(rows, 1)]
    message = f"COMMUNE : {city_commune(city)}\nLIEUX : {json.dumps(places, ensure_ascii=False)}"
    if register:
        message += f"\nREGISTRE : {json.dumps(register, ensure_ascii=False)}"
    service = make_llm_service(category.analyze_agent)
    with mesure_objet("commune", city.get("id")):
        answer = service.complete_json(category.analysis_prompt, message, analysis_schema(category))
    fill_addresses(rows, answer)
    kept, closed, duplicates = apply_analysis(category, rows, answer)
    useless = [row["nom"] for row in kept if row[category.not_for_travellers]]
    kept = [row for row in kept if not row[category.not_for_travellers]]
    if trace is not None:
        trace["analyse"] = answer
    category.logger.info(f"[{category.key}] {city['name']} (analyse) : fermés {closed}, doublons {duplicates},"
                        f" {category.not_for_travellers_log} {useless}, alertes {[row['nom'] for row in kept if row['alerte_registre']]},"
                        f" {sum(len(row['details']) for row in kept)} détails proposés, {_cost(service.last_run)}")
    return kept


# --- La preuve, à part, par petits lots ---

def ask_proofs(category, city: dict, batch: list) -> list:
    places = [{**_place_for_agent(category, number, row), "genre": row.get("genre")} for number, row in enumerate(batch, 1)]
    service = make_llm_service(category.prove_agent)
    with mesure_objet("commune", city.get("id")):
        answer = service.complete_json(category.proof_prompt, f"COMMUNE : {city_commune(city)}\nLIEUX : {json.dumps(places, ensure_ascii=False)}", PROOF_SCHEMA)
    by_number = {place["numero"]: place for place in answer["lieux"]}
    category.logger.info(f"[{category.key}] {city['name']} (preuves) : {[row['nom'] for row in batch]}, {_cost(service.last_run)}")
    return [by_number.get(number, {}) for number in range(1, len(batch) + 1)]


def proofs_of_batch(category, city: dict, batch: list) -> list:
    """Les preuves d'un lot, ou lieu par lieu s'il dépasse son délai. Un lieu seul trop long attend une relecture."""
    try:
        return ask_proofs(category, city, batch)
    except LLMTimeout:
        if len(batch) == 1:
            category.logger.info(f"[{category.key}] {city['name']} (preuves) : {batch[0]['nom']} sans réponse à temps, à relire")
            return [{"a_relire": PROOF_TIMED_OUT}]
        category.logger.info(f"[{category.key}] {city['name']} (preuves) : lot trop long, relancé lieu par lieu")
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            return [proof for answer in pool.map(lambda row: proofs_of_batch(category, city, [row]), batch) for proof in answer]


def find_proofs(category, city: dict, rows: list, trace: dict | None = None) -> list:
    """Pour chaque lieu sans page acceptée, dans le même ordre, ce que l'analyste a trouvé. Lève LLMUnavailable."""
    batches = [rows[start:start + PROOF_BATCH] for start in range(0, len(rows), PROOF_BATCH)]
    if not batches:
        return []
    with ThreadPoolExecutor(max_workers=len(batches)) as pool:
        proofs = [proof for answer in pool.map(lambda batch: proofs_of_batch(category, city, batch), batches) for proof in answer]
    if trace is not None:
        trace["preuves"] = [{"nom": row["nom"], **proof} for row, proof in zip(rows, proofs)]
    return proofs


# --- Les détails pratiques, gardés seulement si le code retrouve la phrase ---

def value_in_citation(field: str, value: str | None, citation: str) -> bool:
    """
    La phrase retrouvée dit-elle bien ce que l'agent en tire ? Les mois de la saison, le nom de la distinction (restaurants)
    ou les jours du marché (commerces).
    """
    quoted = service_store.name_key(citation).split()
    words = service_store.name_key(value).split()
    if field == "saison" and not value:
        return True
    if field == "distinction":
        needed = [word for word in words if word.isalpha() and len(word) > 2]
    else:
        needed = [word for word in words if word in (WEEKDAYS if field == "jours" else MONTHS)]
    return bool(needed) and all(word in quoted for word in needed)


def control_details(category, row: dict, commune: str) -> dict:
    """Les détails que le code retrouve sur une page acceptée, et les preuves qui vont avec. Le premier par champ."""
    checked, proofs = {}, []
    pages = {page["url"].strip(): page for page in row["pages"]}
    commune_name, postcode = service_store.commune_of_address(row.get("adresse"), commune)
    place = {"name": row["nom"], "commune": commune_name, "cp": postcode, "telephone": None}
    for detail in row.get("details", []):
        url = detail["page"].strip()
        if detail["champ"] in checked or not value_in_citation(detail["champ"], detail["valeur"], detail["citation"]):
            continue
        # Un détail réservé à une catégorie : les jours ne se gardent que pour un marché.
        only_for = category.detail_only_for.get(detail["champ"])
        if only_for and row.get("categorie") != only_for:
            continue
        if not citation_found(detail["citation"], url):
            continue
        page = pages.get(url)
        if not page:
            found = check_links_of({"liens": [{"url": url, "type_page": detail["type_page"]}], "autre_nom": row.get("ancien_nom")}, place)
            page = pages[url] = found[0]
        if category.accepts(page, row, commune):
            checked[detail["champ"]] = detail["valeur"]
            proofs.append({**page, "citation": detail["citation"], "citation_trouvee": True, "porte_sur": detail["champ"]})
    dropped = [detail["champ"] for detail in row.get("details", []) if detail["champ"] not in checked]
    if dropped:
        category.logger.info(f"[{category.key}] {row['nom']} : détails sans citation contrôlée {sorted(set(dropped))}")
    return {"saisonnier": "saison" in checked, "mois_ouverture": checked.get("saison"),
            **{field: checked.get(field) for field in category.detail_fields if field != "saison"},
            "pages": row["pages"] + proofs}
