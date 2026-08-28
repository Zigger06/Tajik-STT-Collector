from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

from collector.database import Database
from collector.http_api import serve, serve_online
from collector.storage_aware_service import StorageAwareCollectorService


ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.getenv("TAJIK_COLLECTOR_DATA", ROOT / "runtime")).resolve()
DATABASE_PATH = Path(
    os.getenv("TAJIK_COLLECTOR_DB", RUNTIME_DIR / "collector.db")
).resolve()
AUDIO_DIR = Path(os.getenv("TAJIK_COLLECTOR_AUDIO", RUNTIME_DIR / "audio")).resolve()
API_KEY = os.getenv("TAJIK_COLLECTOR_API_KEY", "tajik-stt-local")
PUBLIC_BASE_URL = os.getenv("TAJIK_COLLECTOR_PUBLIC_URL", "")
ONLINE_CONFIG_PATH = RUNTIME_DIR / "online_config.json"


def load_or_create_online_config() -> dict[str, str]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if ONLINE_CONFIG_PATH.exists():
        config = json.loads(ONLINE_CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        config = {
            "admin_key": secrets.token_urlsafe(32),
        }
        ONLINE_CONFIG_PATH.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if not config.get("admin_key"):
        config["admin_key"] = secrets.token_urlsafe(32)
        ONLINE_CONFIG_PATH.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local backend for Tajik STT Collector")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the local HTTP server")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)

    online_parser = subparsers.add_parser(
        "online", help="Start a public API target and a computer-only admin panel"
    )
    online_parser.add_argument("--public-host", default="127.0.0.1")
    online_parser.add_argument("--public-port", type=int, default=8000)
    online_parser.add_argument("--admin-host", default="127.0.0.1")
    online_parser.add_argument("--admin-port", type=int, default=8001)

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
    service = StorageAwareCollectorService(Database(DATABASE_PATH), AUDIO_DIR)

    if args.command == "serve":
        serve(
            service=service,
            host=args.host,
            port=args.port,
            api_key=API_KEY,
            admin_file=ROOT / "admin.html",
            public_base_url=PUBLIC_BASE_URL,
        )
    elif args.command == "online":
        config = load_or_create_online_config()
        print(f"Admin key for local panel: {config['admin_key']}")
        print(f"The admin key is stored only on this PC: {ONLINE_CONFIG_PATH}")
        print("Android volunteers do not need a password or project key.")
        serve_online(
            service=service,
            public_host=args.public_host,
            public_port=args.public_port,
            admin_host=args.admin_host,
            admin_port=args.admin_port,
            admin_key=config["admin_key"],
            admin_file=ROOT / "admin.html",
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
