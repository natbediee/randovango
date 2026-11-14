"""
Le menu « Catégorie » de Services et de Modifier propose toujours toutes les catégories (carte #186) : celles de la
liste commune des pages (SERVICE_TABS de supervision_common.js), qui doit suivre les onglets de l'étape 4 que connaît
le serveur (POI_FRONTEND_CATEGORY_MAP), plus « Hors étape 4 ».
"""
import re
from pathlib import Path

from services.supervision.services_review import NO_TAB
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP

COMMON_JS = Path(__file__).resolve().parents[3] / "frontend" / "static" / "js" / "supervision_common.js"


def page_tabs() -> list:
    """Les codes des catégories du menu, lus dans SERVICE_TABS de supervision_common.js."""
    block = re.search(r"const SERVICE_TABS = \[(.*?)\];", COMMON_JS.read_text(), re.S).group(1)
    return re.findall(r"\['(\w+)',", block)


def test_the_category_menu_offers_every_tab_of_step_4():
    """Chaque onglet de l'étape 4 a sa ligne dans le menu, et « Hors étape 4 » aussi : aucune catégorie ne manque."""
    assert set(page_tabs()) == set(POI_FRONTEND_CATEGORY_MAP.values()) | {NO_TAB}


def test_the_category_list_is_written_once():
    """La liste n'est plus recopiée dans Services et Modifier : une seule liste, dans le module commun."""
    pages = COMMON_JS.parent
    for name in ("supervision_services.js", "supervision_modifier.js"):
        assert "const SERVICE_TABS" not in (pages / name).read_text()
