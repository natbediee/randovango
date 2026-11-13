"""Un agent enrichit, il ne recrée pas : le service déjà en base est retrouvé dans tous les services, au même endroit."""
from agents.find_commerces import COMMERCES
from agents.find_restaurants import RESTAURANTS
from services import service_store
from services.service_store import find_known, is_verified, same_name

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


# --- Une seule règle pour le nom, quelle que soit la catégorie ---

def test_the_word_saying_what_a_place_is_does_not_make_two_names():
    """« Boulangerie Le Gall » est « Le Gall », « Mercure Bar » est « Café Mercure » : le mot du lieu ne fait pas deux noms."""
    assert same_name("Boulangerie Le Gall", "Le Gall") and same_name("La Crêperie Riboul", "Riboul")
    assert same_name("Mercure Bar", "Café Mercure") and same_name("Bar Crêperie La Grotte", "LA GROTTE")
    assert same_name("Café du Marché", "Le Café du Marché")


def test_two_different_words_make_two_places():
    """Un marché et une épicerie du même village, un café et une crêperie du même port, sont deux services."""
    assert not same_name("Marché de Plougonvelin", "Épicerie de Plougonvelin")
    assert not same_name("Le Café du Port", "Crêperie du Port")
    assert not same_name("Boulangerie du Kreisker", "Café du Kreisker")


def test_a_restaurant_is_found_under_its_short_name():
    """« Crêperie Riboul » retrouve le service « Riboul » d'OSM, comme « Boulangerie Laot » retrouvait « Laot »."""
    osm = _poi("Riboul", "3 rue de la Mer, 29217 Plougonvelin", (48.3400, -4.7200))
    row = {"nom": "Crêperie Riboul", "adresse": "5 rue de la Mer, 29217 Plougonvelin"}
    assert find_known(row, (48.3402, -4.7200), PLOUDALMEZEAU, [osm]) == osm


def test_a_bar_and_a_creperie_side_by_side_stay_two():
    """À 40 m l'un de l'autre, « Bar du Port » et « Crêperie du Port » restent deux services ; deux « du Port » sans mot contraire, un seul."""
    bar = _poi("Bar du Port", "Quai du Port, 29120 Combrit", (47.8730, -4.1210))
    assert find_known({"nom": "Crêperie du Port", "adresse": "Rue du Bac, 29120 Combrit"}, (47.8733, -4.1210), PLOUDALMEZEAU, [bar]) is None
    assert find_known({"nom": "Le Port", "adresse": "Rue du Bac, 29120 Combrit"}, (47.8733, -4.1210), PLOUDALMEZEAU, [bar]) == bar


# --- Une seule règle pour le badge et pour l'envoi en supervision ---

def test_the_badge_rule_is_the_same_for_every_category():
    """« Vérifié » : une page acceptée, ou le registre au nom du lieu et une page qui le nomme, même un annuaire (La Meule de Pierre)."""
    directory = {"url": "https://annuaire.fr/x", "type_page": "agregateur", "verdict": "ok"}
    assert is_verified({"pages": []}, [SITE])
    assert is_verified({"registre_depuis": "2024-01-18", "pages": [directory]}, [])
    assert not is_verified({"registre_depuis": "2024-01-18", "pages": []}, [])
    assert not is_verified({"pages": [directory]}, [])


def test_a_restaurant_sent_to_review_leaves_the_display_like_a_shop(monkeypatch):
    """Un restaurant renvoyé en relecture perd sa fiche jusqu'à la décision, comme un commerce : avant, il restait affiché sans signal."""
    signals = []
    monkeypatch.setattr(service_store, "save_signal", lambda cursor, poi_id, source, kind, detail: signals.append((poi_id, source, detail["raison"])))
    base = _Base()
    assert service_store.send_to_review(RESTAURANTS, base, 32340, "registre : enseigne fermée", {})
    assert base.wrote("DELETE FROM restaurants WHERE poi_id") == [(32340,)]
    assert signals == [(32340, "agent_restaurants", "registre : enseigne fermée")]


def test_a_restaurant_validated_by_a_human_keeps_its_sheet(monkeypatch):
    """Un restaurant qu'un humain a validé garde sa fiche, et rien n'est signalé : sa décision prime."""
    monkeypatch.setattr(service_store, "save_signal", lambda *args: 1 / 0)
    monkeypatch.setattr(service_store, "validated_by_human", lambda cursor, poi_id: True)
    base = _Base()
    assert not service_store.send_to_review(RESTAURANTS, base, 32489, "registre : débit de boissons", {})
    assert not base.wrote("DELETE")


# --- Le Galion, dans les deux ordres : un seul service à la fin ---

class _Base:
    """Une base factice : garde les requêtes, ne trouve ni signal, ni décision, ni correction humaine."""
    lastrowid = 99

    def __init__(self, waiting=False):
        self.queries, self.waiting, self.last, self.ended = [], waiting, "", []

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
        self.ended.append("commit")

    def rollback(self):
        self.ended.append("rollback")

    def wrote(self, start):
        return [params for sql, params in self.queries if sql.startswith(start)]


def _save(monkeypatch, category, row, known=(), sheets=(), waiting=False, trial=False):
    """Enregistre un lieu de Ploudalmézeau. Rend la base, les lieux créés et les services ajoutés à un lieu existant."""
    base, created, linked = _Base(waiting), [], []
    monkeypatch.setattr(service_store.MySQLUtils, "connect", staticmethod(lambda: base))
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, source: 1)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: list(known))
    monkeypatch.setattr(service_store, "known_sheets", lambda cursor, city, table, kinds=(): [] if kinds else list(sheets))
    monkeypatch.setattr(service_store, "_position", lambda city, address: GALION_SPOT)
    monkeypatch.setattr(service_store, "create_poi", lambda category_, cursor, row_, position, city, source, masked: created.append(row_["nom"]) or 99)
    monkeypatch.setattr(service_store, "insert_service_and_link", lambda cursor, poi_id, service: linked.append((poi_id, service)))
    summary = service_store.save_commune(category, PLOUDALMEZEAU, {category.key: [row]}, 1, "modele", trial=trial)
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


# --- À l'essai, le bilan est calculé et rien n'est gardé ---

def test_a_trial_gives_the_summary_and_cancels_every_write(monkeypatch):
    """À l'essai, l'enregistrement d'une commune dit ce qu'il écrirait (une fiche) puis annule tout ; sans essai, il valide."""
    summary, base, created, _ = _save(monkeypatch, RESTAURANTS, RESTAURANT, trial=True)
    assert summary["fiches"] == 1 and created == ["Le Galion"] and base.ended == ["rollback"]
    _, base, _, _ = _save(monkeypatch, RESTAURANTS, RESTAURANT)
    assert base.ended == ["commit"]


def test_a_short_name_must_be_the_whole_name_of_the_known_place():
    """« Marché de Carantec », cherché sous son nom court « Carantec », ne retrouve pas « Carantec Pizza » à 58 m."""
    pizza = _poi("Carantec Pizza", "Rue Albert Louppe, 29660 Carantec", GALION_SPOT)
    market = {"nom": "Marché de Carantec", "adresse": "Place de la Libération, 29660 Carantec"}
    assert find_known(market, GALION_SPOT, PLOUDALMEZEAU, [pizza]) is None


# --- Les supermarchés : une enseigne présente à plusieurs adresses ---

LIDL = {"nom": "Lidl", "genre": "supermarché", "categorie": "supermarche", "adresse": "12 rue de Brest, 29830 Ploudalmézeau",
        "pages": [{"url": "https://www.lidl.fr/s/ploudalmezeau", "type_page": "site", "verdict": "ok"}]}


def test_a_supermarket_is_found_by_its_name_only_close_by(monkeypatch):
    """Le Lidl d'OSM à 150 m de l'adresse trouvée est enrichi de sa fiche ; un autre Lidl à 600 m ne l'est pas, un supermarché est créé."""
    from agents.find_supermarches import SUPERMARCHES
    near = _poi("Lidl", None, (GALION_SPOT[0] + 0.00135, GALION_SPOT[1]), poi_id=1059)
    far = _poi("Lidl", None, (GALION_SPOT[0] + 0.0054, GALION_SPOT[1]), poi_id=2087)
    summary, base, created, linked = _save(monkeypatch, SUPERMARCHES, LIDL, known=[far, near])
    assert created == [] and linked == [(1059, "supermarket")] and summary["fiches"] == 1
    [params] = base.wrote("REPLACE INTO commerces")
    assert params[0] == 1059 and "supermarche" in params
    _, _, created, linked = _save(monkeypatch, SUPERMARCHES, LIDL, known=[far])
    assert created == ["Lidl"] and linked == []


def test_a_grocery_with_a_supermarket_sheet_keeps_it(monkeypatch):
    """Le Biocoop rangé « épicerie » par les commerces a déjà sa fiche supermarché : il n'est pas enregistré une seconde fois."""
    biocoop = {"nom": "Biocoop", "genre": "épicerie bio", "categorie": "epicerie", "adresse": GALION_ADDRESS, "pages": [SITE]}
    supermarket = _poi("Biocoop", GALION_ADDRESS, GALION_SPOT, poi_id=1306)
    base, created = _Base(), []
    monkeypatch.setattr(service_store.MySQLUtils, "connect", staticmethod(lambda: base))
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, source: 1)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: [supermarket])
    monkeypatch.setattr(service_store, "known_sheets", lambda cursor, city, table, kinds=(): [supermarket] if kinds == ("supermarche",) else [])
    monkeypatch.setattr(service_store, "_position", lambda city, address: GALION_SPOT)
    summary = service_store.save_commune(COMMERCES, PLOUDALMEZEAU, {"commerces": [biocoop]}, 4, "modele")
    assert summary["deja_supermarche"] == 1 and summary["fiches"] == 0 and not base.wrote("REPLACE INTO")


def test_a_place_left_without_position_is_found_again_once_placed():
    """Le service masqué « position introuvable » est repris quand son adresse est enfin placée, au lieu d'être créé une seconde fois ; le même nom dans une autre commune ne l'est pas."""
    waiting = _poi("Ferme de Kerguelen", "Kerguelen, 29830 Ploudalmézeau", (None, None), poi_id=48211, masked=1)
    row = {"nom": "Ferme de Kerguelen", "adresse": "Lieu-dit Kerguelen, 29830 Ploudalmézeau"}
    assert find_known(row, GALION_SPOT, PLOUDALMEZEAU, [waiting]) == waiting
    assert find_known({**row, "adresse": "Kerguelen, 29840 Porspoder"}, GALION_SPOT, PLOUDALMEZEAU, [waiting]) is None


def test_the_known_services_include_those_left_without_position(monkeypatch):
    """Les services déjà en base sont lus autour de la commune, et ceux restés sans position avec la ville où un passage les a créés."""
    base = _Base()
    base.description = [("id",)]
    service_store.known_services(base, PLOUDALMEZEAU, ("restaurant", "cafe"))
    [(sql, params)] = base.queries
    assert "p.latitude IS NULL AND EXISTS (SELECT 1 FROM histo_poi" in sql and params[-2:] == (PLOUDALMEZEAU["id"], None)


def test_a_place_without_position_or_postcode_is_found_by_its_town():
    """La Table de Pierre Bourée, restée sans adresse ni position à Gevrey-Chambertin, est reprise par le passage suivant au lieu d'être créée une seconde fois."""
    waiting = _poi("La Table de Pierre Bourée", None, (None, None), poi_id=32475, masked=1)
    assert find_known({"nom": "La Table de Pierre Bourée", "adresse": None}, None, PLOUDALMEZEAU, [waiting]) == waiting


def test_a_known_place_still_without_position_stays_in_review(monkeypatch):
    """Un service retrouvé en base mais toujours sans position reste « position introuvable » : il n'est pas affiché sans pouvoir être placé sur la carte."""
    waiting = _poi("Le Galion", GALION_ADDRESS, (None, None), poi_id=47844, masked=1)
    flagged = []
    monkeypatch.setattr(service_store, "flag", lambda category, cursor, row, position, city, known, source, reason, detail, link=None: flagged.append(reason))
    base, _ = _Base(waiting=True), None
    monkeypatch.setattr(service_store.MySQLUtils, "connect", staticmethod(lambda: base))
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, source: 1)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: [waiting])
    monkeypatch.setattr(service_store, "known_sheets", lambda cursor, city, table, kinds=(): [])
    monkeypatch.setattr(service_store, "_position", lambda city, address: None)
    summary = service_store.save_commune(RESTAURANTS, PLOUDALMEZEAU, {"restaurants": [RESTAURANT]}, 1, "modele")
    assert flagged == [service_store.NO_POSITION] and summary["a_confirmer"] == 1 and summary["fiches"] == 0


# --- Un même nom ailleurs dans la commune : un doute, pas un rattachement ---

CASTEL = {"nom": "Le Castel Ac'h", "genre": "restaurant de poisson", "categorie": "poisson", "adresse": "48 rue Kervenni, 29830 Ploudalmézeau",
          "pages": [SITE]}


def test_a_namesake_further_in_the_commune_makes_a_doubt_not_a_merge(monkeypatch):
    """Le Castel Ac'h, trouvé à 1,7 km de son point d'OSM dans la même commune, est créé avec un doute dans la file « Doublons », posé sur le service sans fiche."""
    osm = _poi("Le Castel Ac'h", "Kervenny, 29830 Ploudalmézeau", (GALION_SPOT[0] + 0.0153, GALION_SPOT[1]), poi_id=7983)
    summary, base, created, _ = _save(monkeypatch, RESTAURANTS, CASTEL, known=[osm])
    assert created == ["Le Castel Ac'h"] and summary["meme_nom_dans_la_commune"] == 1
    [(poi_id, source, kind, detail, _)] = base.wrote("INSERT INTO poi_signals")
    assert (poi_id, source, kind) == (7983, "doublons", "doublon_service") and '"autre_id": 99' in detail and '"distance_m": 17' in detail


def test_a_namesake_of_another_commune_makes_no_doubt(monkeypatch):
    """Le même nom dans une autre commune (autre code postal) reste un autre lieu : créé, sans doute."""
    elsewhere = _poi("Le Castel Ac'h", "Kervenny, 29880 Plouguerneau", (GALION_SPOT[0] + 0.0153, GALION_SPOT[1]), poi_id=7983)
    summary, base, created, _ = _save(monkeypatch, RESTAURANTS, CASTEL, known=[elsewhere])
    assert created == ["Le Castel Ac'h"] and "meme_nom_dans_la_commune" not in summary and not base.wrote("INSERT INTO poi_signals")


# --- Le jumeau masqué n'attend plus de relecture quand le service s'affiche ailleurs ---

def _superseded(monkeypatch, waiting):
    """Hippocampe vient d'être enregistré sur le service visible 850 ; 32023, masqué et sans position, porte le même nom."""
    from services import poi_review_service
    decided = []
    monkeypatch.setattr(poi_review_service, "decide_one",
                        lambda cursor, tab, poi_id, action, note, author, months: decided.append((tab, poi_id, action, author)))
    row = {"nom": "Hippocampe", "adresse": "Lampaul, 29830 Ploudalmézeau"}
    visible = _poi("Hippocampe", "Lampaul, 29830 Ploudalmézeau", GALION_SPOT, poi_id=850)
    masked = _poi("Hippocampe", "Bourg de Lampaul, 29830 Ploudalmézeau", (None, None), poi_id=32023, masked=1)
    closed = service_store.close_superseded(RESTAURANTS, _Base(waiting), row, GALION_SPOT, PLOUDALMEZEAU, [visible, masked], 850)
    return closed, decided


def test_the_masked_twin_stops_waiting_once_the_place_is_shown(monkeypatch):
    """Quand la fiche va sur le service visible, son jumeau masqué en attente est classé sans suite par la règle (Hippocampe, Ouessant)."""
    closed, decided = _superseded(monkeypatch, waiting=True)
    assert closed and decided == [("confirmer", 32023, "sans_suite", service_store.RULE_AUTHOR)]


def test_a_twin_masked_by_a_human_is_left_alone(monkeypatch):
    """Un jumeau masqué par un humain, sans relecture en attente, n'est pas touché."""
    closed, decided = _superseded(monkeypatch, waiting=False)
    assert not closed and decided == []


# --- La même règle du nom pour retrouver un service que pour réunir les réponses ---

RIBOUL_SPOT = (48.3488, -4.70276)


def test_a_name_with_the_word_saying_what_the_place_is_finds_the_known_place():
    """« Riboul Crêperie », au 2 boulevard de la Mer, retrouve le service « Riboul » à 200 m au lieu d'en créer un second (pilote de Plougonvelin, 13 novembre 2026)."""
    riboul = _poi("Riboul", "Résidence de l'Océan, boulevard de la Mer, 29217 Plougonvelin", RIBOUL_SPOT, poi_id=84)
    row = {"nom": "Riboul Crêperie", "adresse": "2 boulevard de la Mer, 29217 Plougonvelin"}
    assert find_known(row, (RIBOUL_SPOT[0] + 0.0018, RIBOUL_SPOT[1]), PLOUDALMEZEAU, [riboul]) == riboul


def test_two_places_whose_names_contradict_stay_two():
    """« Marché de Plougonvelin » ne retrouve pas « Épicerie de Plougonvelin » au même endroit : même nom une fois les mots retirés, mais un marché n'est pas une épicerie."""
    grocery = _poi("Épicerie de Plougonvelin", "Place, 29217 Plougonvelin", RIBOUL_SPOT, poi_id=81)
    row = {"nom": "Marché de Plougonvelin", "adresse": "Place, 29217 Plougonvelin"}
    assert find_known(row, RIBOUL_SPOT, PLOUDALMEZEAU, [grocery]) is None


def test_the_same_name_without_its_kind_further_in_the_commune_makes_a_doubt():
    """« Riboul Crêperie » trouvé à 2 km du « Riboul » de la même commune n'est pas rattaché d'office : un doute, comme pour un nom identique."""
    riboul = _poi("Riboul", "Boulevard de la Mer, 29830 Ploudalmézeau", RIBOUL_SPOT, poi_id=84)
    row = {"nom": "Riboul Crêperie", "adresse": "2 rue du Port, 29830 Ploudalmézeau"}
    far = (RIBOUL_SPOT[0] + 0.018, RIBOUL_SPOT[1])
    assert find_known(row, far, PLOUDALMEZEAU, [riboul]) is None
    assert service_store.namesake_in_commune(row, far, PLOUDALMEZEAU, [riboul]) == riboul


# --- Une fiche masquée ne montre rien : elle ne cache pas le café ---

def test_a_masked_restaurant_sheet_does_not_hide_the_cafe(monkeypatch):
    """Le bar L'Univers est enregistré en café : sa fiche restaurant est masquée (ce n'est pas un restaurant), elle ne l'affiche nulle part (Plougonvelin, 13 novembre 2026)."""
    univers = {"nom": "L'Univers", "genre": "bar", "categorie": "cafe", "adresse": GALION_ADDRESS, "pages": [SITE]}
    osm_cafe = _poi("L'univers", GALION_ADDRESS, GALION_SPOT, poi_id=96)
    summary, base, created, linked = _save(monkeypatch, COMMERCES, univers, known=[osm_cafe])
    assert summary["fiches"] == 1 and summary["deja_restaurant"] == 0 and linked == [(96, "cafe")]


def test_only_visible_sheets_are_read_as_shown_elsewhere():
    """Les fiches lues pour « déjà une fiche restaurant » ne sont que celles des services visibles."""
    base = _Base()
    base.description = [("id",)]
    service_store.known_sheets(base, PLOUDALMEZEAU, "restaurants")
    [(sql, _)] = base.queries
    assert "WHERE p.masque = 0 AND" in sql


# --- Un lieu mixte : le commerce trouvé à la place d'un restaurant enrichit le même service ---

def test_a_shop_found_at_a_restaurant_gets_its_sheet_on_the_same_service(monkeypatch):
    """Une boulangerie trouvée au nom et à l'adresse d'un restaurant déjà en base reçoit sa fiche commerce sur ce même service : un seul point sur la carte, deux fiches (La Maison du Phare)."""
    restaurant = _poi("La Maison du Phare", GALION_ADDRESS, GALION_SPOT, poi_id=30745)
    bakery = {"nom": "La Maison du Phare", "genre": "boulangerie, snack", "categorie": "boulangerie", "adresse": GALION_ADDRESS,
              "pages": [SITE]}
    summary, base, created, linked = _save(monkeypatch, COMMERCES, bakery, known=[restaurant])
    assert created == [] and linked == [(30745, "bakery")] and summary["fiches"] == 1
    [params] = base.wrote("REPLACE INTO commerces")
    assert params[0] == 30745
