"""Launch the local MSF Costing Tool."""

from __future__ import annotations

import argparse
from pathlib import Path

from msf_costing.server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local MSF Costing Tool")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--database",
        type=Path,
        help="Optional SQLite database path (defaults to data/msf_costing.db)",
    )
    parser.add_argument(
        "--rates",
        type=Path,
        help="Optional rate library path (defaults to data/rates.json)",
    )
    args = parser.parse_args()
    serve(
        args.host,
        args.port,
        not args.no_browser,
        database_path=args.database,
        rates_path=args.rates,
    )


if __name__ == "__main__":
    main()
