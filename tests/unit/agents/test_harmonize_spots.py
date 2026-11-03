from agents import harmonize_spots


SPOT = {
    "id": 1,
    "description": "Nous avons dormi 1 nuit, assez calme. Vue sur la rade.",
    "type": "PARKING JOUR ET NUIT",
    "postal_code": "29200",
    "city_label": "Brest",
    "place_label": "172 Rue de Quimper",
}

PAYLOAD = {
    "description": "Stationnement calme avec vue sur la rade.",
    "services": ["Eau potable"],
    "a_verifier": False,
    "nuit_interdite": False,
}


class FakeLLM:
    """Double du service : enregistre les appels, renvoie une réponse fixée."""

    def __init__(self, payload=None):
        self.payload = payload or PAYLOAD
        self.calls = []

    def complete_json(self, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        return self.payload


class FakeCursor:
    """Curseur minimal : enregistre les requêtes, ne renvoie aucune ligne."""

    description = [("id",)]

    def __init__(self, columns=()):
        self.calls = []
        self.columns = columns  # colonnes renvoyées par information_schema

    def execute(self, query, params=None):
        self.calls.append((" ".join(query.split()), params))

    def fetchall(self):
        return [(column,) for column in self.columns]

    def fetchone(self):
        return (7,)  # le service cherché existe, avec l'id 7


# --- Prompt et schéma ---

def test_schema_asks_for_the_description_and_the_cited_services() -> None:
    schema = harmonize_spots.SPOT_SCHEMA
    assert set(schema["properties"]) == {"description", "services", "a_verifier", "nuit_interdite",
                                         "doute_nuit", "doute_nuit_raison"}
    # Liste fermée : pas de service inventé, pas de service exclu.
    allowed = schema["properties"]["services"]["items"]["enum"]
    assert "Eau potable" in allowed
    assert "Belle balade à moto" not in allowed
    assert schema["additionalProperties"] is False


def test_prompt_keeps_its_essential_rules() -> None:
    prompt = harmonize_spots.SYSTEM_PROMPT
    assert "n'invente rien" in prompt
    # v13 : tri tranché par listes, avertissements dans un paragraphe dédié.
    assert "GARDER" in prompt and "SUPPRIMER" in prompt
    assert "En cas de doute, supprime" in prompt
    assert "clients sans véhicule" in prompt
    # v17 : les deux trous révélés par la comparaison Sonnet / Opus.
    assert "anecdotes du séjour d'un contributeur" in prompt
    # v18 : commentaires comme témoignages, nuit interdite, pas de "Camping." seul.
    assert "Les commentaires sont des témoignages" in prompt
    assert "## nuit_interdite" in prompt
    # v20 : une interdiction seulement en saison ne masque pas le spot toute l'année.
    assert "interdiction de nuit en saison seulement" in prompt
    # v19 : "À savoir" et a_verifier recentrés, pas de commentaire sur les sources.
    assert "change la décision de venir" in prompt
    assert "ne parle jamais des sources" in prompt
    assert "simplement datée" in prompt
    assert "n'écris pas \"Camping.\" ou \"Parking.\"" in prompt
    assert "absent, interdit ou hors service" in prompt
    assert "À savoir :" in prompt
    # v22 : les informations anciennes se jugent par rapport à la date du jour.
    assert "## Informations anciennes" in prompt
    assert "Un minimum de nuits imposé par le lieu" in prompt
    # v15 : les services sont affichés en badges, pas répétés dans le texte.
    assert "ne la répète pas dans le texte" in prompt
    assert "N'ajoute aucune phrase" in prompt
    assert "Ne commente jamais la fiche" in prompt
    # Claude ne reçoit que la description : le prompt ne doit pas parler d'un contexte.
    assert "contexte" not in prompt.lower()
    # Application non limitée à une région.
    assert "Bretagne" not in prompt


def test_harmonize_one_passes_schema_and_returns_payload() -> None:
    service = FakeLLM()
    assert harmonize_spots.harmonize_one(service, SPOT) == PAYLOAD
    assert service.calls[0]["schema"] is harmonize_spots.SPOT_SCHEMA


def test_claude_receives_description_opening_and_reviews_only() -> None:
    from datetime import date
    spot = {**SPOT, "opening_period": "open from may 1st to sep 15th", "reviews": [
        {"review_date": date(2026, 9, 20), "rating": 5, "text": "Calme la nuit."},
    ]}
    service = FakeLLM()
    harmonize_spots.harmonize_one(service, spot)
    message = service.calls[0]["user"]
    assert SPOT["description"] in message
    assert "open from may 1st to sep 15th" in message
    assert '- 20/09/2026, 5/5 : "Calme la nuit."' in message
    # Pas de contexte géographique : Claude pourrait en déduire des informations.
    assert "Brest" not in message and "PARKING" not in message


def test_message_without_reviews_or_opening() -> None:
    message = harmonize_spots.build_user_message({"description": "Petit parking."})
    assert 'OUVERTURE : "non renseignée"' in message
    assert "(aucun)" in message


def test_message_gives_the_date_of_the_day() -> None:
    from datetime import date
    message = harmonize_spots.build_user_message({"description": "Petit parking."})
    assert message.startswith(f"DATE DU JOUR : {date.today():%d/%m/%Y}\n")


# --- Mise en forme de la réponse ---

def test_normalize_turns_empty_values_into_null() -> None:
    # NULL en base : le site retombe sur la description d'origine.
    fields = harmonize_spots.normalize({"description": "   "})
    assert fields == {"description_ia": None, "a_verifier": 0, "nuit_interdite": 0}


def test_a_verifier_is_stored_as_one_or_zero() -> None:
    assert harmonize_spots.normalize({"description": "Fermé.", "a_verifier": True})["a_verifier"] == 1


def test_a_doubt_about_the_night_goes_to_verification() -> None:
    fields = harmonize_spots.normalize({"description": "Parking.", "doute_nuit": True})
    assert fields["a_verifier"] == 1
    assert fields["nuit_interdite"] == 0


# --- Base de données ---

def test_spots_to_harmonize_are_selected_by_prompt_version() -> None:
    from utils.display_utils import HIDDEN_SPOT_TYPES

    cursor = FakeCursor()
    harmonize_spots.fetch_spots_to_harmonize(cursor, limit=20)
    query, params = cursor.calls[0]
    assert "prompt_version IS NULL OR prompt_version < %s" in query
    assert "duplicate_of_spot_id IS NULL" in query  # pas de doublons
    assert "details_scraped_at IS NOT NULL" in query  # ouverture et commentaires récupérés
    assert "p4n_removed = 0" in query  # pas de fiches disparues de Park4Night
    # Version actuelle, puis types masqués (jamais harmonisés), puis la limite.
    assert params == (harmonize_spots.PROMPT_VERSION, *HIDDEN_SPOT_TYPES, 20)


def test_only_new_leaves_the_spots_of_an_older_version_alone() -> None:
    from utils.display_utils import HIDDEN_SPOT_TYPES

    cursor = FakeCursor()
    harmonize_spots.fetch_spots_to_harmonize(cursor, only_new=True)
    query, params = cursor.calls[0]
    assert "WHERE prompt_version IS NULL AND" in query
    assert "prompt_version < %s" not in query
    assert tuple(params) == tuple(HIDDEN_SPOT_TYPES)


def test_write_records_the_prompt_version_and_never_the_description() -> None:
    # Garde-fou principal : la source Park4Night doit rester rejouable.
    cursor = FakeCursor()
    harmonize_spots.write_harmonization(cursor, 1, PAYLOAD)
    query, params = cursor.calls[0]
    assert "prompt_version = %s" in query
    assert "harmonized_at = NOW()" in query
    assert "description =" not in query.replace("description_ia =", "")
    assert params[-2:] == (harmonize_spots.PROMPT_VERSION, 1)


def test_write_never_lowers_the_flags() -> None:
    # Le SET s'applique dans l'ordre : a_verifier doit lire l'ancienne nuit_interdite.
    cursor = FakeCursor()
    harmonize_spots.write_harmonization(cursor, 1, PAYLOAD)
    query, _ = cursor.calls[0]
    assert "a_verifier = GREATEST(COALESCE(a_verifier, 0), %s, COALESCE(nuit_interdite, 0) > %s)" in query
    assert "nuit_interdite = GREATEST(COALESCE(nuit_interdite, 0), %s)" in query
    assert query.index("a_verifier = GREATEST") < query.index("nuit_interdite = GREATEST")


def test_update_spots_columns_adds_version_and_drops_obsolete_columns() -> None:
    cursor = FakeCursor(columns=["id", "enriched_at", "tags", "source_hash"])
    harmonize_spots.update_spots_columns(cursor, "bdd")
    statements = [query for query, _ in cursor.calls]
    assert "ALTER TABLE spots RENAME COLUMN enriched_at TO harmonized_at" in statements
    assert "ALTER TABLE spots ADD COLUMN prompt_version INT" in statements
    assert "ALTER TABLE spots ADD COLUMN a_verifier TINYINT(1)" in statements
    assert "ALTER TABLE spots ADD COLUMN nuit_interdite TINYINT(1)" in statements
    assert "ALTER TABLE spots DROP COLUMN tags" in statements
    assert "ALTER TABLE spots DROP COLUMN source_hash" in statements
    # Une colonne déjà absente n'est pas supprimée une seconde fois.
    assert "ALTER TABLE spots DROP COLUMN confidence" not in statements


def test_spot_ids_select_those_spots_even_if_already_harmonized() -> None:
    cursor = FakeCursor()
    harmonize_spots.fetch_spots_to_harmonize(cursor, spot_ids=[31, 44])
    query, params = cursor.calls[0]
    assert "WHERE id IN (%s,%s)" in query
    assert "prompt_version" not in query
    assert params == (31, 44)


def test_normalize_never_cuts_a_long_description() -> None:
    long_text = "Camping calme avec vue sur la mer. " * 30
    assert harmonize_spots.normalize({"description": long_text})["description_ia"] == long_text.strip()


def test_cited_services_complete_the_badges_with_source_ia() -> None:
    cursor = FakeCursor()
    harmonize_spots.write_harmonization(cursor, 1, PAYLOAD)
    statements = [query for query, _ in cursor.calls]
    # Les ajouts IA précédents sont effacés, les lignes Park4Night jamais touchées.
    assert "DELETE FROM spot_service WHERE spot_id = %s AND source = 'ia'" in statements
    insert = [call for call in cursor.calls if call[0].startswith("INSERT IGNORE INTO spot_service")]
    assert insert == [(
        "INSERT IGNORE INTO spot_service (spot_id, service_id, source) VALUES (%s, %s, 'ia')", (1, 7),
    )]


def test_no_cited_service_only_clears_previous_ia_services() -> None:
    cursor = FakeCursor()
    harmonize_spots.write_harmonization(cursor, 1, {"description": "Parking.", "services": []})
    assert not any(query.startswith("INSERT") for query, _ in cursor.calls)


def test_spot_service_gets_a_source_column() -> None:
    cursor = FakeCursor(columns=[])  # la colonne n'existe pas encore
    harmonize_spots.update_spot_service_table(cursor, "bdd")
    assert any("ADD COLUMN source" in query for query, _ in cursor.calls)
