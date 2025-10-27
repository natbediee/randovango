# RandoVango

Application de planification de randonnées en Bretagne avec recherche de spots, météo et points d'intérêt.

## Architecture

- **Backend** : FastAPI (API REST, ETL, scraping)
- **Frontend** : Flask (interface utilisateur)
- **Bases de données** :
  - MySQL : données structurées (villes, randonnées, spots)
  - MongoDB : données GPX, météo, POI

## Prérequis

### Environnement Docker (recommandé)

- Docker
- Docker Compose

Toutes les dépendances (Python, Chromium, MySQL, MongoDB) sont gérées automatiquement dans les conteneurs.

### Environnement local (développement)

#### Python et dépendances
```bash
python 3.12+
pip install -r requirements.txt
```

#### Chromium et chromedriver (pour le scraping P4N)

**Sur Debian/Ubuntu :**
```bash
sudo apt-get update
sudo apt-get install -y chromium chromium-driver
```

**Sur macOS (avec Homebrew) :**
```bash
brew install chromium
brew install chromedriver
```

**Sur Windows :**
- Télécharge [Chromium](https://www.chromium.org/getting-involved/download-chromium/) ou [Google Chrome](https://www.google.com/chrome/)
- Télécharge [chromedriver](https://chromedriver.chromium.org/downloads) compatible avec ta version de Chrome/Chromium
- Ajoute le chemin de `chromedriver.exe` à ton PATH système

**Configuration du script Python (`backend/etl/extract/scraper_p4n.py`) :**
Adapte les chemins selon ton installation locale :
```python
CHROME_BINARY_PATH = '/usr/bin/chromium'  # Ou '/usr/bin/google-chrome'
CHROMEDRIVER_PATH = '/usr/bin/chromedriver'
```

#### Bases de données
- MySQL 8.0+
- MongoDB 6.0+

## Installation et lancement

### Avec Docker (recommandé)

1. **Clone le projet**
```bash
git clone <repo-url>
cd randovango
```

2. **Configure les variables d'environnement**
Copie et adapte le fichier `.env` :
```bash
cp .env.example .env
# Édite .env avec tes paramètres
```

3. **Lance les services**
```bash
docker compose up -d
```

4. **Initialise les bases de données**
```bash
# MySQL
docker compose exec backend python3 -m db_init.db_randovango

# Importe les données GPX archivées dans MongoDB
docker compose exec backend python3 -m utils.migrate_gpx_to_mongo
```

5. **Lance l'ETL pour une ville**
```bash
docker compose exec backend python3 -m etl.etl_pipeline
```

### En local

1. **Installe les dépendances**
```bash
python -m venv .venv
source .venv/bin/activate  # Sur Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure `.env`** avec les informations de connexion MySQL et MongoDB locales

3. **Lance le backend FastAPI**
```bash
cd backend
uvicorn main:app --reload
```

4. **Lance le frontend Flask**
```bash
cd frontend
python app.py
```

## Utilisation

### Backend API (FastAPI)
- URL : `http://localhost:8000`
- Documentation interactive : `http://localhost:8000/docs`

### Frontend (Flask)
- URL : `http://localhost:5000`

### Adminer (interface MySQL)
- URL : `http://localhost:8080`
- Serveur : `db_randovango`
- Utilisateur : `randovango_user` (voir `.env`)

## Structure du projet

```
randovango/
├── backend/
│   ├── api/              # Routers FastAPI
│   ├── etl/              # Extract, Transform, Load
│   │   ├── extract/      # Scrapers et API externes
│   │   ├── transform/    # Transformation des données
│   │   └── load/         # Chargement en base
│   ├── db_init/          # Scripts d'initialisation DB
│   ├── utils/            # Utilitaires (logger, DB, geo)
│   └── main.py           # Point d'entrée FastAPI
├── frontend/
│   ├── static/           # CSS, JS, images
│   ├── templates/        # Templates Jinja2
│   └── app.py            # Point d'entrée Flask
├── data/
│   ├── in/               # Données d'entrée (GPX, JSON, CSV)
│   └── archive/          # Données archivées
├── storage/
│   ├── mysql/            # Volumes persistants MySQL
│   └── mongodb/          # Volumes persistants MongoDB
├── logs/                 # Logs applicatifs
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.frontend
├── requirements.txt
└── .env
```

## ETL Pipeline

Le pipeline ETL extrait, transforme et charge les données depuis plusieurs sources :

- **Météo** : API Open-Meteo
- **Points d'intérêt (POI)** : OpenStreetMap (Overpass API), Wikidata
- **Spots camping-car** : Park4Night (scraping Selenium)
- **Traces GPX** : Fichiers GPX locaux

### Lancement manuel d'un ETL

```bash
# ETL complet pour une ville
docker compose exec backend python3 -m etl.etl_pipeline

# ETL météo uniquement
docker compose exec backend python3 -m etl.extract.api_meteo

# Scraping P4N pour une ville
docker compose exec backend python3 -m etl.extract.scraper_p4n "Brest"
```

## Développement

### Logs
Les logs sont générés dans le dossier `logs/` et affichés dans la console.

### Tests
```bash
# À venir
pytest
```

### Migrations base de données
Les schémas MySQL et MongoDB sont versionnés dans `storage/database_schema.sql` et `storage/mongodb_schema.md`.

## Auteurs

Équipe RandoVango

## Licence

MIT
