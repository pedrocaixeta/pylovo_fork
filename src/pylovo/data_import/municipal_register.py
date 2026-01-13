"""
Municipal register data import functions.
This module consolidates functions for importing and processing municipal register data
from Regiostar and Gemeindeverzeichnis datasets.
"""
import os
import pandas as pd
from pathlib import Path
from openpyxl import load_workbook
import pylovo.database.database_client as dbc
def _get_repo_root() -> Path:
    """Get the repository root directory."""
    # Start from this file and go up to find the repo root
    current = Path(__file__).parent
    while current != current.parent:
        if (current / "raw_data").exists():
            return current
        current = current.parent
    # Fallback to current working directory
    return Path.cwd()
def _get_data_file_path(relative_path: str) -> str:
    """Get path to municipal data file in raw_data directory."""
    repo_root = _get_repo_root()
    file_path = repo_root / "raw_data" / "municipal_register" / relative_path
    if not file_path.exists():
        raise FileNotFoundError(
            f"Municipal data file not found: {file_path}\n"
            f"Make sure you have cloned the full repository with data files in raw_data/municipal_register/\n"
            f"Run: git clone https://github.com/tum-ens/pylovo.git"
        )
    return str(file_path)
def import_regiostar() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Import RegioStaR dataset from excel datasheet.
    Regiostar: Regionalstatistische Raumtypologie des Bundesministeriums für Digitales und Verkehr (BMVI)
    classification of German Municipalities
    source: https://bmdv.bund.de/SharedDocs/DE/Artikel/G/regionalstatistische-raumtypologie.html
    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        - Full regiostar table with AGS, name, Regiostar 5 and 7 classes
        - Bavaria-only subset of the regiostar table
    """
    data_path = _get_data_file_path('regiostar/regiostar.xlsx')
    name_worksheet = "ReferenzGebietsstand2020"
    # load excel work book
    wb = load_workbook(data_path)
    # load excel sheet
    ws = wb[name_worksheet]
    # write excel regiostar table into dataframe
    data = ws.values
    columns = next(data)[0:]
    regiostar = pd.DataFrame(data, columns=columns)
    # columns to be dropped
    drop_columns = ["gemrs_20", "vbgem_20", "vbgemrs_20", "vbgnam_20", "RegioStaR2", "RegioStaR4", "RegioStaR17",
                    "RegioStaRGem7", "RegioStaRGem5", "RegioStaR_Stadtregion", "RegioStaR_NameStadtregion"]
    regiostar5_7 = regiostar.drop(drop_columns, axis=1)
    # The columns are municipal code (Gemeindeschlüssel), Name (Gemeindename), population, area, federal state (Bundesland)
    # and regio 5 and 7 code
    regiostar5_7.columns = ["mun_code", "name_city", "pop", "area", "fed_state", "regio7", "regio5"]
    # Calculating the population density
    regiostar5_7["pop_den"] = regiostar5_7["pop"] / regiostar5_7["area"]
    # selecting municipalities in Bayern
    regiostar5_7_bayern = regiostar5_7.loc[regiostar5_7['fed_state'] == 9]
    regiostar5_7_bayern = regiostar5_7_bayern.drop(["fed_state"], axis=1)
    return regiostar5_7, regiostar5_7_bayern
def import_plz_einwohner() -> pd.DataFrame:
    """
    Import table with PLZ, population, area, latitude and longitude.
    Source: https://www.suche-postleitzahl.org/downloads
    Returns
    -------
    pd.DataFrame
        Table with population data per postal code
    """
    data_path = _get_data_file_path('gemeindeverzeichnis/plz_einwohner.xls')
    plz_einwohner = pd.read_excel(data_path)
    return plz_einwohner
def import_zuordnung_plz() -> pd.DataFrame:
    """
    Import excel table with matching PLZ and AGS.
    Source: https://www.suche-postleitzahl.org/downloads
    Returns
    -------
    pd.DataFrame
        Table with PLZ and AGS data
    """
    data_path = _get_data_file_path('gemeindeverzeichnis/zuordnung_plz_ort.xls')
    plz_zuordnung = pd.read_excel(data_path)
    plz_zuordnung = plz_zuordnung.drop(columns=["osm_id"])
    return plz_zuordnung
def import_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Retrieve data from gemeindeverzeichnis and regiostar.
    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
        - plz_einwohner: Population data per postal code
        - plz_zuordnung: PLZ to AGS mapping
        - regiostar: Regiostar classification data
    """
    plz_zuordnung = import_zuordnung_plz()
    plz_einwohner = import_plz_einwohner()
    regiostar, regiostar_bayern = import_regiostar()
    return plz_einwohner, plz_zuordnung, regiostar
def join_regiostar_plz(plz_pop: pd.DataFrame, plz_ags: pd.DataFrame, regiostar: pd.DataFrame) -> pd.DataFrame:
    """
    Create table that contains regiostar classes for PLZ.
    Pop and area columns contain specific data for the PLZ.
    Parameters
    ----------
    plz_pop : pd.DataFrame
        Population data per postal code
    plz_ags : pd.DataFrame
        PLZ to AGS mapping
    regiostar : pd.DataFrame
        Regiostar classification data
    Returns
    -------
    pd.DataFrame
        Combined table with PLZ, AGS, and regiostar classifications
    """
    plz_pop_ags = plz_pop.merge(plz_ags, left_on="plz", right_on="plz")
    plz_pop_ags_regio = plz_pop_ags.merge(regiostar, left_on="ags", right_on="mun_code")
    plz_pop_ags_regio = plz_pop_ags_regio.drop(
        columns=["note", "ort", "landkreis", "bundesland", "mun_code", "pop", "area", "pop_den"])
    plz_pop_ags_regio = plz_pop_ags_regio.rename(columns={"population": "pop", "qkm": "area"})
    plz_pop_ags_regio["pop_den"] = plz_pop_ags_regio["pop"] / plz_pop_ags_regio["area"]
    return plz_pop_ags_regio
def municipal_register_to_db(regiostar_plz: pd.DataFrame) -> None:
    """
    Write municipal register to database.
    Parameters
    ----------
    regiostar_plz : pd.DataFrame
        Combined municipal register data
    """
    dbc_client = dbc.DatabaseClient()
    try:
        regiostar_plz.to_sql(
            'municipal_register', 
            con=dbc_client.sqla_engine, 
            if_exists='append', 
            index=False,
        )
    except Exception as e:
        print(e)
def create_municipal_register() -> None:
    """
    Join gemeindeverzeichnis with regiostar.
    Each PLZ is associated with an AGS and regiostar class.
    The data is written to the database table 'municipal_register'.
    """
    plz_einwohner, plz_zuordnung, regiostar = import_tables()
    plz_einwohner = plz_einwohner.rename(columns={"einwohner": "population"})
    regiostar_plz = join_regiostar_plz(plz_einwohner, plz_zuordnung, regiostar)
    municipal_register_to_db(regiostar_plz)
