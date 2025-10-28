
import requests
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

app = Flask(__name__)
app.secret_key = 'randovango-secret-key-change-in-production'
API_BASE = 'http://fastapi_backend:8000'

# Route GET pour afficher la page de login contributeur
@app.route('/login', methods=['GET'])
def login():
    return render_template('pages/login.html')

# Configuration
app.config['STATIC_FOLDER'] = 'static'
app.config['TEMPLATES_FOLDER'] = 'templates'

@app.route('/')
def index():
    """Page d'accueil - Redirection vers le planificateur"""
    return redirect(url_for('step1'))

# ===== PLANIFICATEUR PRINCIPAL ====

@app.route('/step1')
def step1():
    """Étape 1 - Choix de la ville"""
    # Appel à l'API FastAPI pour récupérer la liste des villes
    try:
        api_url = f'{API_BASE}/api/step1/cities?user_role=admin'
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        cities = response.json()
    except Exception as e:
        cities = []
        print(f"Erreur lors de l'appel à l'API FastAPI: {e}")
    return render_template('pages/step1_city.html', cities=cities)

# Proxy route pour relayer le POST vers le backend FastAPI
@app.route('/api/step1/create_plan', methods=['POST'])
def proxy_create_plan():
    backend_url = f'{API_BASE}/api/step1/create_plan'
    try:
        resp = requests.post(backend_url, json=request.get_json(), timeout=10)
        return (resp.content, resp.status_code, resp.headers.items())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/step2')
def step2():
    """Étape 2 - Choix de la randonnée"""
    return render_template('pages/step2_hike.html')

@app.route('/step3')
def step3():
    """Étape 3 - Choix de la nuit"""
    return render_template('pages/step3_spot.html')

@app.route('/step4')
def step4():
    """Étape 4 - Services et POI"""
    return render_template('pages/step4_services.html')

@app.route('/results')
def results():
    """Résultat final du planning"""
    return render_template('pages/results.html')

@app.route('/api/login', methods=['POST'])
def login_api():
    """Proxy login utilisateur vers FastAPI"""
    backend_url = f'{API_BASE}/api/login'
    try:
        resp = requests.post(backend_url, json=request.get_json(), timeout=10)
        return (resp.content, resp.status_code, resp.headers.items())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logout', methods=['POST'])
def logout():
    """Déconnexion"""
    session.pop('user', None)
    return jsonify({'status': 'success', 'message': 'Déconnexion réussie'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
