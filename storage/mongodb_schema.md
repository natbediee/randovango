# =============================================
# RANDOVANGO - SCHEMA MONGODB
# Collections pour données semi-structurées
# =============================================

# Collection: gpx_files
# Stockage des fichiers GPX complets
{
  "_id": ObjectId,
  "randonnee_id": 123,  # Référence SQL
  "nom_fichier": "FFRandonnée-Du_Minou_au_Mengant.gpx",
  "contenu_gpx": "<?xml version='1.0'...",  # Contenu XML complet
  "points_trace": [
    {
      "lat": 48.3422,
      "lon": -4.7231,
      "elevation": 45.2,
      "time": "2024-01-15T10:00:00Z"
    }
    # ... tous les points
  ],
  "statistiques": {
    "distance_totale": 12.5,
    "elevation_min": 0,
    "elevation_max": 156,
    "denivele_positif": 234,
    "denivele_negatif": 198,
    "duree_estimee_minutes": 180
  },
  "metadata": {
    "source": "FFRandonnée",
    "date_creation": "2024-01-15",
    "auteur": "FFRandonnée Finistère",
    "description": "Randonnée côtière..."
  },
  "created_at": new Date(),
  "updated_at": new Date()
}

# Collection: spots_donnees_detaillees
# Données complètes des spots (Park4Night, OSM, etc.)
{
  "_id": ObjectId,
  "spot_id": 456,  # Référence SQL
  "source": "park4night",
  "donnees_originales": {
    "URL_fiche": "https://park4night.com/fr/place/225996",
    "Note_Avis": "4.2/5",
    "Services": "Laverie, Dépannage en gaz",
    "Commentaires": [
      {
        "auteur": "VanLifer123",
        "date": "2024-01-10",
        "note": 4,
        "commentaire": "Très calme, proche des commerces"
      }
    ]
  },
  "services_detailles": [
    {
      "nom": "Eau potable",
      "disponible": true,
      "gratuit": true,
      "horaires": "24h/24"
    },
    {
      "nom": "Électricité",
      "disponible": true,
      "gratuit": false,
      "prix": "3€/nuit",
      "horaires": "8h-20h"
    }
  ],
  "photos": [
    {
      "url": "https://...",
      "description": "Vue générale",
      "auteur": "user123"
    }
  ],
  "restrictions": {
    "taille_max": "7m",
    "animaux": true,
    "generateur": false,
    "feu": false
  },
  "created_at": new Date(),
  "updated_at": new Date()
}

# Collection: services_osm_data
# Données OpenStreetMap complètes des services
{
  "_id": ObjectId,
  "service_id": 789,  # Référence SQL
  "osm_id": "node/123456789",
  "osm_data": {
    "amenity": "pharmacy",
    "name": "Pharmacie du Centre",
    "addr:housenumber": "15",
    "addr:street": "Rue de la Paix",
    "addr:city": "Plougonvelin",
    "phone": "+33 2 98 48 75 62",
    "opening_hours": "Mo-Sa 09:00-19:00",
    "wheelchair": "yes"
  },
  "horaires_structures": {
    "lundi": {"ouvert": true, "heures": "09:00-19:00"},
    "mardi": {"ouvert": true, "heures": "09:00-19:00"},
    "mercredi": {"ouvert": true, "heures": "09:00-19:00"},
    "jeudi": {"ouvert": true, "heures": "09:00-19:00"},
    "vendredi": {"ouvert": true, "heures": "09:00-19:00"},
    "samedi": {"ouvert": true, "heures": "09:00-19:00"},
    "dimanche": {"ouvert": false}
  },
  "created_at": new Date(),
  "updated_at": new Date()
}

# Collection: meteo_donnees_completes
# Données météo détaillées des APIs
{
  "_id": ObjectId,
  "ville_id": 1,  # Référence SQL
  "date_prevision": "2024-01-20",
  "source": "openweathermap",
  "donnees_api": {
    "current": {
      "temp": 12.5,
      "feels_like": 10.2,
      "humidity": 78,
      "uvi": 2.1,
      "wind_speed": 15.3,
      "wind_deg": 240,
      "weather": [
        {
          "main": "Clouds",
          "description": "nuageux",
          "icon": "04d"
        }
      ]
    },
    "hourly": [
      # Prévisions par heure...
    ]
  },
  "analyse_activites": {
    "randonnee_possible": true,
    "conditions_ideales": false,
    "recommandations": "Prévoir veste imperméable",
    "score_meteo": 7.2
  },
  "created_at": new Date(),
  "updated_at": new Date()
}

# Collection: wikidata_donnees
# Données touristiques et culturelles
{
  "_id": ObjectId,
  "ville_id": 1,  # Référence SQL
  "donnees_wikidata": {
    "monuments": [
      {
        "nom": "Fort de Bertheaume",
        "type": "monument historique",
        "coordonnees": [48.3456, -4.7890],
        "description": "Forteresse du XVIIe siècle...",
        "wikidata_id": "Q123456"
      }
    ],
    "sites_naturels": [
      {
        "nom": "Pointe de Corsen",
        "type": "site naturel",
        "coordonnees": [48.4123, -4.7956],
        "description": "Point le plus occidental..."
      }
    ]
  },
  "created_at": new Date(),
  "updated_at": new Date()
}

# Collection: plannings_complets
# Plannings utilisateur avec toutes les données
{
  "_id": ObjectId,
  "planning_id": 101,  # Référence SQL
  "utilisateur_id": 1,
  "details_complets": {
    "itineraire_optimise": {
      "jour_1": {
        "randonnee": {
          "nom": "Du Minou au Mengant",
          "trace_gpx": "...",
          "points_interet": [...]
        },
        "hebergement": {
          "nom": "Aire de Plougonvelin",
          "services_disponibles": [...]
        },
        "services_proximite": [...]
      }
    },
    "budget_estime": {
      "hebergement": 15.00,
      "carburant": 25.00,
      "alimentation": 35.00,
      "total": 75.00
    },
    "export_formats": {
      "pdf_genere": false,
      "gpx_export": "...",
      "ical_export": "..."
    }
  },
  "created_at": new Date(),
  "updated_at": new Date()
}

# Index MongoDB pour optimiser les requêtes
db.gpx_files.createIndex({"randonnee_id": 1})
db.spots_donnees_detaillees.createIndex({"spot_id": 1})
db.services_osm_data.createIndex({"service_id": 1})
db.meteo_donnees_completes.createIndex({"ville_id": 1, "date_prevision": 1})
db.plannings_complets.createIndex({"planning_id": 1, "utilisateur_id": 1})