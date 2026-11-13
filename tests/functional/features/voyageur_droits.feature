# language: fr
Fonctionnalité: Le voyage d'un voyageur n'est qu'à lui
  Un voyageur, avec ou sans compte, compose son voyage jour après jour : ville, rando, spot, services,
  pépites de Vany. Lui seul peut le lire ou le modifier, et l'API ne le croit pas sur parole :
  le propriétaire d'un plan vient toujours de son jeton.

  Scénario: Sans jeton, on ne crée pas de voyage
    Étant donné un visiteur sans jeton
    Quand il crée un voyage
    Alors la réponse est 401
    Et Vany ne lance aucune recherche

  Scénario: Un invité crée son voyage, qui lui appartient
    Étant donné l'invité "Léa"
    Quand il crée un voyage
    Alors la réponse est 200
    Et le plan appartient à l'invité "Léa"
    Et Vany lance une recherche

  Scénario: Un compte crée son voyage, qui lui appartient
    Étant donné le compte "Camille"
    Quand il crée un voyage
    Alors la réponse est 200
    Et le plan appartient au compte "Camille"

  Scénario: Se déclarer quelqu'un d'autre ne sert à rien
    Étant donné l'invité "Léa"
    Quand il crée un voyage en se déclarant le compte "Camille"
    Alors la réponse est 200
    Et le plan appartient à l'invité "Léa"

  Scénario: Un invité retrouve son carnet
    Étant donné l'invité "Léa"
    Et un voyage composé par l'invité "Léa"
    Quand il ouvre le carnet de ce voyage
    Alors la réponse est 200

  Plan du scénario: Le voyage d'un autre est refusé, en lecture comme en écriture
    Étant donné <qui>
    Et un voyage composé par <proprietaire>
    Quand il <action> ce voyage
    Alors la réponse est 403
    Et rien n'est écrit dans ce voyage

    Exemples:
      | qui                 | proprietaire        | action                       |
      | l'invité "Léa"      | l'invité "Tom"      | ouvre le carnet de           |
      | l'invité "Léa"      | l'invité "Tom"      | choisit le spot de           |
      | l'invité "Léa"      | l'invité "Tom"      | ajoute une pépite à          |
      | l'invité "Léa"      | le compte "Camille" | ouvre le carnet de           |
      | le compte "Camille" | l'invité "Tom"      | choisit le spot de           |
      | le compte "Camille" | le compte "Louis"   | ouvre les pépites du jour de |

  Scénario: Un voyage qui n'existe pas
    Étant donné l'invité "Léa"
    Quand il ouvre le carnet du voyage 999
    Alors la réponse est 404

  Scénario: Un jeton invité expiré ne rouvre pas le voyage
    Étant donné l'invité "Léa" dont le jeton a expiré
    Et un voyage composé par l'invité "Léa"
    Quand il ouvre le carnet de ce voyage
    Alors la réponse est 401

  Scénario: Un voyage gratuit par jour
    Étant donné l'invité "Léa"
    Et il a déjà créé un voyage aujourd'hui
    Quand il crée un voyage
    Alors la réponse est 429
    Et Vany ne lance qu'une seule recherche
