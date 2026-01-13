"""Region resolver (PLZ / AGS -> PLZ list + municipal register slice).

This module intentionally stays lightweight:
- no dependencies on `src.classification`
- assumes callers provide correct integer inputs (PLZ/AGS as int or list[int])
- no leading zeros in PLZ (as per project assumptions)

The single public function `resolve_regions()` is used by:
- `runme/main_generation.py` to turn AGS execution modes into PLZ lists
- `src/data_import/import_buildings.py` to determine which building shapefiles to import

The municipal register is fetched via `dbc_client.get_municipal_register()`.
"""

from __future__ import annotations
from typing import Any
import pandas as pd


def resolve_regions(
    dbc_client: Any,
    *,
    plz: int | list[int] | None = None,
    ags: int | list[int] | None = None,
) -> tuple[list[int], pd.DataFrame]:
    """Resolve regional inputs (PLZ or AGS) against the municipal register.

    Contract
    --------
    Inputs:
      - Exactly one of `plz` or `ags` must be provided.
      - Values are expected to be `int` or `list[int]`.

    Output:
      - `plz_list`: sorted unique PLZ codes to process
      - `df_plz_ags`: a DataFrame slice of `municipal_register` containing the matching rows

    Why return both?
      - `plz_list` is needed for "generation" (GridGenerator runs per PLZ)
      - `df_plz_ags` is needed for "imports" (maps PLZ<->AGS to pick shapefiles)

    Raises:
      - ValueError: invalid inputs or missing codes in the municipal register
      - TypeError: if the database layer returns an unexpected type
    """

    # Step 1: Normalize to list[int]
    plz_list_in: list[int] | None
    ags_list_in: list[int] | None

    if plz is None:
        plz_list_in = None
    elif isinstance(plz, list):
        plz_list_in = plz
    else:
        plz_list_in = [plz]

    if ags is None:
        ags_list_in = None
    elif isinstance(ags, list):
        ags_list_in = ags
    else:
        ags_list_in = [ags]

    # Step 2: Fetch the municipal register
    mr = dbc_client.get_municipal_register()
    if not isinstance(mr, pd.DataFrame):
        raise TypeError("dbc_client.get_municipal_register() must return a pandas DataFrame")

    # Step 3: Filter by the chosen regional input and verify all codes exist
    if plz_list_in is not None:
        df_plz_ags = mr[mr["plz"].isin(plz_list_in)].copy()

        present_plz = set(df_plz_ags["plz"].tolist())
        missing_plz = sorted(set(plz_list_in).difference(present_plz))
        if missing_plz:
            raise ValueError(f"PLZ not found in municipal_register: {missing_plz}")

    else:
        # ags_list_in must be provided here due to Step 1
        assert ags_list_in is not None

        df_plz_ags = mr[mr["ags"].isin(ags_list_in)].copy()

        present_ags = set(df_plz_ags["ags"].tolist())
        missing_ags = sorted(set(ags_list_in).difference(present_ags))
        if missing_ags:
            raise ValueError(f"AGS not found in municipal_register: {missing_ags}")

    # Step 4: Derive the PLZ list for generation (unique, sorted)
    plz_list_out = sorted(set(df_plz_ags["plz"].tolist()))

    return plz_list_out, df_plz_ags
