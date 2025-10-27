from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd
import pandapower as pp

from .metrics_calculator import MetricsCalculator

FILENAME_RE = re.compile(r"^(?:(?P<netz>\w{3})__)?trafo_(?P<tid>\d+)\.json$")


def parse_ids_from_filename(name: str) -> Dict[str, Any]:
    """Extract netznummer and trafo_id from a subgrid filename.

    Expected patterns:
    - {netz}__trafo_{id}.json
    - trafo_{id}.json
    """
    m = FILENAME_RE.match(name)
    return {
        "netznummer": m.group("netz") if m else None,
        "trafo_id": m.group("tid") if m else None,
    }


def generate_metrics_csv(subgrids_dir: str | Path, output_csv: str | Path) -> pd.DataFrame:
    """Compute metrics for all pandapower subgrid JSONs in a folder and write a CSV.

    Columns include: file, netznummer, trafo_id, and all metrics returned by MetricsCalculator.
    """
    subgrids_dir = Path(subgrids_dir)
    output_csv = Path(output_csv)
    calc = MetricsCalculator()

    rows: List[Dict[str, Any]] = []
    files = sorted(subgrids_dir.glob("*.json"))
    for f in files:
        try:
            net = pp.from_json(str(f))
            params = calc.compute_parameters_with_fallback(net, estimate_simultaneous_load=True)
            meta = parse_ids_from_filename(f.name)
            rows.append({"file": f.name, **meta, **params})
        except Exception as e:
            meta = parse_ids_from_filename(f.name)
            rows.append({"file": f.name, **meta, "error": str(e)})

    df = pd.DataFrame(rows)
    df.to_csv(output_csv, index=False)
    return df


def main():
    parser = argparse.ArgumentParser(description="Compute metrics for LV subgrid JSONs and export to CSV")
    parser.add_argument("subgrids_dir", help="Directory containing subgrid JSON files")
    parser.add_argument("--out", dest="output_csv", default="subgrids_metrics.csv", help="Output CSV path")
    args = parser.parse_args()

    df = generate_metrics_csv(args.subgrids_dir, args.output_csv)
    print(f"Wrote {len(df)} rows to {args.output_csv}")


if __name__ == "__main__":
    main()

