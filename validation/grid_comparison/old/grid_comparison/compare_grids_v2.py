import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.grid_comparison.compare_grids import main, process_real_grids, process_synthetic_grids


if __name__ == "__main__":
    main()
