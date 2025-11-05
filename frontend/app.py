
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
        api_url = f'{API_BASE}/api/step1/cities'
        headers = {}
        # Récupérer le token JWT depuis la session si l'utilisateur est connecté
        if 'user' in session and session['user'].get('token'):
            headers['Authorization'] = f"Bearer {session['user']['token']}"
        response = requests.get(api_url, headers=headers, timeout=5)
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

@app.route('/api/step2/hikes', methods=['GET'])
def proxy_get_hikes():
    """Proxy pour récupérer les randonnées avec authentification JWT depuis la session"""
    backend_url = f'{API_BASE}/api/step2/hikes'
    try:
        # Transférer les query params (city_id, distance_km)
        if request.query_string:
            backend_url += '?' + request.query_string.decode('utf-8')
        
        # Préparer les headers
        headers = {}
        
        # Récupérer le token JWT depuis la session Flask si l'utilisateur est connecté
        if 'user' in session and session['user'].get('token'):
            headers['Authorization'] = f"Bearer {session['user']['token']}"
        
        # Appeler FastAPI avec le token
        resp = requests.get(backend_url, headers=headers, timeout=10)
        
        # Retourner la réponse JSON
        return (resp.content, resp.status_code, resp.headers.items())
    except Exception as e:
        print(f"Erreur proxy /api/step2/hikes: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/step3')
def step3():
    """Étape 3 - Choix du spot nuit"""
    return render_template('pages/step3_spot.html')

@app.route('/api/step3/spots', methods=['GET'])
def proxy_get_spots():
    """Proxy pour récupérer les spots avec authentification JWT depuis la session"""
    backend_url = f'{API_BASE}/api/step3/spots'
    try:
        # Transférer les query params (city_id, hike_id)
        if request.query_string:
            backend_url += '?' + request.query_string.decode('utf-8')
        
        # Préparer les headers
        headers = {}
        
        # Récupérer le token JWT depuis la session Flask si l'utilisateur est connecté
        if 'user' in session and session['user'].get('token'):
            headers['Authorization'] = f"Bearer {session['user']['token']}"
        
        # Appeler FastAPI avec le token
        resp = requests.get(backend_url, headers=headers, timeout=10)
        
        # Retourner la réponse JSON
        return (resp.content, resp.status_code, resp.headers.items())
    except Exception as e:
        print(f"Erreur proxy /api/step3/spots: {e}")
        return jsonify({'error': str(e)}), 500

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
            'username': data.get('username'),
            'password': data.get('password')
        }, timeout=10)
        
        if resp.status_code == 200:
            # Récupérer le token JWT et les infos utilisateur
            response_data = resp.json()
            user_data = response_data.get('user', {})
            token = response_data.get('token')
            
            # Stocker les infos utilisateur dans la session Flask
            session['user'] = {
                'id': user_data.get('id'),
                'username': user_data.get('username'),
                'roles': user_data.get('roles', []),
                'token': token
            }
            
            return jsonify({
                'success': True,
                'token': token,
                'username': user_data.get('username'),
                'roles': user_data.get('roles', []),
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

@app.route('/delete_gpx/<filename>', methods=['DELETE'])
def delete_gpx(filename):
    """Delete GPX - proxy vers FastAPI avec authentification admin"""
    backend_url = f'{API_BASE}/api/etl/delete_gpx/{filename}'
    try:
        # Récupérer le token JWT depuis l'en-tête Authorization
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({
                'success': False,
                'message': 'Token d\'authentification manquant'
            }), 401
        
        # Préparer les headers pour la requête vers FastAPI
        headers = {'Authorization': auth_header}
        
        # Appeler l'API FastAPI etl/delete_gpx
        resp = requests.delete(backend_url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            response_data = resp.json()
            return jsonify({
                'success': True,
                'message': response_data.get('message', 'Suppression réussie'),
                'deleted_file': response_data.get('deleted_file')
            })
        elif resp.status_code == 403:
            return jsonify({
                'success': False,
                'message': 'Accès refusé : rôle admin requis'
            }), 403
        else:
            return jsonify({
                'success': False,
                'message': 'Erreur lors de la suppression'
            }), resp.status_code
    except Exception as e:
        print(f"Erreur lors de la suppression GPX: {e}")
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

# Route proxy générique pour toutes les autres routes API
@app.route('/api/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def proxy_api(path):
    """Proxy générique pour toutes les routes API vers FastAPI"""
    backend_url = f'{API_BASE}/api/{path}'
    try:
        # Transférer les query params
        if request.query_string:
            backend_url += '?' + request.query_string.decode('utf-8')
        
        # Transférer les headers (sauf Host)
        headers = {key: value for key, value in request.headers if key.lower() != 'host'}
        
        # Faire la requête vers FastAPI
        resp = requests.request(
            method=request.method,
            url=backend_url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=30
        )
        
        # Retourner la réponse
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = [(name, value) for name, value in resp.raw.headers.items() if name.lower() not in excluded_headers]
        
        return (resp.content, resp.status_code, response_headers)
    except Exception as e:
        print(f"Erreur proxy API {path}: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
