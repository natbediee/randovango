import math
import os
import re
import unicodedata
import gpxpy
from utils.geo_utils import get_city_from_coordinates, get_commune_at

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
# Nettoyage du nom d'une rando (issue #319).
# Une rando sans nom de trace prend le nom de son fichier, où le site de la fédération a remplacé chaque apostrophe
# et chaque espace par « _ », et le séparateur « : » par « ___ » :
# « FFRandonnée-L_Île-d_Yeu___Kreuzland.gpx » doit se lire « L'Île-d'Yeu : Kreuzland ».

# Les préfixes ajoutés devant le nom par une source : celui de la fédération, ou un numéro d'ordre (« 01- »).
# Seuls ceux-là sont retirés : un nom qui commence par « Saint-Pol » garde son tiret.
SOURCE_PREFIX = re.compile(r'^(FFRandonnée|\d+)-')

# Le séparateur entre le lieu et le titre : trois « _ », parfois entourés d'espaces.
SEPARATOR = re.compile(r'\s*___\s*')

# Une apostrophe effacée : un petit mot élidé (l, d, qu, presqu…) collé par « _ » au mot suivant (« d_Yeu »,
# « l_Abbé », « presqu_île »). Le petit mot doit être isolé : il commence le nom ou suit un séparateur (espace, « _ »,
# tiret, comme dans « Dolus-d_Oléron »), sinon « Rand_Abers » deviendrait « Ran'd Abers ».
# Le mot suivant n'a pas à commencer par une voyelle : les noms de lieux savoyards élident devant une consonne
# (« Praz_d_zeures » se lit « Praz d'zeures », rando 605). Il doit commencer par une lettre, pas par un chiffre.
ELIDED_WORD = re.compile(
	r"(?<![^\s_\-])(l|d|j|m|n|s|t|c|qu|jusqu|lorsqu|puisqu|quoiqu|presqu)_(?=[^\W\d_])",
	re.IGNORECASE,
)

# Le « c'h » breton : « Roc_h_ar_Bic », « Créac_h_Gwen », « C_hléguer » s'écrivent avec une apostrophe.
BRETON_CH = re.compile(r'(c)_(h)', re.IGNORECASE)


def remove_source_prefix(name):
	"""Retire le préfixe d'une source connue (« FFRandonnée- », « 01- ») ; tout autre tiret fait partie du nom."""
	return SOURCE_PREFIX.sub('', name, count=1)


def restore_apostrophes(name):
	"""Remet les apostrophes que le nom de fichier a remplacées par « _ » (« L_Île-d_Yeu » → « L'Île-d'Yeu »)."""
	name = ELIDED_WORD.sub(r"\1'", name)
	return BRETON_CH.sub(r"\1'\2", name)


def normalize_name(raw_name):
	"""Rend lisible le nom d'une rando tiré d'un nom de trace ou de fichier : préfixe, séparateur, apostrophes, espaces."""
	# Sur Mac, un nom de fichier peut écrire « é » en deux caractères (e + accent) : on le ramène à un seul,
	# sinon le préfixe « FFRandonnée- » et les voyelles accentuées ne seraient pas reconnus.
	name = unicodedata.normalize('NFC', raw_name)
	name = remove_source_prefix(name)
	name = SEPARATOR.sub(' : ', name)
	name = restore_apostrophes(name)
	# Les « _ » restants étaient des espaces ; on supprime ensuite les espaces en double.
	name = name.replace('_', ' ')
	return re.sub(r' +', ' ', name).strip()

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

	# Détection de la ville à la phase de transformation : la commune officielle qui contient le départ (geo.api.gouv.fr).
	# Nominatim donne le lieu le plus proche, parfois un lieu-dit (Trézien pour la pointe de Corsen, en Plouarzel) :
	# depuis l'issue #184, « Où pars-tu » ne propose plus que des communes, et un GPX parti d'un lieu-dit est rattaché à
	# la ville de sa commune. Nominatim ne sert plus que si l'État ne répond pas.
	# La réponse de l'État donne aussi le département et la région (commune_details) : le chargement les écrit dans la
	# ville si elle est nouvelle, sans redemander l'État (issue #328).
	city_name = commune = insee = commune_details = None
	if start_lat and start_lon:
		commune_details = get_commune_at(start_lat, start_lon)
		if commune_details:
			commune, insee = commune_details["name"], commune_details["insee"]
		city_name = commune or get_city_from_coordinates(start_lat, start_lon, language='fr')
	# Si la ville n'est pas trouvée, on arrête la transformation (aucun chargement)
	if not city_name:
		return None

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
		'city_name': city_name,
		'commune': commune,
		'insee': insee,
		'commune_details': commune_details
	}
