"""Un agent enrichit, il ne recrée pas : le service déjà en base est retrouvé dans tous les services, au même endroit."""
from agents.find_commerces import COMMERCES
from agents.find_restaurants import RESTAURANTS
from services import service_store
from services.service_store import find_known

PLOUDALMEZEAU = {"id": 1, "name": "Ploudalmézeau", "latitude": 48.5439, "longitude": -4.655}
GALION_SPOT = (48.5413, -4.65673)
GALION_ADDRESS = "1 rue des Murs, 29830 Ploudalmézeau"
SITE = {"url": "https://legalion.fr", "type_page": "site", "verdict": "ok"}


def _poi(name, address, position, poi_id=7, masked=0):
    return {"id": poi_id, "name": name, "address": address, "latitude": position[0], "longitude": position[1],
            "url": None, "masque": masked}


# --- Le nom ne suffit jamais, il faut aussi le lieu ---

def test_a_namesake_of_another_commune_is_another_place():
    """Le Galion de Lampaul-Plouarzel n'est pas celui de Ploudalmézeau, à 10 km : il ne lui est plus rattaché."""
    ploudalmezeau = _poi("Le Galion", GALION_ADDRESS, GALION_SPOT)
    lampaul = {"nom": "Le Galion", "adresse": "Place de l'Église, 29810 Lampaul-Plouarzel"}
    assert find_known(lampaul, (48.4474, -4.7632), PLOUDALMEZEAU, [ploudalmezeau]) is None


def test_the_same_name_nearby_is_the_same_place():
    """Le même nom à quelques centaines de mètres est le même service : l'adresse géocodée et le point d'OSM diffèrent."""
    osm = _poi("Bzzzt Café", "9 Menez Perroz, 29880 Lilia", (48.6120, -4.5560))
    row = {"nom": "Bzzzt Café", "adresse": "Port de Perros, 29880 Plouguerneau"}
    assert find_known(row, (48.6150, -4.5560), PLOUDALMEZEAU, [osm]) == osm
    assert find_known(row, (48.6320, -4.5560), PLOUDALMEZEAU, [osm]) is None


def test_the_same_address_finds_the_place_wherever_it_was_put():
    """Le Commerce de Tréméoc : même nom et même adresse, alors que le géocodage l'a placé à 1,8 km de sa ligne."""
    osm = _poi("Le Commerce", "8 Rue de Pont-l'Abbé, 29120 Tréméoc", (47.9040, -4.2250))
    row = {"nom": "Le Commerce", "adresse": "8 route de Pont-l'Abbé, 29120 Tréméoc"}
    assert find_known(row, (47.9200, -4.2250), PLOUDALMEZEAU, [osm]) == osm


def test_the_nearest_namesake_is_chosen():
    """Entre deux services du même nom à moins d'un kilomètre, le plus proche de l'adresse est retenu."""
    far = _poi("La Poke", "1 Rue de Narvik, 29200 Brest", (48.3960, -4.4800), poi_id=1)
    near = _poi("La Poke", "2 Rue Keréon, 29200 Brest", (48.3900, -4.4860), poi_id=2)
    row = {"nom": "La Poke", "adresse": "4 rue Keréon, 29200 Brest"}
    assert find_known(row, (48.3901, -4.4861), PLOUDALMEZEAU, [far, near])["id"] == 2


def test_a_place_without_position_is_found_alone_in_its_commune():
    """Sans position (« Bourg de Lampaul »), le service est retrouvé s'il est le seul à ce nom dans la commune."""
    ouessant = {"id": 2, "name": "Ouessant", "latitude": 48.4580, "longitude": -5.0950}
    row = {"nom": "Ki Tomm", "adresse": "Bourg de Lampaul, 29242 Ouessant"}
    here = _poi("Ki Tomm", "Lampaul, 29242 Ouessant", (48.4575, -5.0960))
    elsewhere = _poi("Ki Tomm", "Le Bourg, 29259 Île-Molène", (48.3960, -4.9560), poi_id=8)
    twin = _poi("Ki Tomm", "Route du Stiff, 29242 Ouessant", (48.4700, -5.0600), poi_id=9)
    assert find_known(row, None, ouessant, [here]) == here
    assert find_known(row, None, ouessant, [elsewhere]) is None
    assert find_known(row, None, ouessant, [here, twin]) is None


def test_a_place_without_postcode_is_in_the_commune_near_its_centre():
    """Un service d'OSM sans adresse est dans la commune s'il est à moins de 5 km de son centre."""
    ouessant = {"id": 2, "name": "Ouessant", "latitude": 48.4580, "longitude": -5.0950}
    row = {"nom": "Ki Tomm", "adresse": None}
    assert find_known(row, None, ouessant, [_poi("Ki Tomm", None, (48.4575, -5.0960))])
    assert find_known(row, None, ouessant, [_poi("Ki Tomm", None, (48.5413, -4.6567))]) is None


def test_a_longer_name_with_a_curly_apostrophe_is_the_same_place():
    """« L'Hermine » retrouve « L’Hermine Bar Tabac Presse » d'OSM, écrit avec une apostrophe courbe, à 3 m."""
    osm = _poi("L’Hermine Bar Tabac Presse", None, (48.3260, -4.1590))
    row = {"nom": "L'Hermine", "adresse": "7 rue Henri Mazé, 29460 Hanvec"}
    assert find_known(row, (48.3260, -4.1591), PLOUDALMEZEAU, [osm]) == osm


def test_every_tab_of_the_chain_is_searched():
    """Le service existant est cherché dans tous les onglets que la chaîne remplit, pas dans les toilettes ni les musées."""
    assert {"restaurant", "fast_food", "cafe", "bakery", "convenience", "supermarket"} <= set(service_store.KNOWN_SERVICES)
    assert not {"toilets", "museum", "fuel", "drinking_water"} & set(service_store.KNOWN_SERVICES)


# --- Le Galion, dans les deux ordres : un seul service à la fin ---

class _Base:
    """Une base factice : garde les requêtes, ne trouve ni signal, ni décision, ni correction humaine."""
    lastrowid = 99

    def __init__(self, waiting=False):
        self.queries, self.waiting, self.last = [], waiting, ""

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.last = " ".join(sql.split())
        self.queries.append((self.last, params))

    def fetchone(self):
        return (1,) if self.waiting and "FROM poi_signals" in self.last else None

    def fetchall(self):
        return []

    def close(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def wrote(self, start):
        return [params for sql, params in self.queries if sql.startswith(start)]


def _save(monkeypatch, category, row, known=(), sheets=(), waiting=False):
    """Enregistre un lieu de Ploudalmézeau. Rend la base, les lieux créés et les services ajoutés à un lieu existant."""
    base, created, linked = _Base(waiting), [], []
    monkeypatch.setattr(service_store.MySQLUtils, "connect", staticmethod(lambda: base))
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, source: 1)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: list(known))
    monkeypatch.setattr(service_store, "known_sheets", lambda cursor, city, table: list(sheets))
    monkeypatch.setattr(service_store, "_position", lambda city, address: GALION_SPOT)
    monkeypatch.setattr(service_store, "create_poi", lambda category_, cursor, row_, position, city, source, masked: created.append(row_["nom"]) or 99)
    monkeypatch.setattr(service_store, "insert_service_and_link", lambda cursor, poi_id, service: linked.append((poi_id, service)))
    summary = service_store.save_commune(category, PLOUDALMEZEAU, {category.key: [row]}, 1, "modele")
    return summary, base, created, linked


RESTAURANT = {"nom": "Le Galion", "genre": "bar-brasserie", "categorie": "bistrot", "adresse": GALION_ADDRESS, "pages": [SITE]}
CAFE = {"nom": "Le Galion", "genre": "bar-tabac", "categorie": "cafe", "adresse": GALION_ADDRESS, "pages": [SITE]}


def test_the_restaurant_first_then_the_cafe_makes_one_service(monkeypatch):
    """Restaurants puis commerces : le restaurant est créé, puis le café, qui a déjà sa fiche restaurant, n'est pas enregistré."""
    summary, base, created, _ = _save(monkeypatch, RESTAURANTS, RESTAURANT)
    assert created == ["Le Galion"] and summary["fiches"] == 1 and base.wrote("REPLACE INTO restaurants")
    galion = _poi("Le Galion", GALION_ADDRESS, GALION_SPOT, poi_id=99)
    summary, base, created, linked = _save(monkeypatch, COMMERCES, CAFE, known=[galion], sheets=[galion])
    assert summary["deja_restaurant"] == 1 and summary["fiches"] == 0
    assert created == [] and linked == [] and not base.wrote("REPLACE INTO commerces")


def test_the_cafe_first_then_the_restaurant_makes_one_service(monkeypatch):
    """Commerces puis restaurants : le restaurant retrouve le café, lui ajoute son service et sa fiche, et la fiche de café s'en va."""
    summary, base, created, _ = _save(monkeypatch, COMMERCES, CAFE)
    assert created == ["Le Galion"] and summary["fiches"] == 1 and base.wrote("REPLACE INTO commerces")
    cafe = _poi("Le Galion", GALION_ADDRESS, GALION_SPOT, poi_id=99)
    summary, base, created, linked = _save(monkeypatch, RESTAURANTS, RESTAURANT, known=[cafe])
    assert created == [] and summary["fiches"] == 1
    assert linked == [(99, "restaurant")]
    assert base.wrote("REPLACE INTO restaurants")[0][0] == 99
    assert base.wrote("DELETE FROM commerces WHERE poi_id = %s AND categorie IN") == [(99, "cafe")]


def test_a_restaurant_enriches_the_cafe_of_osm(monkeypatch):
    """Un restaurant qu'OSM range en café n'est pas recréé : le service d'OSM reçoit l'adresse, le lien, la fiche et le service."""
    osm = _poi("L'Odyssée", None, (48.5414, -4.6568), poi_id=1658)
    row = {**RESTAURANT, "nom": "L'Odyssée"}
    summary, base, created, linked = _save(monkeypatch, RESTAURANTS, row, known=[osm])
    assert created == [] and linked == [(1658, "restaurant")] and summary["fiches"] == 1
    [(sql, params)] = [(sql, params) for sql, params in base.queries if sql.startswith("UPDATE poi SET address")]
    assert GALION_ADDRESS in params and "https://legalion.fr" in params and params[-1] == 1658


def test_a_place_waiting_for_another_agent_review_is_taken_over(monkeypatch):
    """Un café masqué en attente de relecture est repris par l'agent des restaurants, qui en a la preuve : il s'affiche."""
    waiting = _poi("Le Galion", GALION_ADDRESS, GALION_SPOT, poi_id=47844, masked=1)
    summary, base, created, linked = _save(monkeypatch, RESTAURANTS, RESTAURANT, known=[waiting], waiting=True)
    assert created == [] and summary["fiches"] == 1 and linked == [(47844, "restaurant")]
    assert any("masque = %s" in sql and params[-1] == 47844 for sql, params in base.queries if sql.startswith("UPDATE poi SET"))


def test_a_place_masked_by_a_human_is_not_taken_over(monkeypatch):
    """Un service masqué par un humain, sans relecture en attente, reste masqué : rien n'est écrit, quelle que soit la catégorie."""
    removed = _poi("Le Galion", GALION_ADDRESS, GALION_SPOT, poi_id=47844, masked=1)
    summary, base, created, linked = _save(monkeypatch, RESTAURANTS, RESTAURANT, known=[removed])
    assert created == [] and linked == [] and summary["fiches"] == 0
    assert not base.wrote("REPLACE INTO") and not base.wrote("UPDATE poi SET")
