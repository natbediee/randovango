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

# Front unique : identité Vany, templates sous templates/v2/ et assets sous static/v2/.
def page(name):
    """Rend le template d'une page du front v2 ('v2/pages/<name>.html')."""
    return render_template(f'v2/pages/{name}.html')


@app.context_processor
def inject_public_api_base_url():
    return {
        'public_api_base_url': PUBLIC_API_BASE_URL,
    }


@app.route('/')
def index():
    """Page d'accueil - Redirection vers le planificateur"""
    return redirect(url_for('duration'))

# ===== PLANIFICATEUR PRINCIPAL ====

@app.route('/duration')
def duration():
    """Étape 1 - Durée du séjour"""
    return page('step_duration')

@app.route('/step1')
def step1():
    """Étape 1 - Choix de la ville"""
    return page('step1_city')

@app.route('/step2')
def step2():
    """Étape 2 - Choix de la randonnée"""
    return page('step2_hike')

@app.route('/step3')
def step3():
    """Étape 3 - Choix des spots/nuits"""
    return page('step3_spot')

@app.route('/step4')
def step4():
    """Étape 4 - Services et POI"""
    return page('step4_services')

@app.route('/results')
def results():
    """Résultat final du planning"""
    return page('results')


# ===== PAGES ANNEXES =====

@app.route('/how-it-works')
def how_it_works():
    """Comment ça marche - présentation des 6 étapes, FAQ"""
    return page('how_it_works')

@app.route('/chat')
def chat():
    """Voyage 100% IA - conversation avec Vany"""
    return page('chat')

@app.route('/contributor/login')
def contributor_login():
    """Connexion contributeur"""
    return page('contrib_login')

@app.route('/contributor')
def contributor_dashboard():
    """Espace contributeur - tableau de bord"""
    return page('contrib_dashboard')

@app.route('/contributor/add-hike')
def contributor_add_hike():
    """Ajout d'une randonnée par un contributeur"""
    return page('add_hike')

@app.route('/unlock-vany')
def unlock_vany():
    """Accès à Vany - paiement unique ou code contributeur"""
    return page('unlock_vany')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
