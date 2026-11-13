"""La structure de la base se rejoue sans risque : seules les colonnes absentes sont ajoutées."""
from db_init.db_randovango import add_missing_columns, add_missing_indexes, parse_create_table

STATEMENT = """
            CREATE TABLE IF NOT EXISTS exemple (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                nom VARCHAR(10) NOT NULL DEFAULT 'a, b',
                parent_id INT,
                UNIQUE (nom),
                INDEX idx_nom (nom),
                FOREIGN KEY (parent_id) REFERENCES exemple(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """


class FakeCursor:
    def __init__(self, existing):
        self.existing = existing
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append(query)

    def fetchall(self):
        return [(column,) for column in self.existing]


def test_parse_separates_columns_from_keys():
    """La définition d'une table est lue en colonnes d'un côté, clés étrangères de l'autre."""
    table, columns, foreign_keys = parse_create_table(STATEMENT)
    assert table == "exemple"
    assert columns == {"id": "INT NOT NULL AUTO_INCREMENT PRIMARY KEY", "nom": "VARCHAR(10) NOT NULL DEFAULT 'a, b'",
                       "parent_id": "INT"}
    assert foreign_keys == {"parent_id": "FOREIGN KEY (parent_id) REFERENCES exemple(id) ON DELETE CASCADE"}


def test_a_missing_column_is_added_with_its_foreign_key():
    """Une colonne absente est ajoutée, avec sa clé étrangère."""
    cursor = FakeCursor(["id", "nom"])
    assert add_missing_columns(cursor, "base", STATEMENT) == ["parent_id"]
    assert cursor.calls[1:] == ["ALTER TABLE exemple ADD COLUMN parent_id INT",
                                "ALTER TABLE exemple ADD FOREIGN KEY (parent_id) REFERENCES exemple(id) ON DELETE CASCADE"]


def test_a_complete_table_is_left_alone():
    """Une table complète n'est pas touchée."""
    cursor = FakeCursor(["id", "nom", "parent_id", "colonne_en_plus"])
    assert add_missing_columns(cursor, "base", STATEMENT) == []
    assert len(cursor.calls) == 1


def test_a_missing_named_index_is_added():
    """Un index nommé absent est ajouté."""
    cursor = FakeCursor(["PRIMARY", "nom"])
    assert add_missing_indexes(cursor, "base", STATEMENT) == ["idx_nom"]
    assert cursor.calls[1:] == ["ALTER TABLE exemple ADD INDEX idx_nom (nom)"]


def test_an_existing_index_is_left_alone():
    """Un index déjà là n'est pas recréé."""
    cursor = FakeCursor(["PRIMARY", "idx_nom"])
    assert add_missing_indexes(cursor, "base", STATEMENT) == []
    assert len(cursor.calls) == 1
