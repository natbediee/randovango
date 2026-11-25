"""
La source des spots déjà lue pour une ville (spot_chain.source_already_read, issue #316) : histo_scrap est lu par l'id
de la ville. Ni base : la connexion à MySQL est remplacée.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from services import spot_chain


@pytest.mark.parametrize("count,read", [(3, True), (0, False)])
def test_a_city_with_rows_in_histo_scrap_has_its_source_already_read(monkeypatch, count, read):
    """Une ville avec des lignes dans histo_scrap a déjà sa source des spots lue ; sans ligne, elle reste à lire."""
    cursor = MagicMock()
    cursor.fetchone.return_value = (count,)

    @contextmanager
    def open_cursor():
        yield None, cursor
    monkeypatch.setattr(spot_chain.MySQLUtils, "open_cursor", open_cursor)
    assert spot_chain.source_already_read(12) is read
    assert cursor.execute.call_args.args[1] == (12,)
