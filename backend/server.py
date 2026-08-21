from __future__ import annotations

import argparse
import os
from pathlib import Path

from collector.database import Database
from collector.http_api import serve
from collector.service import CollectorService


ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.getenv("TAJIK_COLLECTOR_DATA", ROOT / "runtime")).resolve()
DATABASE_PATH = Path(
    os.getenv("TAJIK_COLLECTOR_DB", RUNTIME_DIR / "collector.db")
).resolve()
AUDIO_DIR = Path(os.getenv("TAJIK_COLLECTOR_AUDIO", RUNTIME_DIR / "audio")).resolve()
API_KEY = os.getenv("TAJIK_COLLECTOR_API_KEY", "tajik-stt-local")
PUBLIC_BASE_URL = os.getenv("TAJIK_COLLECTOR_PUBLIC_URL", "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local backend for Tajik STT Collector")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the local HTTP server")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)

    subparsers.add_parser("init", help="Create the local SQLite database")

    import_parser = subparsers.add_parser("import-texts", help="Import TXT or CSV texts")
    import_parser.add_argument("file")
    import_parser.add_argument("--source", default="")
    import_parser.add_argument("--approved", action="store_true")
    import_parser.add_argument("--voices", type=int, default=5)

    export_parser = subparsers.add_parser("export", help="Export approved WAV/TXT pairs")
    export_parser.add_argument("--output", default=str(ROOT / "exports" / "latest"))

    subparsers.add_parser("stats", help="Show collection statistics")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    service = CollectorService(Database(DATABASE_PATH), AUDIO_DIR)

    if args.command == "serve":
        serve(
            service=service,
            host=args.host,
            port=args.port,
            api_key=API_KEY,
            admin_file=ROOT / "admin.html",
            public_base_url=PUBLIC_BASE_URL,
        )
    elif args.command == "init":
        print(f"Database ready: {DATABASE_PATH}")
        print(f"Audio folder: {AUDIO_DIR}")
    elif args.command == "import-texts":
        result = service.import_file(
            args.file,
            source=args.source,
            approved=args.approved,
            required_recordings=args.voices,
        )
        print(result)
    elif args.command == "export":
        print(service.export_dataset(args.output))
    elif args.command == "stats":
        print(service.stats())


if __name__ == "__main__":
    main()
