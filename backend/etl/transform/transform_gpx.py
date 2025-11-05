import math
import os
import re
import gpxpy
from utils.geo_utils import get_city_from_coordinates

def extract_points(gpx):
	"""Extrait la liste des points (lat, lon, ele) de toutes les traces du GPX."""
	return [
		{'lat': pt.latitude, 'lon': pt.longitude, 'ele': pt.elevation}
		for track in gpx.tracks for segment in track.segments for pt in segment.points
	]

def extract_waypoints(gpx):
	"""Extrait la liste des waypoints (nom, lat, lon, ele, desc) du GPX."""
	return [
		{'name': wpt.name, 'lat': wpt.latitude, 'lon': wpt.longitude, 'ele': wpt.elevation, 'desc': wpt.description}
		for wpt in gpx.waypoints
	]
def normalize_name(raw_name):
    # Prendre la partie après le premier tiret
    if '-' in raw_name:
        name = raw_name.split('-', 1)[1]
    else:
        name = raw_name

    # Remplacer les cas particuliers d'apostrophe
    name = re.sub(r'_d_', " d'", name)
    name = re.sub(r'_l_', " l'", name)
    name = re.sub(r'_qu_', " qu'", name)
    name = re.sub(r'_s_', " s'", name)
    name = re.sub(r'_t_', " t'", name)
    name = re.sub(r'_n_', " n'", name)
    # Remplacer les autres _ par des espaces
    name = name.replace('_', ' ')
    # Supprimer les espaces en double
    name = re.sub(r' +', ' ', name)
    return name

def transform_gpx(gpx_content, fname) -> dict:
	"""
	Prend le contenu brut d'un fichier GPX (texte ou file-like), parse et transforme en dict normalisé.
	"""
	if hasattr(gpx_content, 'read'):
		gpx = gpxpy.parse(gpx_content)
	else:
		gpx = gpxpy.parse(str(gpx_content))

	# Points et waypoints (via fonctions dédiées)
	points = extract_points(gpx)
	waypoints = extract_waypoints(gpx)
	distance_km = 0
	denivele_m = 0
	start_lat = points[0]['lat'] if points else None
	start_lon = points[0]['lon'] if points else None
	description = None
	# Extraire la description du GPX
	if gpx.description:
		description = gpx.description
	elif gpx.tracks and gpx.tracks[0].description:
		description = gpx.tracks[0].description

	# Détection de la ville à la phase de transformation
	city_name = None
	if start_lat and start_lon:
		city_name = get_city_from_coordinates(start_lat, start_lon, language='fr')
	# Si la ville n'est pas trouvée, on arrête la transformation (aucun chargement)
	if not city_name:
		return None

	for waypoint in gpx.waypoints:
		waypoints.append({
			'name': waypoint.name,
			'lat': waypoint.latitude,
			'lon': waypoint.longitude,
			'ele': waypoint.elevation,
			'desc': waypoint.description
		})
	if gpx.tracks:
		# Calcul de la distance totale en 3D (prend en compte l'altitude)
		total_distance = 0
		for track in gpx.tracks:
			track_distance = track.length_3d()
			if track_distance:
				total_distance += track_distance
		# Conversion en kilomètres
		distance_km = total_distance / 1000 if total_distance else 0

		# Calcul du dénivelé positif (somme des montées)
		total_uphill = 0
		total_downhill = 0
		for track in gpx.tracks:
			for segment in track.segments:
				previous_elevation = None
				for point in segment.points:
					if point.elevation is not None:
						if previous_elevation is not None:
							elevation_diff = point.elevation - previous_elevation
							if elevation_diff > 0:
								total_uphill += elevation_diff  # On additionne uniquement les montées
							else:
								total_downhill += abs(elevation_diff)  # On additionne les descentes (optionnel)
						previous_elevation = point.elevation
		denivele_m = total_uphill
		# Arrondir la distance au km supérieur, arrondir le dénivelé à l'entier
		distance_km_rounded = math.ceil(distance_km)
		denivele_m_rounded = round(denivele_m)

		# Règle de Naismith :
		# - 1h de marche pour chaque 4 km à plat
		# - 1h de marche pour chaque 600 m de dénivelé positif
		time_distance_h = distance_km / 4
		time_elevation_h = denivele_m / 600  # 600m de montée = 1h supplémentaire
		estimated_duration_h = round(time_distance_h + time_elevation_h)
	else:
		# Si pas de trace, valeurs nulles
		distance_km_rounded = 0
		denivele_m_rounded = 0
		estimated_duration_h = 0
		total_downhill = 0
	if gpx.tracks and gpx.tracks[0].name:
		hike_name = gpx.tracks[0].name
	else:
		hike_name = os.path.splitext(fname)[0]
	# Normalisation du nom de la randonnée
	hike_name = normalize_name(hike_name)
	author = gpx.author_name if hasattr(gpx, 'author_name') and gpx.author_name else 'inconnue'

	# Calcul de la difficulté
	if distance_km_rounded < 8 and denivele_m_rounded < 200:
		difficulte = "facile"
	elif distance_km_rounded < 15 or denivele_m_rounded < 500:
		difficulte = "moyen"
	else:
		difficulte = "difficile"

	return {
		'name': hike_name,
		'distance_km': distance_km_rounded,
		'denivele_m': denivele_m_rounded,
		'estimated_duration_h': estimated_duration_h,
		'difficulte': difficulte,
		'points': points,
		'waypoints': waypoints,
		'author': author,
		'start_lat': start_lat,
		'start_lon': start_lon,
		'description': description,
		'city_name': city_name
	}
