"""Les supermarchés : une catégorie de plus dans la chaîne commune, où l'enseigne ne prouve rien sans l'adresse."""
from agents import find_services, llm_config, service_chain
from agents.find_supermarches import SUPERMARCHES, register_facts, register_is_proof

REGISTER = {"actifs": [
    {"nom": "LIDL", "adresse": "12 RUE DE BREST 29830 PLOUDALMEZEAU", "activite": "47.11D", "actif_depuis": "2019-03-01"},
    {"nom": "INTERMARCHE", "adresse": "ROUTE DU DREVERZ 29100 DOUARNENEZ", "activite": "47.11D", "actif_depuis": "2025-04-14"},
    {"nom": "CENTRE E. LECLERC", "adresse": "160 ROUTE DE BREST 29000 QUIMPER", "activite": "47.11F", "actif_depuis": "2001-01-01"},
]}


def _shop(name, address):
    return {"nom": name, "categorie": "supermarche", "genre": "supermarché", "adresse": address, "pages": []}


def test_the_register_proves_a_supermarket_by_its_name_and_its_address():
    """Le registre prouve le Lidl inscrit à son nom et à son adresse, et donne sa date (12 rue de Brest, Ploudalmézeau)."""
    lidl = _shop("Lidl", "12 rue de Brest, 29830 Ploudalmézeau")
    assert register_is_proof(lidl, REGISTER)
    assert register_facts(lidl, REGISTER) == {"registre_depuis": "2019-03-01", "au_registre": True}


def test_the_same_brand_at_another_address_is_not_proved():
    """Une enseigne est présente à plusieurs adresses : le Lidl inscrit rue de Brest ne prouve pas celui d'une autre rue."""
    other = _shop("Lidl", "3 route de Portsall, 29830 Ploudalmézeau")
    assert not register_is_proof(other, REGISTER)
    assert register_facts(other, REGISTER) == {"registre_depuis": None, "au_registre": False}


def test_another_shop_at_the_address_is_not_proved():
    """L'adresse seule ne prouve rien non plus : un autre nom au 12 rue de Brest n'est pas le Lidl du registre."""
    assert not register_is_proof(_shop("Biocoop", "12 rue de Brest, 29830 Ploudalmézeau"), REGISTER)


def test_a_longer_brand_name_at_the_address_is_the_same_shop():
    """Le registre écrit l'enseigne autrement : « E.Leclerc » est prouvé par CENTRE E. LECLERC au même numéro (Quimper)."""
    assert register_is_proof(_shop("E.Leclerc", "160 route de Brest, 29000 Quimper"), REGISTER)


def test_a_retail_park_without_a_street_number_is_proved_by_its_street():
    """Une zone commerciale n'a pas de numéro : « Intermarché Super », route du Dreverz, est prouvé par la ligne de cette route (Douarnenez)."""
    assert register_is_proof(_shop("Intermarché Super", "Route du Dreverz, 29100 Douarnenez"), REGISTER)
    assert not register_is_proof(_shop("Intermarché Super", "Route de Brest, 29100 Douarnenez"), REGISTER)


def test_the_supermarkets_are_one_more_category_of_the_chain():
    """Les supermarchés passent dans la chaîne commune : une seule recherche, les codes 47.11D et 47.11F, leurs trois agents déclarés."""
    assert SUPERMARCHES in find_services.CATEGORIES
    assert len(SUPERMARCHES.searches) == 1 and SUPERMARCHES.register_activities == ("47.11D", "47.11F")
    assert {SUPERMARCHES.find_agent, SUPERMARCHES.analyze_agent, SUPERMARCHES.prove_agent} <= set(llm_config.AGENTS)
    schema = service_chain.search_schema(SUPERMARCHES)
    assert "supermarches" in schema["properties"] and "pas_un_supermarche" in str(service_chain.analysis_schema(SUPERMARCHES))


def test_the_sheet_goes_to_the_shops_table_and_the_service_to_the_supermarket_tab():
    """La fiche d'un supermarché va dans la table des commerces, et le service créé rejoint l'onglet « Supermarché »."""
    assert SUPERMARCHES.sheet_table == "commerces" and SUPERMARCHES.categories == ["supermarche"]
    assert SUPERMARCHES.new_service(_shop("Lidl", None)) == "supermarket"


def test_a_commune_with_more_supermarkets_than_one_search_returns_is_searched_by_zones():
    """Une recherche rend 15 lieux au plus : au-delà de 15 lignes au registre, les supermarchés d'une ville sont cherchés par zones."""
    lines = [{"nom": f"Magasin {number}"} for number in range(16)]
    assert service_chain.is_big_city(SUPERMARCHES, {"actifs": lines}) and not service_chain.is_big_city(SUPERMARCHES, {"actifs": lines[:15]})
