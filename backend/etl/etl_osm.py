"""
L'étape OSM d'une ville : extraction, transformation, chargement.
Une ville est notée dans osm_a_rattraper.json avant l'extraction et retirée une fois chargée.
Elle reste donc listée si OSM échoue, mais aussi si uvicorn --reload coupe le thread en route.
"""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from etl.extract.api_osm import extract_osm
from etl.load.load_poi import load_osm_poi
from etl.transform.transform_osm import transform_osm
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_osm")

CATCH_UP_FILE = Path(os.getenv("RANDOVANGO_LOG_DIR", "/usr/src/logs")) / "osm_a_rattraper.json"
_catch_up_lock = threading.Lock()


def _read_catch_up() -> dict:
    try:
        return json.loads(CATCH_UP_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError:
        logger.warning(f"[catch-up] {CATCH_UP_FILE} illisible : considéré comme vide")
        return {}


def _update_catch_up(city: str, state: str | None) -> None:
    """Note la ville dans cet état, ou la retire si state est None."""
    with _catch_up_lock:
        cities = _read_catch_up()
        if state is None:
            cities.pop(city, None)
        else:
            cities[city] = {"etat": state, "depuis": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        temporary = CATCH_UP_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(cities, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, CATCH_UP_FILE)


def run_osm_etl(city: str) -> int | None:
    """Renvoie le nombre de lieux retenus, ou None si OSM n'a pas pu être lu."""
    _update_catch_up(city, "en_cours")
    try:
        osm_json = extract_osm(city)
        if osm_json is None:
            _update_catch_up(city, "echec")
            logger.error(f"[catch-up] OSM en échec pour {city} : ville notée dans {CATCH_UP_FILE.name}")
            return None
        df_osm = transform_osm(osm_json, city=city)
        load_osm_poi(df_osm, city_name=city)
    except Exception:
        _update_catch_up(city, "echec")
        raise
    _update_catch_up(city, None)
    return 0 if df_osm is None else len(df_osm)
