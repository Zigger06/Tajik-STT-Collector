from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from .http_api import make_handler
from .security import DeviceSecurity
from .service import CollectorService


# 19-bit proof-of-work was noticeably slow on mid-range Android phones. A 16-bit
# challenge is about eight times cheaper for a legitimate first registration while
# the existing per-device/IP registration limits still provide the main anti-abuse
# boundary. Existing devices do not solve this challenge again during normal use.
ANDROID_REGISTRATION_DIFFICULTY = 16


def serve_online_fast_registration(
    service: CollectorService,
    public_host: str,
    public_port: int,
    admin_host: str,
    admin_port: int,
    admin_key: str,
    admin_file: str | Path,
) -> None:
    """Run the Funnel-facing API with phone-friendly first-registration PoW."""
    if admin_host != "127.0.0.1":
        raise ValueError("The online admin panel must bind to 127.0.0.1 only")
    if public_host != "127.0.0.1":
        raise ValueError("The online public API target must bind to 127.0.0.1 only")

    public_security = DeviceSecurity(
        service,
        challenge_difficulty=ANDROID_REGISTRATION_DIFFICULTY,
    )
    admin_security = DeviceSecurity(
        service,
        challenge_difficulty=ANDROID_REGISTRATION_DIFFICULTY,
    )

    public_handler = make_handler(
        service,
        "",
        admin_file,
        allow_admin=False,
        security_context=public_security,
    )
    admin_handler = make_handler(
        service,
        admin_key,
        admin_file,
        allow_admin=True,
        security_context=admin_security,
    )
    public_server = ThreadingHTTPServer((public_host, public_port), public_handler)
    admin_server = ThreadingHTTPServer((admin_host, admin_port), admin_handler)
    public_thread = threading.Thread(target=public_server.serve_forever, daemon=True)
    public_thread.start()

    print(f"Public Android API target: http://{public_host}:{public_port}")
    print(f"Private admin panel: http://127.0.0.1:{admin_port}/admin")
    print("The admin panel is not exposed through Tailscale Funnel.")
    print("Press Ctrl+C to stop both servers.")
    try:
        admin_server.serve_forever()
    except KeyboardInterrupt:
        print("\nServers stopped.")
    finally:
        admin_server.server_close()
        public_server.shutdown()
        public_server.server_close()
        public_thread.join(timeout=2)
