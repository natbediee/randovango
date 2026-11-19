# Plafonds de l'API

Certaines routes de l'API sont plafonnées : au-delà d'un nombre d'appels en peu de temps, elles répondent
**429 Too Many Requests** et ne s'exécutent pas. Le message de refus est en français, dans le champ `detail` ;
le front l'affiche dans un bandeau en haut de page (`frontend/static/js/common.js`, `showTooManyRequests`).

Le code est dans `backend/api/rate_limit.py` (slowapi). Les compteurs sont en mémoire : ils repartent de zéro
au redémarrage de l'API, ce qui suffit pour un seul serveur.

## Les plafonds

| Route | Plafond | Compté par | Pourquoi |
| --- | --- | --- | --- |
| `POST /api/step1/create_plan` | 1 par jour | voyageur | Un voyage gratuit par jour : chaque voyage met les agents de Vany au travail, et chaque appel à un modèle de langage coûte. |
| `PUT /api/step1/update_day_city/{plan_id}` | 15 par heure | voyageur | Une ville par jour du séjour (7 au plus), plus quelques changements d'avis. |
| `PUT /api/step3/update_plan/{plan_id}` | 30 par heure | voyageur | Le spot du jour se choisit en quelques clics : environ 3 par jour sur 7 jours. |
| `POST /api/auth/guest` | 10 par heure | adresse IP | Un jeton invité neuf donne des compteurs neufs : sans ce plafond, il suffirait d'en demander un autre. |
| `POST /api/auth/login` | 5 **échecs** en 15 minutes | nom de compte | Empêche d'essayer des mots de passe sans fin, sur les comptes admin compris (issue #264). |
| `POST /api/auth/login` | 20 **échecs** en 15 minutes | adresse IP | Arrête un script qui essaie beaucoup de noms de compte depuis la même machine. |

« Voyageur » veut dire : le compte ou l'invité du cookie de connexion, sinon l'adresse IP. Compter par voyageur
évite qu'un même wifi de camping, partagé par plusieurs voyageurs, ne les bloque tous ensemble.

## La connexion, un plafond à part

Le plafond de la connexion ne compte pas les appels, mais les **essais manqués** (mot de passe faux ou compte
inconnu). Une connexion réussie ne compte jamais.

- Le compteur d'un compte vaut depuis toutes les adresses : changer de machine ne donne pas 5 essais de plus.
- Le nom de compte est compté en minuscules : taper « Admin » au lieu de « admin » ne remet pas le compteur à zéro.
- Une fois le plafond atteint, même le bon mot de passe est refusé, jusqu'à la fin des 15 minutes.
  Les 15 minutes partent du premier échec compté.
- Le blocage dure peu, pour qu'un compte bloqué exprès par quelqu'un d'autre ne le reste pas longtemps.
- Chaque refus est noté dans le journal des connexions (`auth_log`), avec l'action `login_rate_limited`
  et le code 429, comme les échecs (`failed_login`, 401) et les connexions réussies (`login`, 200).
- Message : « Trop d'essais de connexion manqués. Réessaie dans 15 minutes au plus. »

## L'adresse IP

Derrière nginx, l'API ne voit que l'adresse de nginx : nginx transmet la vraie dans l'en-tête `X-Real-IP`
(`nginx/randovango.conf`). Cet en-tête n'est fiable que si l'API n'est joignable que par nginx ; sinon,
un visiteur pourrait l'écrire lui-même et changer d'adresse à chaque essai.

## Sur le poste de développement

`RATE_LIMIT_ENABLED=0` coupe tous les plafonds, celui de la connexion compris : on compose beaucoup de voyages
pour tester, et l'adresse de la développeuse serait vite bloquée. Sans ce réglage, les plafonds sont actifs
(préprod, prod).
