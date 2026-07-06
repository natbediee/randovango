import os
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for

load_dotenv()

app = Flask(__name__)

# Configuration
app.config['STATIC_FOLDER'] = 'static'
app.config['TEMPLATES_FOLDER'] = 'templates'

# URL de l'API FastAPI, telle que le NAVIGATEUR doit la joindre (distincte d'une éventuelle
# URL interne Docker) : injectée dans tous les templates via window.API_BASE (voir base.html).
PUBLIC_API_BASE_URL = os.getenv('PUBLIC_API_BASE_URL', 'http://localhost:8000')


@app.context_processor
def inject_public_api_base_url():
    return {'public_api_base_url': PUBLIC_API_BASE_URL}


@app.route('/')
def index():
    """Page d'accueil - Redirection vers le planificateur"""
    return redirect(url_for('duration'))

# ===== PLANIFICATEUR PRINCIPAL ====

@app.route('/duration')
def duration():
    """Étape 1 - Durée du séjour"""
    return render_template('pages/step_duration.html')

@app.route('/step1')
def step1():
    """Étape 1 - Choix de la ville"""
    return render_template('pages/step1_city.html')

@app.route('/step2')
def step2():
    """Étape 2 - Choix de la randonnée"""
    return render_template('pages/step2_hike.html')

@app.route('/step3')
def step3():
    """Étape 3 - Choix des spots/nuits"""
    return render_template('pages/step3_spot.html')

@app.route('/step4')
def step4():
    """Étape 4 - Services et POI"""
    return render_template('pages/step4_services.html')

@app.route('/results')
def results():
    """Résultat final du planning"""
    return render_template('pages/results.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
