import re

import pandas as pd
from utils.logger_util import LoggerUtil

# Park4Night ne fournit pas un nom de lieu mais un gabarit constant :
#   "(29200) Brest - 172 Rue de Quimper"  -> code postal + commune + adresse
#   "(29790) Camping Lizoé"               -> code postal + vrai nom du lieu
# Affiché tel quel sur les cartes et le PDF, l'utilisateur lit une adresse là où
# il attend un lieu. On éclate donc le gabarit en colonnes exploitables.
SPOT_NAME_RE = re.compile(r"^\((?P<cp>\d{5})?\)\s*(?P<rest>.*)$")


def parse_spot_name(name) -> tuple:
    """
    (code_postal, commune, libellé de lieu) extraits du nom Park4Night.

    La commune n'est renseignée que pour la forme "Ville - Adresse" : sans
    tiret, ce qui suit le code postal est le nom du lieu (camping, aire), pas
    une commune - vérifié sur les 338 spots concernés, aucun ne porte un nom de
    commune. Chaque champ vaut None s'il est absent (4 spots ont un code postal
    vide et rien après le tiret).
    """
    if not name or not str(name).strip():
        return None, None, None
    match = SPOT_NAME_RE.match(str(name).strip())
    if not match:
        return None, None, str(name).strip()
    postal_code = match.group("cp")
    rest = match.group("rest").strip()
    # Adresse vide côté P4N : le nom s'arrête sur le séparateur ("() Poullaouen -").
    # Sans ce cas, la commune serait prise pour un libellé de lieu.
    if rest.endswith(" -"):
        return postal_code, rest[:-2].strip() or None, None
    if " - " in rest:
        city, place = rest.split(" - ", 1)
        return postal_code, city.strip() or None, place.strip() or None
    return postal_code, None, rest or None


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

    # Nom_Place → code postal / commune / libellé de lieu
    df[['postal_code', 'city_label', 'place_label']] = df['Nom_Place'].apply(
        lambda n: pd.Series(parse_spot_name(n), index=['postal_code', 'city_label', 'place_label'])
    )

    # Colonnes finales
    cols = ['URL_fiche', 'p4n_id', 'Nom_Place', 'latitude', 'longitude', 'Type_Place', 'note', 'Services', 'Description',
            'postal_code', 'city_label', 'place_label']
    df_out = df[cols].drop_duplicates(subset=['p4n_id']).reset_index(drop=True)
    for i, row in df_out.iterrows():
        logger.info(f"[transform] : Spot transformé - Nom: {row['Nom_Place']}, p4n_id: {row['p4n_id']}, lat: {row['latitude']}, lon: {row['longitude']}, type: {row['Type_Place']}")
    logger.info(f"[transform] : DataFrame transformé: shape={df_out.shape}, colonnes={df_out.columns.tolist()}")
    return df_out
