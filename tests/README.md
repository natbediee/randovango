# Tests

| Dossier | Ce qu'on y met | Ce qu'il faut pour les lancer |
| --- | --- | --- |
| `unit/` | Une fonction ou un module testé seul : ni base, ni réseau, ni navigateur, ni appel à un modèle. | Rien : `pytest tests/unit` |
| `functional/` | Le comportement de l'application vu de l'extérieur, décrit en scénarios (pytest-bdd). | Rien : `pytest tests/functional` |
| `functional/parcours_complet.py` | Le parcours à travers les écrans, dans un vrai navigateur. | Les conteneurs démarrés : `.venv/bin/python tests/functional/parcours_complet.py` |

Un scénario s'écrit en français dans `functional/features/*.feature`, et ses phrases sont reliées
au code dans le fichier `test_*.py` du même nom.
