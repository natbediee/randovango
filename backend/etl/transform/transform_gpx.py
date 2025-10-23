import gpxpy
import json
import os

# Dossier source GPX
GPX_SRC = '../../in/gpx/'
# Dossier archive GPX
GPX_ARCHIVE = '../../archive/gpx/'
# Dossier output pour les données transformées
OUTPUT = '../../in/gpx_transformed/'

os.makedirs(OUTPUT, exist_ok=True)
os.makedirs(GPX_ARCHIVE, exist_ok=True)

def extract_gpx_metadata(gpx_file):
    with open(gpx_file, 'r') as f:
        gpx = gpxpy.parse(f)
    points = [
        {'lat': pt.latitude, 'lon': pt.longitude, 'ele': pt.elevation}
        for track in gpx.tracks for segment in track.segments for pt in segment.points
    ]
    waypoints = [
        {'name': wpt.name, 'lat': wpt.latitude, 'lon': wpt.longitude, 'ele': wpt.elevation, 'desc': wpt.description}
        for wpt in gpx.waypoints
    ]
    # Extraction de la source (auteur)
    source = None
    if hasattr(gpx, 'author') and gpx.author and hasattr(gpx.author, 'name'):
        source = gpx.author.name
    meta = {
        'name': gpx.tracks[0].name if gpx.tracks and gpx.tracks[0].name else os.path.basename(gpx_file),
        'distance_km': sum(track.length_2d() for track in gpx.tracks) / 1000 if gpx.tracks else None,
        'denivele_m': sum(track.get_uphill_downhill()[0] for track in gpx.tracks) if gpx.tracks else None,
        'points': points,
        'waypoints': waypoints,
        'source': source
    }
    return meta

def transform_all_gpx():
    for fname in os.listdir(GPX_SRC):
        if fname.endswith('.gpx'):
            src_path = os.path.join(GPX_SRC, fname)
            meta = extract_gpx_metadata(src_path)
            out_path = os.path.join(OUTPUT, fname.replace('.gpx', '.json'))
            with open(out_path, 'w') as out:
                json.dump(meta, out, indent=2)
            # Déplacement en archive
            archive_path = os.path.join(GPX_ARCHIVE, fname)
            os.rename(src_path, archive_path)
            print(f'Transformé et archivé: {fname}')

if __name__ == '__main__':
    transform_all_gpx()
