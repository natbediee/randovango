"""La lecture du fichier FINESS : le fichier du jour est trouvé, seules les pharmacies (catégorie 620) sont gardées."""
import gzip
import io
import json

from etl.extract.api_finess import daily_file_url, read_pharmacies_file

# Deux entités juridiques : une pharmacie (catégorie 620) et une maison de retraite (catégorie 500).
FILE = {
    "schemaVersion": "v1.0.0",
    "gco": [{"pmSmsseId": "403"}],
    "pmej": [
        {"informationsGeneralesPMEJ": {"denominationPm": "PHARMACIE RIVOALEN-COUSIN"},
         "ege": [{"categorieentiteGeographiqueExercice": "620",
                  "informationsGeneralesEGE": {"numFinessEge": "290011048"}}]},
        {"informationsGeneralesPMEJ": {"denominationPm": "MAISON DE RETRAITE"},
         "ege": [{"categorieentiteGeographiqueExercice": "500",
                  "informationsGeneralesEGE": {"numFinessEge": "010000016"}}]},
    ],
}


def _compressed(content: dict) -> io.BytesIO:
    return io.BytesIO(gzip.compress(json.dumps(content).encode()))


def test_only_the_pharmacies_are_read():
    """Seuls les établissements de catégorie 620 sont gardés : la maison de retraite n'est pas une pharmacie."""
    pharmacies = read_pharmacies_file(_compressed(FILE))
    assert [o["informationsGeneralesEGE"]["numFinessEge"] for o in pharmacies] == ["290011048"]


def test_the_daily_file_is_chosen_among_the_monthly_copies():
    """Le jeu de données garde aussi les copies mensuelles : seul le fichier du jour est téléchargé."""
    dataset = {"resources": [
        {"title": "finess-structures-mensuel-202610.json.gz", "url": "https://exemple/mensuel"},
        {"title": "finess-structures-journalier-20261114.json.gz", "url": "https://exemple/journalier"},
    ]}
    assert daily_file_url(dataset) == "https://exemple/journalier"


def test_no_daily_file_gives_nothing():
    """Sans fichier du jour, le passage s'arrête sans rien écrire."""
    assert daily_file_url({"resources": []}) is None
