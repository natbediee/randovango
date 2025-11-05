import pandas as pd
from utils.logger_util import LoggerUtil

def transform_p4n(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforme le DataFrame issu du scraping Park4Night selon les règles métier :
    - Extrait p4n_id depuis URL_fiche
    - Sépare Coordonnees en latitude/longitude
    - Nettoie Type_Place (après le tiret)
    - Nettoie note (avant /5)
    - Garde Nom_Place, services, description
    """
    logger = LoggerUtil.get_logger("etl_p4n")

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

    # Colonnes finales
    cols = ['URL_fiche', 'p4n_id', 'Nom_Place', 'latitude', 'longitude', 'Type_Place', 'note', 'Services', 'Description']
    df_out = df[cols].drop_duplicates(subset=['p4n_id']).reset_index(drop=True)
    for i, row in df_out.iterrows():
        logger.info(f"[transform] : Spot transformé - Nom: {row['Nom_Place']}, p4n_id: {row['p4n_id']}, lat: {row['latitude']}, lon: {row['longitude']}, type: {row['Type_Place']}")
    logger.info(f"[transform] : DataFrame transformé: shape={df_out.shape}, colonnes={df_out.columns.tolist()}")
    return df_out
