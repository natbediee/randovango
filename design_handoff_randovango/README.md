# Handoff : RandoVanGo — refonte du parcours de planification

## Overview
RandoVanGo est un planificateur de voyage van life + randonnée. L'utilisateur choisit une durée de séjour, puis pour chaque jour : une ville, une randonnée, un spot pour la nuit et des services utiles ; à la fin il obtient un carnet de voyage (PDF). Cette refonte introduit une nouvelle identité visuelle (mascotte **Vany**, header sombre, palette crème/menthe/teal) déclinée sur l'ensemble du parcours, en version desktop **et** mobile.

## About the Design Files
Les fichiers de ce dossier sont des **références de design réalisées en HTML** — des prototypes qui montrent l'apparence et le comportement visés, ce ne sont **pas** du code de production à copier tel quel. Le travail consiste à **recréer ces designs dans l'environnement réel du produit** (le codebase existant de RandoVanGo — front actuel dans `frontend/`) en respectant ses conventions (framework, gestion d'état, routing, appels API réels pour météo/carte/paiement), et non à embarquer ce HTML tel quel.

`Projet validé.dc.html` est un fichier "Design Component" (format propriétaire de l'outil de design utilisé) mais reste du HTML/CSS statique standard sous le capot — il s'ouvre dans n'importe quel navigateur (double-clic, ou via un petit serveur statique) grâce au `support.js` fourni à côté. Toutes les couleurs, polices et mesures sont en CSS inline directement lisibles dans la source.

## Fidelity
**Haute fidélité (hifi)** : couleurs, typographies, espacements et contenus sont définitifs. Le développeur doit recréer l'UI au pixel près, en utilisant les librairies/patterns déjà en place dans le codebase RandoVanGo.

## Fichier de référence
Toutes les pages sont centralisées, **dans l'ordre du site**, dans **`Projet validé.dc.html`** — pour chaque page : la version desktop (header sombre + Vany) suivie de la version mobile (390 px). Chaque section porte un attribut `data-screen-label="NN — Nom"` reprenant l'ordre ci-dessous.

## Design Tokens

### Couleurs
- Fond crème (page) : `#F9F8F1`
- Header / bandeau sombre : `#22424B`
- Texte principal : `#22424B`
- Texte secondaire / muted : `#64797C`
- Texte tertiaire (labels majuscules) : `#7A8C89` / `#9AA6A0`
- Surface menthe (cartes mises en avant, bandeau Vany) : `#E6F3F0`
- Bordure menthe : `#C9E4DD` / `#A9DCD3`
- Couleur d'action / accent principal (boutons, liens, focus) : `#2E7D86`
- Bordure focus (champ actif, date) : `#8FB5AE`
- Bordure neutre (cartes) : `#E8E6DB`
- Séparateurs internes : `#F0EEE3`
- Tag succès : fond `#F1F7E0`, bordure `#D5E5A8`, texte `#5F7A24`
- Tag avertissement : fond `#FBF3DE`, bordure `#ECDDB4`, texte `#9A7A2E`
- Surfaces blanches : `#FFFFFF`
- Sur fond sombre : texte `#F9F8F1` / `#F1F4F2`, accent clair `#7FC4CC` / `#9FDBE2`, libellé inactif `#B8CBCE`

### Typographie
- Titres / UI forte (`Archivo`, Google Fonts) : poids 700–800, letter-spacing -0.3 à -0.8px
- Texte courant / UI (`Public Sans`, Google Fonts) : poids 400–700
- Codes / dates (`ui-monospace, Menlo, monospace`)
- Tailles desktop : titres de page 24–38px, titres de carte 16–20px, corps 13.5–15.5px, labels 10.5–12.5px
- Tailles mobile : titres de page 23–28px, titres de carte 14.5–16.5px, corps 12.5–14px, labels 10–11.5px

### Forme
- Rayon des cartes : 14–16px (18px pour la carte « cerise sur le gâteau »)
- Boutons / pills / inputs : rayon `999px` (pilule complète)
- Petits badges/tags : rayon 5–8px
- Ombre (rare, réservée aux champs actifs) : `0 1px 3px rgba(34,66,75,0.08)`
- Container desktop de référence : 1240px de large
- Container mobile de référence : 390px de large (gabarit iPhone standard)

## Screens / Views
Ordre du parcours, desktop puis mobile pour chacun (voir anchors `data-screen-label` dans `Projet validé.dc.html`) :

### 01 — Accueil
**Purpose** : point d'entrée, choix de la durée du séjour et de la date de départ, ou bascule vers le chat IA.
**Layout** : header sombre (logo + nav) → hero (titre + texte + photo van 480×250 desktop / pleine largeur 170px haut mobile) → bandeau « parcours en 6 étapes » (icônes numérotées reliées par des traits) → carte « Combien de jours pars-tu ? » (5 cartes de durée en grille, sélection avec bordure teal + coche) → champ date → CTA pilule pleine couleur → bandeau menthe « Voyage 100% IA » avec Vany (image alignée en bas à gauche d'une rangée texte+CTA).
**Mobile** : header compact avec icône burger (3 traits) remplaçant la nav ; grille de durée en 3 colonnes ; CTA et champ date en pleine largeur. La réf. 10a montre le menu **en état déplié** (panneau sous la barre avec les liens Comment ça marche / Devenir contributeur / Contributeur ? Connexion) uniquement pour documenter son contenu — dans le produit réel c'est un état caché par défaut, à ouvrir/fermer au tap sur l'icône burger (qui se transforme généralement en croix quand ouvert).

### 02 — Comment ça marche
**Purpose** : explique les 6 étapes, compare parcours classique gratuit vs voyage 100% IA payant, réassurance spots vérifiés, FAQ.
**Layout** : liste numérotée des 6 étapes (cercle teal + titre + description, dernière étape taguée « Inclus ») → 2 cartes côte à côte (Parcours classique / Voyage 100% IA avec Vany, image alignée en haut à gauche d'une rangée titre) → bandeau réassurance contributeurs → grille FAQ 3 colonnes (1 colonne mobile) → CTA final centré.

### 03 — Ville
**Purpose** : étape 1/5 du parcours jour par jour — choisir la ville de départ.
**Layout** : header avec stepper 5 étapes (desktop : cercles horizontaux ; mobile : barre de progression 5 segments + texte « x/5 · Nom ») → champ recherche + bouton → carte interactive (placeholder) → carte ville sélectionnée (badges nb randos/spots/POI) → grille météo 4 jours (desktop) / 2×2 (mobile) avec icône, températures, vent, tag conseil.

### 04 — Randonnée
**Purpose** : étape 2/5 — choisir la randonnée du jour.
**Layout** : filtres segmentés (Difficulté, Durée) en pilules → carte des tracés (placeholder) → liste de fiches randonnée (titre, badge « Vérifié », description, tags distance/durée/dénivelé/difficulté, action Choisir/Sélectionnée) → lien « pas de rando aujourd'hui ».

### 05 — Spot
**Purpose** : étape 3/5 — choisir le spot pour la nuit.
**Layout** : filtre Prix (Tout/Gratuit/Payant) → carte (placeholder) → fiches spot (nom, type, tarif, distance, description, équipements en tags, note ★, actions Voir/Choisir).

### 06 — Services
**Purpose** : étape 4/5 — ajouter les services utiles (eau, vidange, commerces…) autour du spot.
**Layout** : chips de catégories (11 catégories) → carte (placeholder) → liste de services (nom, catégorie, distance, statut Ajouté/Ajouter).

### 07 — Récapitulatif
**Purpose** : étape 5/5 — vue d'ensemble du séjour, téléchargement du carnet PDF.
**Layout** : titre + résumé chiffré du séjour → cartes par jour (J1, J2… : randonnée / spot / services) en grille 2 colonnes (empilées en mobile) → carte itinéraire (placeholder) → bandeau « La cerise sur le gâteau » (recommandation Vany : image mascotte + titre + description + tags + CTA « Ajouter à mon carnet ») → CTA final sombre « Télécharger le carnet de voyage (PDF) ».

### 08 — Voyage 100% IA (chat)
**Purpose** : alternative payante — Vany compose l'itinéraire par conversation, validable étape par étape.
**Layout** : header avec avatar Vany + bascule « mode manuel » → fil de conversation (bulles utilisateur à droite blanches, bulles Vany à gauche menthe, avatar rond) → carte « proposition Jour N » encapsulée dans une bulle (randonnée / spot / services + actions Valider/Changer) → puces de réponse rapide alignées à droite → indicateur de saisie (3 points) → champ de saisie + bouton d'envoi rond, fixé en bas (hauteur de fenêtre fixe desktop 720px).

### 09 — Connexion contributeur
**Purpose** : authentification des contributeurs (partage de spots/randos).
**Layout** : header sombre simplifié (logo + retour) → formulaire (email, mot de passe masqué, case « se souvenir », mot de passe oublié, CTA plein) + carte menthe latérale « Contribuer, ça change quoi ? » (3 bénéfices + citation chiffrée). Empilé verticalement en mobile.

### 10 — Espace contributeur
**Purpose** : tableau de bord du contributeur connecté.
**Layout** : header avec badge « Espace contributeur » + avatar initiales → salutation + 2 CTA (ajouter spot/rando) → 3 cartes stats (spots partagés, randos décrites, nuits passées) → carte « contributions récentes » (liste statut En ligne/En relecture) + carte « ajouter un spot » (formulaire condensé) côte à côte (empilées en mobile) → bandeau menthe « Le mot de Vany » (citation + CTA « Voir ton impact »).

### 11 — Ajouter une randonnée
**Purpose** : formulaire de contribution d'une nouvelle randonnée.
**Layout** : « L'essentiel » (nom, ville de départ, distance/durée/dénivelé, difficulté et type de parcours en pilules sélectionnables) + « Tracé GPS » (dropzone .gpx, aperçu placeholder, encart consigne) côte à côte (empilés en mobile) → « Ton récit du parcours » (textarea, tags « sur le chemin », dropzone photos) → actions Envoyer en relecture / Enregistrer le brouillon.

### 12 — Accès à Vany (paiement / code)
**Purpose** : débloquer le chat 100% IA — soit paiement unique, soit code contributeur.
**Layout** : intro avec mascotte Vany centrée → 2 cartes côte à côte séparées par un « ou » (Paiement unique 4,90 €, avantages listés, CTA plein ; Code contributeur, champ code pré-rempli, CTA outline) → rappel que le parcours classique reste gratuit. Empilé verticalement en mobile (séparateur « ou » horizontal).

## Interactions & Behavior
- **Navigation du parcours** : stepper linéaire Ville → Randonnée → Spot → Services → Récapitulatif, avec bouton retour (icône ← circulaire 46px en mobile) et CTA d'action pleine largeur qui avance à l'étape suivante.
- **Sélection** : cartes cliquables (durée, ville, rando, spot, service) — état sélectionné = bordure/fond teal + coche ; état par défaut = bordure neutre.
- **Carte interactive** : toutes les zones « carte » sont des placeholders (fond hachuré + légende monospace) — à remplacer par une intégration cartographique réelle (tracés GPX, pins spots/services).
- **Météo** : données factices à remplacer par un appel API météo réel, avec le tag conseil (ex. "Pars de bonne heure", "Équipements conseillés") recalculé selon les conditions.
- **Chat Vany** : conversation avec bulles + « quick replies » cliquables qui envoient un message pré-rempli ; indicateur de saisie animé (3 points) pendant que Vany « réfléchit » ; carte de proposition éditable inline (boutons Changer la rando / Changer le spot re-déclenchent une suggestion).
- **Upload** : dropzone GPX (formulaire rando) et dropzone photos (spot, rando, profil) — drag & drop + clic pour parcourir.
- **Paiement** : CTA « Payer et discuter avec Vany » → à brancher sur un prestataire de paiement réel (CB, Apple Pay, Google Pay mentionnés) ; code contributeur → validation côté serveur.
- **Formulaires** : tags de sélection multiple (équipements, points d'intérêt) à état toggle ; validation avant passage en « relecture » (modération humaine sous 48h mentionnée dans les CTA).
- **Menu mobile** : le burger (3 traits) ouvre/ferme un panneau de nav sous le header (liens empilés, cible tactile ≥44px chacun) ; icône à basculer en croix (✕) quand ouvert ; fermeture au tap sur l'icône, sur un lien, ou en dehors du panneau.
- **Responsive** : bascule desktop (≥ ~1240px, stepper en cercles horizontaux dans le header) → mobile (390px, header compact + burger, stepper en barre de progression 5 segments + libellé, navigation basse fixe avec retour + CTA pleine largeur). Prévoir les breakpoints intermédiaires (tablette) en interpolant entre les deux gabarits fournis.

## State Management
- Durée du séjour sélectionnée + date de départ.
- Jour courant en cours d'édition (« Jour X / N ») et, pour chaque jour : ville, randonnée, spot, liste de services ajoutés.
- Session contributeur (connecté/déconnecté), profil (nom, initiales, stats).
- Historique de conversation du chat Vany + état de la proposition en cours (validée / en attente de changement) par jour.
- État des formulaires de contribution (spot / randonnée) : brouillon vs envoyé en relecture.
- Statut de déverrouillage du chat 100% IA (payé / code contributeur validé).

## Assets

### Logo (`assets/logo/`)
- `wordmark.png` — logo fourni tel quel par le client (référence 7a). Limites documentées dans la réf. design : fond blanc cassé intégré à l'image, teal peu contrasté, typo différente de celle du site.
- `hat.png` — chapeau détouré de Vany, source utilisée pour composer le lockup HTML/CSS (posé sur le « n » de « RandoVanGo ») et pour les favicons.
- `lockup-white-large.png` — proposition de lockup harmonisé (réf. 7b), grand format, sur blanc : « Rando » en encre `#22424B` + « VanGo » en teal `#2E7D86`, Archivo 800.
- `lockup-cream.png` — même lockup, sur fond crème `#F9F8F1` (fond réel du site).
- `lockup-dark.png` — variante claire du lockup pour fond sombre `#22424B` : texte `#F9F8F1` + accent `#7FC4CC`.
- `favicon-mint.png` / `favicon-teal.png` — chapeau seul sur carré arrondi (menthe `#E6F3F0` / teal `#2E7D86`), pour favicon / app icon / avatar Vany.

**Important** : `lockup-*.png` sont des **exports raster de rendu**, fournis pour prévisualisation rapide et usages ponctuels (réseaux sociaux, favicon, og:image). Le lockup est fondamentalement un **assemblage HTML/CSS** (texte en Archivo 800 + `hat.png` positionné en absolu sur le « n », voir bloc 7b dans `Directions artistiques.dc.html` du projet source) — **à réimplémenter en code** (texte réel + image du chapeau) dans le header du site plutôt qu'à utiliser comme image plate, pour rester net à toutes tailles et modifiable.

### Mascotte Vany (`assets/vany2/`)
Set complet des poses utilisées/disponibles pour la mascotte (variantes `-soft` = versions estompées utilisées en fond de bandeau) :
- `avatar.png` — avatar rond (chat).
- `front.png` / `front-soft.png` — Vany de face (bandeau « Voyage 100% IA »).
- `waiting.png` / `waiting-soft.png` — Vany qui recommande (bandeau « cerise sur le gâteau », récapitulatif).
- `celebrating.png` / `celebrating-soft.png` — Vany qui célèbre (bandeau « Le mot de Vany », espace contributeur).
- `showing.png` / `showing-soft.png` — Vany qui présente (page accès Vany).
- `pensive.png` — Vany pensif (disponible pour états d'attente/chargement).
- `profile.png`, `icon-front.png`, `icon-profile.png` — formats profil/icône.
- `ref.png` — planche de référence du personnage.
- `_check.png` — variante interne.

### Autres
- `frontend/static/images/van-life-liberte.jpg` — photo hero (accueil).
- `frontend/static/images/wheather/sun.png`, `cloud.png`, `rain.png` — icônes météo (étape Ville).

Tous les autres visuels (cartes, tracés) sont des placeholders intentionnels à remplacer par de vraies données/imagery.

## Files
- `Projet validé.dc.html` — **fichier de référence unique**, contient les 12 pages ci-dessus en desktop + mobile, dans l'ordre du site. S'ouvre directement dans un navigateur.
- `support.js` — requis à côté du fichier HTML pour son rendu (ne pas omettre lors de la copie).
