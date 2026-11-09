"""
Ce que l'étape 4 montre d'une station-service de l'État (etl/etl_carburants.py).

LE LIEN GOOGLE MAPS D'UNE STATION (essai du 8 novembre 2026)
Le nom affiché ne suffit pas : « Intermarché Rue du Stade » ouvrirait le supermarché, pas sa station. On cherche donc
« station-service », la marque (OSM), puis l'adresse ou, à défaut, le code postal et la ville de l'État. Essayé sur
quatre stations : Intermarché de Plougonvelin, E.Leclerc de Keruscat et Station U de Plouarzel tombent chacune sur la
fiche Google de la station elle-même.
Sans marque, la même recherche ouvre une liste de stations des environs, dont la première est ailleurs (Carrefour de
Saint-Renan pour la station de Locmaria-Plouzané) : on donne alors la position, comme maps_url pour un nom générique.
Une station reliée à la main en supervision a sa marque, et retrouve le lien par la recherche.
"""
import json
from datetime import date, datetime
from urllib.parse import quote_plus

from services.restaurant_selection_service import MAPS_SEARCH_URL

FUEL_SEARCH_WORD = "station-service"

# LES PRIX (maquette validée le 8 novembre 2026)
# Une pastille par carburant vendu, dans cet ordre : le gazole d'abord, c'est celui des vans. Le nom du fichier de l'État
# est gardé comme clé (« E10 »), le libellé est celui de la pompe (« SP95-E10 »).
FUEL_LABELS = {"Gazole": "Gazole", "E10": "SP95-E10", "SP95": "SP95", "SP98": "SP98", "E85": "E85", "GPLc": "GPL"}
FUEL_ORDER = list(FUEL_LABELS)
OLD_PRICE_DAYS = 7          # au-delà, le prix déclaré est montré en ocre, avec sa date
SHORTAGE_FOR_GOOD = "definitive"
CLOSED_FOR_GOOD = ("D", "definitive")
MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")


def _day(value) -> date | None:
    """Une date de MySQL : un datetime, ou le texte de JSON_OBJECT (« 2026-11-03 15:19:50.000000 »)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def day_label(day: date | None) -> str | None:
    """« 3 nov. »"""
    return f"{day.day} {MONTHS[day.month - 1]}" if day else None


def price_badges(prices_json, today: date) -> list:
    """
    Les pastilles d'une station, depuis prix_carburants (JSON_ARRAYAGG de l'étape 4). Une rupture définitive : pas de
    pastille (le carburant n'est pas vendu). Une rupture temporaire : une pastille « en rupture », sans prix.
    Un prix déclaré il y a plus de OLD_PRICE_DAYS jours : « ancien », avec sa date.
    """
    rows = json.loads(prices_json) if isinstance(prices_json, (str, bytes)) else (prices_json or [])
    badges = []
    for row in rows or []:
        if row.get("rupture_type") == SHORTAGE_FOR_GOOD:
            continue
        shortage = row.get("rupture_type") == "temporaire"
        if not shortage and row.get("prix") is None:
            continue
        declared = _day(row.get("releve_le"))
        badges.append({
            "carburant": row["carburant"],
            "label": FUEL_LABELS.get(row["carburant"], row["carburant"]),
            "prix": None if shortage else float(row["prix"]),
            "rupture": shortage,
            "releve_le": declared.isoformat() if declared else None,
            "date_label": day_label(declared),
            "ancien": bool(declared) and not shortage and (today - declared).days > OLD_PRICE_DAYS,
        })
    rank = {fuel: index for index, fuel in enumerate(FUEL_ORDER)}
    return sorted(badges, key=lambda badge: rank.get(badge["carburant"], len(FUEL_ORDER)))


def prices_summary(badges: list, read_at) -> str | None:
    """« Prix déclarés du 30 oct. au 3 nov., lus le 8 nov. » (ou « le 3 nov. » quand toutes les dates sont les mêmes)."""
    days = sorted({badge["releve_le"] for badge in badges if badge["releve_le"] and not badge["rupture"]})
    if not days:
        return None
    first, last = day_label(date.fromisoformat(days[0])), day_label(date.fromisoformat(days[-1]))
    declared = f"le {last}" if first == last else f"du {first} au {last}"
    read = day_label(_day(read_at))
    return f"Prix déclarés {declared}" + (f", lus le {read}" if read else "")


def is_closed_for_good(closure_type: str | None) -> bool:
    return closure_type in CLOSED_FOR_GOOD


def closure_label(closure_type: str | None, start, end, today: date) -> str | None:
    """« Fermée jusqu'au 12 nov. » pendant une fermeture temporaire, « Fermée en ce moment » sans date de fin."""
    if not closure_type or is_closed_for_good(closure_type):
        return None
    start_day, end_day = _day(start), _day(end)
    if (start_day and start_day > today) or (end_day and end_day < today):
        return None
    return f"Fermée jusqu'au {day_label(end_day)}" if end_day else "Fermée en ce moment"


def station_maps_url(brand: str | None, address: str | None, postcode: str | None, town: str | None,
                     latitude: float | None, longitude: float | None) -> str | None:
    """
    Le lien de recherche Google d'une station. address est poi.address : la rue de l'État avec code postal et ville,
    ou None quand le champ de l'État est le nom d'une société (transform_carburants.usable_address).
    """
    if not (brand and brand.strip()):
        if latitude is None or longitude is None:
            return None
        return MAPS_SEARCH_URL + quote_plus(f"{float(latitude):.6f},{float(longitude):.6f}")
    place = address or " ".join(part for part in (postcode, (town or "").title()) if part)
    words = [FUEL_SEARCH_WORD, brand, place]
    return MAPS_SEARCH_URL + quote_plus(" ".join(word.strip() for word in words if word and word.strip()))
