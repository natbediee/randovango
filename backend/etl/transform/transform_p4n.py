import pandas as pd
from backend.utils.logger_util import LoggerUtil

def transform_p4n(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforme le DataFrame issu du scraping Park4Night selon les règles métier :
    - Extrait p4n_id depuis URL_fiche
    - Sépare Coordonnees en latitude/longitude
    - Nettoie Type_Place (après le tiret)
    - Nettoie note (avant /5)
    - Garde Nom_Place, services, description
    - Supprime les doublons sur p4n_id
    """
    logger = LoggerUtil.get_logger("transform_p4n")

    # p4n_id
    df['p4n_id'] = df['URL_fiche'].str.extract(r'/place/(\d+)')

    # Coordonnees → latitude, longitude
    def split_coords(coord):
        try:
            lat, lon = coord.split(',')
            return float(lat.strip()), float(lon.strip())
        except Exception:
            return None, None
    df[['latitude', 'longitude']] = df['Coordonnees'].apply(lambda x: pd.Series(split_coords(x)))

    # Type_Place : après le tiret
    df['Type_Place'] = df['Type_Place'].astype(str).str.split('-', n=1).str[-1].str.strip()

    # note : avant /5 (gère l'ancien nom de colonne)
    if 'note' not in df.columns and 'Note_Avis' in df.columns:
        df['note'] = df['Note_Avis']
    df['note'] = df['note'].astype(str).str.extract(r'([\d\.,]+)(?=/5)')[0]

    # Colonnes finales (URL conservée en première colonne, city à la fin)
    if 'city' in df.columns:
        cols = ['URL_fiche', 'p4n_id', 'Nom_Place', 'latitude', 'longitude', 'Type_Place', 'note', 'Services', 'Description', 'city']
    else:
        cols = ['URL_fiche', 'p4n_id', 'Nom_Place', 'latitude', 'longitude', 'Type_Place', 'note', 'Services', 'Description']
    df_out = df[cols].drop_duplicates(subset=['p4n_id']).reset_index(drop=True)
    logger.info(f"DataFrame transformé: shape={df_out.shape}, colonnes={df_out.columns.tolist()}")
    return df_out

# Exemple d'utilisation
if __name__ == "__main__":
    import sys
    import os
    if len(sys.argv) < 2:
        print("Usage: python3 transform_p4n.py <csv_path>")
        sys.exit(1)
    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"Fichier introuvable: {csv_path}")
        sys.exit(1)
    df = pd.read_csv(csv_path, sep=';', encoding='utf-8')
    df_transformed = transform_p4n(df)
    out_path = csv_path.replace('.csv', '_transformed.csv')
    df_transformed.to_csv(out_path, sep=';', index=False, encoding='utf-8')
    print(f"Fichier transformé sauvegardé: {out_path}")
