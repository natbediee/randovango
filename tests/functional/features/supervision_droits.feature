# language: fr
Fonctionnalité: La supervision est réservée aux admins
  Les décisions de la supervision priment sur les agents et changent ce que voient les voyageurs :
  seul un compte admin peut les lire, les prendre ou les annuler.

  Plan du scénario: Sans jeton valide, aucune route ne répond
    Étant donné un visiteur avec un jeton <jeton>
    Quand il appelle <methode> <route>
    Alors la réponse est 401
    Et aucune décision n'est enregistrée

    Exemples:
      | jeton    | methode | route                          |
      | absent   | GET     | /api/supervision/reviews/spots |
      | invalide | GET     | /api/supervision/reviews/spots |
      | expiré   | GET     | /api/supervision/reviews/spots |
      | absent   | POST    | /api/supervision/decisions     |
      | invalide | DELETE  | /api/supervision/decisions/1   |
      | absent   | GET     | /api/supervision/reviews/summary |
      | absent   | POST    | /api/supervision/edit/services/decisions |

  Scénario: Le jeton n'est lu que dans le cookie de connexion
    Étant donné un admin qui envoie son jeton valide dans l'en-tête Authorization, sans cookie
    Quand il appelle GET /api/supervision/reviews/spots
    Alors la réponse est 401

  Scénario: Un voyageur sans compte est refusé, même avec un jeton valide
    Étant donné un voyageur sans compte, avec son jeton invité
    Quand il appelle GET /api/supervision/reviews/spots
    Alors la réponse est 403
    Et aucune décision n'est enregistrée

  Plan du scénario: Un compte qui n'est pas admin est refusé partout
    Étant donné un utilisateur connecté avec le rôle "<role>"
    Quand il appelle <methode> <route>
    Alors la réponse est 403
    Et aucune décision n'est enregistrée

    Exemples:
      | role        | methode | route                                   |
      | contributor | GET     | /api/supervision/reviews/spots          |
      | user        | GET     | /api/supervision/reviews/spots          |
      | contributor | POST    | /api/supervision/decisions              |
      | contributor | PUT     | /api/supervision/decisions/1            |
      | contributor | DELETE  | /api/supervision/decisions/1            |
      | contributor | GET     | /api/supervision/reviews/services       |
      | contributor | POST    | /api/supervision/services/decisions     |
      | contributor | POST    | /api/supervision/services/audit/1       |
      | contributor | DELETE  | /api/supervision/services/decisions/1   |
      | contributor | GET     | /api/supervision/reviews/summary        |
      | contributor | GET     | /api/supervision/edit/services           |
      | contributor | POST    | /api/supervision/services/fiche          |
      | contributor | GET     | /api/supervision/edit/services/fiche/1   |
      | contributor | POST    | /api/supervision/edit/services/fiche     |
      | contributor | POST    | /api/supervision/edit/services/decisions |
      | contributor | DELETE  | /api/supervision/edit/services/decisions/1 |
      | contributor | GET     | /api/supervision/edit/spots              |
      | contributor | POST    | /api/supervision/edit/spots/decisions    |
      | contributor | PUT     | /api/supervision/edit/spots/decisions/1  |
      | contributor | DELETE  | /api/supervision/edit/spots/decisions/1  |
      | contributor | POST    | /api/supervision/edit/spots/openings     |
      | contributor | DELETE  | /api/supervision/edit/spots/openings/1   |

  Scénario: Un admin enregistre une décision à son nom
    Étant donné un utilisateur connecté avec le rôle "admin"
    Quand il décide de "garder" le spot 574
    Alors la réponse est 200
    Et la décision "garder" sur le spot 574 est enregistrée au nom de l'utilisateur

  Scénario: Une décision inconnue est refusée
    Étant donné un utilisateur connecté avec le rôle "admin"
    Quand il décide de "supprimer" le spot 574
    Alors la réponse est 422
    Et aucune décision n'est enregistrée

  Scénario: Un rôle admin retiré vaut tout de suite, même avec un jeton encore valide
    Étant donné un utilisateur connecté avec le rôle "admin"
    Et son rôle admin vient de lui être retiré
    Quand il décide de "garder" le spot 574
    Alors la réponse est 403
    Et aucune décision n'est enregistrée
