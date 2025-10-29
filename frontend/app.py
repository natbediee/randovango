
import requests
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

app = Flask(__name__)
app.secret_key = 'randovango-secret-key-change-in-production'
API_BASE = 'http://fastapi_backend:8000'

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

# Proxy route pour récupérer les villes avec rafraîchissement
@app.route('/api/step1/cities', methods=['GET'])
def proxy_get_cities():
    user_role = request.args.get('user_role', 'user')
    backend_url = f'{API_BASE}/api/step1/cities?user_role={user_role}'
    try:
        resp = requests.get(backend_url, timeout=10)
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
    return render_template('pages/step3_night.html')

@app.route('/step4')
def step4():
    """Étape 4 - Services et POI"""
    return render_template('pages/step4_services.html')

@app.route('/results')
def results():
    """Résultat final du planning"""
    return render_template('pages/results.html')

@app.route('/login', methods=['POST'])
def login_post():
    """Authentification utilisateur - proxy vers FastAPI"""
    backend_url = f'{API_BASE}/api/auth/login'
    try:
        # Récupérer les données du formulaire (username, password)
        data = request.get_json()
        
        # Appeler l'API FastAPI auth/login
        resp = requests.post(backend_url, json={
            'login': data.get('username'),
            'password': data.get('password')
        }, timeout=10)
        
        if resp.status_code == 200:
            # Récupérer le token JWT et les infos utilisateur
            response_data = resp.json()
            return jsonify({
                'success': True,
                'token': response_data.get('token'),  # FastAPI renvoie 'token', pas 'access_token'
                'username': data.get('username'),
                'message': 'Connexion réussie'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Identifiants incorrects'
            }), 401
    except Exception as e:
        print(f"Erreur lors de l'authentification: {e}")
        return jsonify({
            'success': False,
            'message': 'Erreur serveur'
        }), 500

@app.route('/upload_gpx', methods=['POST'])
def upload_gpx():
    """Upload GPX - proxy vers FastAPI avec authentification"""
    backend_url = f'{API_BASE}/api/etl/upload_gpx'
    try:
        # Récupérer le token JWT depuis l'en-tête Authorization
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({
                'success': False,
                'message': 'Token d\'authentification manquant'
            }), 401
        
        # Récupérer le fichier GPX
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'Aucun fichier fourni'
            }), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({
                'success': False,
                'message': 'Nom de fichier vide'
            }), 400
        
        # Préparer les fichiers et headers pour la requête vers FastAPI
        files = {'file': (file.filename, file.stream, file.content_type)}
        headers = {'Authorization': auth_header}
        
        # Appeler l'API FastAPI etl/upload_gpx
        resp = requests.post(backend_url, files=files, headers=headers, timeout=60)
        
        if resp.status_code == 200:
            response_data = resp.json()
            return jsonify({
                'success': True,
                'message': response_data.get('message', 'Upload réussi'),
                'ville': response_data.get('ville')
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Erreur lors de l\'upload'
            }), resp.status_code
    except Exception as e:
        print(f"Erreur lors de l'upload GPX: {e}")
        return jsonify({
            'success': False,
            'message': 'Erreur serveur'
        }), 500

@app.route('/logout', methods=['POST', 'GET'])
def logout():
    """Déconnexion - nettoyage session"""
    session.clear()
    return jsonify({
        'success': True,
        'message': 'Déconnexion réussie'
    })

# Route GET pour afficher la page de login contributeur (ancienne route)
@app.route('/login_page', methods=['GET'])
def login_page():
    return render_template('pages/login.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
