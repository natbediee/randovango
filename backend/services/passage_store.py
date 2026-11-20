"""
La trace des passages en base (tables passages et passage_parts, déclarées dans db_init) : l'écrire et la relire.

Un passage est une chaîne d'agents lancée sur une ville (issue #204). Cette trace dit ce qui a été demandé (chaîne, ville,
catégories, origine) et où en est chaque partie. Ce que chaque appel d'agent a coûté reste dans llm_calls, sous le même
passage_id : load_calls le relit. Ce fichier ne contient que les requêtes ; les règles sont dans passage_service.py.
"""
import json
from datetime import datetime

from utils.db_utils import MySQLUtils

# Les états d'un passage, et ceux de chacune de ses parties.
QUEUED = "en_file"          # demandé, pas encore commencé : il partira dès que le verrou et le budget le permettent
WAITING = "en_attente"      # demandé par l'ETL alors que la mise à jour automatique est coupée : attend l'admin (#211)
RUNNING = "en_cours"
DONE = "fini"
FAILED = "echec"
TO_DO = "a_faire"           # une partie que le passage n'a pas encore commencée

PASSAGE_COLUMNS = """p.passage_id, p.chain, p.city_id, p.origin, p.status, p.requested_at, p.started_at, p.finished_at,
                     p.error, p.resumed_from, c.name AS city_name, c.commune AS city_commune"""


def _write(sql: str, rows: list) -> None:
    """Exécute une écriture pour chaque ligne de `rows`, puis la valide (commit)."""
    with MySQLUtils.open_cursor() as (connection, cursor):
        for row in rows:
            cursor.execute(sql, row)
        connection.commit()


def _read(sql: str, params: tuple) -> list:
    """Les lignes d'une lecture, chacune en dictionnaire {colonne: valeur}."""
    with MySQLUtils.open_cursor(dictionary=True) as (connection, cursor):
        cursor.execute(sql, params)
        return cursor.fetchall()


def insert_passage(passage_id: str, chain: str, city_id: int, origin: str, parts: list,
                   resumed_from: str | None = None, status: str = QUEUED) -> None:
    """
    Écrit un passage demandé et ses parties, toutes à faire, dans l'ordre où elles passeront. Le passage est en file,
    ou en attente de l'admin quand la mise à jour automatique est coupée.
    """
    _write("""INSERT INTO passages (passage_id, chain, city_id, origin, status, requested_at, resumed_from)
              VALUES (%s, %s, %s, %s, %s, %s, %s)""",
           [(passage_id, chain, city_id, origin, status, datetime.now(), resumed_from)])
    _write("INSERT INTO passage_parts (passage_id, part, position, status) VALUES (%s, %s, %s, %s)",
           [(passage_id, part, position, TO_DO) for position, part in enumerate(parts, start=1)])


def set_passage_status(passage_id: str, status: str, error: str | None = None) -> None:
    """
    Change l'état d'un passage : son début est noté quand il passe en cours, sa fin quand il finit ou échoue. Un passage
    remis en file (relancé par l'admin) garde sa date de demande : il reprend sa place dans la file.
    """
    if status == QUEUED:
        _write("UPDATE passages SET status = %s WHERE passage_id = %s", [(status, passage_id)])
    elif status == RUNNING:
        _write("UPDATE passages SET status = %s, started_at = %s WHERE passage_id = %s",
               [(status, datetime.now(), passage_id)])
    else:
        _write("UPDATE passages SET status = %s, finished_at = %s, error = %s WHERE passage_id = %s",
               [(status, datetime.now(), error, passage_id)])


def set_part(passage_id: str, part: str, status: str, step: str | None = None, summary: dict | None = None,
             error: str | None = None) -> None:
    """Change l'état d'une partie, avec l'étape notée par le code, le bilan de l'enregistrement ou la raison d'un échec."""
    now = datetime.now()
    _write("""UPDATE passage_parts
              SET status = %s, step = %s, summary = %s, error = %s,
                  started_at = COALESCE(started_at, %s),
                  finished_at = CASE WHEN %s IN ('fini', 'echec') THEN %s ELSE NULL END
              WHERE passage_id = %s AND part = %s""",
           [(status, step, json.dumps(summary, ensure_ascii=False) if summary is not None else None, error, now,
             status, now, passage_id, part)])


def load_passage(passage_id: str) -> dict | None:
    """Le passage, avec le nom et la commune de sa ville ; None s'il n'existe pas."""
    rows = _read(f"""SELECT {PASSAGE_COLUMNS} FROM passages p LEFT JOIN cities c ON c.id = p.city_id
                     WHERE p.passage_id = %s""", (passage_id,))
    return rows[0] if rows else None


def load_parts(passage_id: str) -> list:
    """Les parties d'un passage, dans l'ordre où elles passent, avec leur bilan relu depuis le JSON."""
    rows = _read("""SELECT part, position, status, step, started_at, finished_at, summary, error
                    FROM passage_parts WHERE passage_id = %s ORDER BY position""", (passage_id,))
    for row in rows:
        row["summary"] = json.loads(row["summary"]) if row["summary"] else None
    return rows


def load_calls(passage_id: str) -> list:
    """
    Les appels d'agents du passage, lus dans llm_calls, dans l'ordre : agent, étape, statut et coût de chacun, avec
    leur jour et leur moteur pour convertir le coût en euros et dire s'il est réel ou un équivalent API.
    """
    return _read("""SELECT agent, etape, status, cost_usd, called_at, engine FROM llm_calls
                    WHERE passage_id = %s ORDER BY called_at, id""", (passage_id,))


def passage_ids(status: str, limit: int) -> list:
    """Les identifiants des passages dans cet état, du plus récent au plus ancien."""
    rows = _read("SELECT passage_id FROM passages WHERE status = %s ORDER BY requested_at DESC LIMIT %s",
                 (status, limit))
    return [row["passage_id"] for row in rows]


def recent_ids(limit: int) -> list:
    """Les identifiants des derniers passages finis ou en échec, du plus récent au plus ancien."""
    rows = _read("""SELECT passage_id FROM passages WHERE status IN ('fini', 'echec')
                    ORDER BY requested_at DESC LIMIT %s""", (limit,))
    return [row["passage_id"] for row in rows]


def resumed_by(passage_id: str) -> str | None:
    """Le passage qui reprend celui-ci (sa colonne resumed_from le désigne), ou None s'il n'a pas été repris."""
    rows = _read("SELECT passage_id FROM passages WHERE resumed_from = %s", (passage_id,))
    return rows[0]["passage_id"] if rows else None


def oldest_queued() -> str | None:
    """Le passage en file depuis le plus longtemps : c'est lui qui part en premier. None si la file est vide."""
    rows = _read("SELECT passage_id FROM passages WHERE status = %s ORDER BY requested_at, passage_id LIMIT 1",
                 (QUEUED,))
    return rows[0]["passage_id"] if rows else None



def finished_parts(chain: str, city_ids: list) -> set:
    """
    Les parties déjà finies pour ces villes (les villes d'une même commune), dans n'importe quel passage, même un échec
    (une catégorie finie avant la coupure reste faite).
    La base est commune à toutes les branches, alors que chaque worktree a son propre dossier de fichiers des passages :
    un backend de branche ne voyait pas Combrit et Ergué-Gabéric, cherchées depuis main, et les a payées une seconde
    fois (nuit du 19 au 20 novembre 2026).
    """
    placeholders = ",".join(["%s"] * len(city_ids))
    rows = _read(f"""SELECT DISTINCT pp.part FROM passages p JOIN passage_parts pp ON pp.passage_id = p.passage_id
                     WHERE p.chain = %s AND p.city_id IN ({placeholders}) AND pp.status = 'fini'""",
                 (chain, *city_ids))
    return {row["part"] for row in rows}


def open_parts(chain: str, city_ids: list) -> set:
    """
    Les parties déjà demandées pour ces villes (les villes d'une même commune) dans un passage en file, en attente ou
    en cours, ou dans un échec pas encore repris : l'ETL ne les redemande pas, une seconde rando dans la même commune
    ne fait pas payer deux fois.
    Un échec pas encore repris compte aussi : c'est l'admin qui le reprend, et sa reprise refait ces catégories. Sans
    cela, une seconde rando à Paimpont avait demandé un nouveau passage pendant que le premier attendait sa reprise,
    et reprendre l'échec aurait payé la ville deux fois (19 novembre 2026).
    """
    placeholders = ",".join(["%s"] * len(city_ids))
    rows = _read(f"""SELECT DISTINCT pp.part FROM passages p JOIN passage_parts pp ON pp.passage_id = p.passage_id
                     WHERE p.chain = %s AND p.city_id IN ({placeholders})
                       AND (p.status IN ('en_file', 'en_attente', 'en_cours')
                            OR (p.status = 'echec' AND NOT EXISTS
                                (SELECT 1 FROM passages r WHERE r.resumed_from = p.passage_id)))""",
                 (chain, *city_ids))
    return {row["part"] for row in rows}
