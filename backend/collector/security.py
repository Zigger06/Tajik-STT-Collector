from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from .service import (
    CollectorError,
    CollectorService,
    ConflictError,
    ForbiddenError,
    normalize_text,
    validate_uuid,
)


class AuthenticationError(CollectorError):
    status_code = 401


class RateLimitError(CollectorError):
    status_code = 429

    def __init__(self, retry_after: int):
        super().__init__("too many requests")
        self.retry_after = max(1, int(retry_after))


class RegistrationProofError(CollectorError):
    status_code = 428


@dataclass(frozen=True)
class RateRule:
    limit: int
    window_seconds: int


DEFAULT_RATE_RULES: dict[str, dict[str, tuple[RateRule, ...]]] = {
    # Registration is special: before a credential exists, IP is only an extra signal.
    # A proof-of-work challenge is the IP-independent Sybil friction.
    "registration": {
        "device": (RateRule(6, 3600),),
        "ip": (RateRule(20, 3600), RateRule(80, 86400)),
    },
    "challenge": {
        "device": (RateRule(12, 3600),),
        "ip": (RateRule(60, 3600),),
    },
    "task": {
        "device": (RateRule(180, 600),),
        "ip": (RateRule(2500, 600),),
    },
    "stats": {
        "device": (RateRule(120, 600),),
        "ip": (RateRule(2000, 600),),
    },
    "data": {
        "device": (RateRule(120, 600),),
        "ip": (RateRule(2000, 600),),
    },
    "text": {
        "device": (RateRule(30, 3600),),
        "ip": (RateRule(500, 3600),),
    },
    "review": {
        "device": (RateRule(180, 3600),),
        "ip": (RateRule(2500, 3600),),
    },
    "upload": {
        "device": (RateRule(40, 3600),),
        "ip": (RateRule(600, 3600),),
    },
}


class SlidingWindowRateLimiter:
    """Small in-memory limiter for the single-PC backend.

    Device credentials are the primary key. Source IP is deliberately only an
    aggregate secondary signal because mobile users can share carrier NAT. When
    Funnel hides the original address and the backend sees loopback, IP limits
    are skipped rather than treating every volunteer as one person.
    """

    def __init__(self, rules: dict[str, dict[str, tuple[RateRule, ...]]] | None = None):
        self.rules = rules or DEFAULT_RATE_RULES
        self._events: dict[tuple[str, str, int], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _usable_ip(ip: str) -> bool:
        return bool(ip) and ip not in {"127.0.0.1", "::1"}

    def check(self, category: str, device_key: str, ip: str) -> None:
        category_rules = self.rules.get(category, {})
        checks: list[tuple[str, str, RateRule]] = []
        for rule in category_rules.get("device", ()):
            checks.append(("device", device_key, rule))
        if self._usable_ip(ip):
            for rule in category_rules.get("ip", ()):
                checks.append(("ip", ip, rule))

        now = time.monotonic()
        with self._lock:
            for scope, key, rule in checks:
                bucket_key = (f"{category}:{scope}", key, rule.window_seconds)
                bucket = self._events[bucket_key]
                cutoff = now - rule.window_seconds
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if len(bucket) >= rule.limit:
                    retry_after = max(1, int(rule.window_seconds - (now - bucket[0])) + 1)
                    raise RateLimitError(retry_after)
            for scope, key, rule in checks:
                self._events[(f"{category}:{scope}", key, rule.window_seconds)].append(now)


class RegistrationChallengeManager:
    def __init__(self, difficulty_bits: int = 19, ttl_seconds: int = 120):
        self.difficulty_bits = max(4, min(int(difficulty_bits), 24))
        self.ttl_seconds = max(30, min(int(ttl_seconds), 300))
        self._items: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def issue(self, binding: str) -> dict:
        nonce = secrets.token_urlsafe(24)
        expires_at = time.monotonic() + self.ttl_seconds
        with self._lock:
            now = time.monotonic()
            self._items = {
                key: value for key, value in self._items.items() if value[0] > now
            }
            self._items[nonce] = (expires_at, binding)
        return {
            "nonce": nonce,
            "difficulty": self.difficulty_bits,
            "expires_in": self.ttl_seconds,
        }

    def verify(self, nonce: str, proof: str, binding: str) -> None:
        try:
            counter = int(proof)
        except (TypeError, ValueError) as exc:
            raise RegistrationProofError("valid registration proof is required") from exc
        if counter < 0:
            raise RegistrationProofError("valid registration proof is required")

        with self._lock:
            item = self._items.pop(nonce, None)
        if not item:
            raise RegistrationProofError("registration challenge is missing or already used")
        expires_at, expected_binding = item
        if time.monotonic() > expires_at or not secrets.compare_digest(
            expected_binding, binding
        ):
            raise RegistrationProofError("registration challenge expired")

        digest = hashlib.sha256(f"{nonce}:{counter}".encode("utf-8")).digest()
        if not self._has_leading_zero_bits(digest, self.difficulty_bits):
            raise RegistrationProofError("registration proof is invalid")

    @staticmethod
    def _has_leading_zero_bits(digest: bytes, bits: int) -> bool:
        whole_bytes, remaining_bits = divmod(bits, 8)
        if any(digest[index] != 0 for index in range(whole_bytes)):
            return False
        if remaining_bits == 0:
            return True
        mask = 0xFF << (8 - remaining_bits) & 0xFF
        return digest[whole_bytes] & mask == 0


class DeviceSecurity:
    """Anonymous bearer-token authentication for volunteers.

    The Android app owns a random 256-bit token. SQLite stores only a random
    salt and SHA-256(salt || token). A fast hash is intentional here: unlike a
    human password, the token already has high entropy and is not guessable.
    """

    def __init__(
        self,
        service: CollectorService,
        *,
        challenge_difficulty: int = 19,
        rate_rules: dict[str, dict[str, tuple[RateRule, ...]]] | None = None,
    ):
        self.service = service
        self.rate_limiter = SlidingWindowRateLimiter(rate_rules)
        self.challenges = RegistrationChallengeManager(challenge_difficulty)

    @staticmethod
    def validate_secret(secret: str) -> str:
        secret = (secret or "").strip()
        if not 40 <= len(secret) <= 160:
            raise AuthenticationError("device credential is missing or invalid")
        if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in secret):
            raise AuthenticationError("device credential is missing or invalid")
        return secret

    @staticmethod
    def device_key(volunteer_id: str, secret: str) -> str:
        return hashlib.sha256(f"{volunteer_id}:{secret}".encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_secret(secret: str, salt: bytes) -> str:
        return hashlib.sha256(salt + secret.encode("utf-8")).hexdigest()

    def issue_registration_challenge(self, volunteer_id: str, secret: str, ip: str) -> dict:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        secret = self.validate_secret(secret)
        key = self.device_key(volunteer_id, secret)
        self.rate_limiter.check("challenge", key, ip)
        return self.challenges.issue(key)

    def register_volunteer(
        self,
        *,
        volunteer_id: str,
        secret: str,
        display_name: str,
        region: str = "",
        dialect: str = "",
        consent: bool = False,
        challenge_nonce: str = "",
        challenge_proof: str = "",
        ip: str = "",
    ) -> dict:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        secret = self.validate_secret(secret)
        device_key = self.device_key(volunteer_id, secret)
        self.rate_limiter.check("registration", device_key, ip)

        with self.service.database.connect() as connection:
            volunteer = connection.execute(
                "SELECT id, display_name, consent_active FROM volunteers WHERE id = ?",
                (volunteer_id,),
            ).fetchone()
            credential = connection.execute(
                "SELECT secret_salt, secret_hash FROM device_credentials WHERE volunteer_id = ?",
                (volunteer_id,),
            ).fetchone()

        if credential:
            self._verify_row(secret, credential)
            if volunteer and not volunteer["consent_active"]:
                # Repeated background registration must never silently undo a
                # user's explicit withdrawal. Re-consent needs a future explicit flow.
                raise ForbiddenError("volunteer consent has been revoked")
        else:
            # New installs and one-time migration of pre-auth installs both need
            # proof-of-work. This creates Sybil friction without asking the user
            # for an account, CAPTCHA, phone number or email.
            self.challenges.verify(challenge_nonce, challenge_proof, device_key)
            if volunteer:
                # A legacy UUID can only be claimed by an upgrade that still has
                # the same locally stored display name. This is not perfect
                # identity proof, but prevents blind UUID-only takeover.
                old_name = normalize_text(volunteer["display_name"]).casefold()
                new_name = normalize_text(display_name).casefold()
                if old_name != new_name:
                    raise ConflictError("legacy volunteer profile does not match this device")
                if not volunteer["consent_active"]:
                    raise ForbiddenError("volunteer consent has been revoked")

        result = self.service.register_volunteer(
            volunteer_id=volunteer_id,
            display_name=display_name,
            region=region,
            dialect=dialect,
            consent=consent,
        )

        if not credential:
            salt = secrets.token_bytes(16)
            digest = self._hash_secret(secret, salt)
            with self.service.database.connect() as connection:
                try:
                    connection.execute(
                        """
                        INSERT INTO device_credentials (volunteer_id, secret_salt, secret_hash)
                        VALUES (?, ?, ?)
                        """,
                        (volunteer_id, salt.hex(), digest),
                    )
                except Exception as exc:
                    # A concurrent first registration may have won the race.
                    row = connection.execute(
                        "SELECT secret_salt, secret_hash FROM device_credentials WHERE volunteer_id = ?",
                        (volunteer_id,),
                    ).fetchone()
                    if not row:
                        raise
                    try:
                        self._verify_row(secret, row)
                    except AuthenticationError:
                        raise ConflictError("volunteer credential was initialized elsewhere") from exc
        return result

    def authenticate(
        self,
        volunteer_id: str,
        secret: str,
        category: str,
        ip: str,
        *,
        allow_revoked: bool = False,
    ) -> str:
        if not volunteer_id or not secret:
            raise AuthenticationError("device credential is missing or invalid")
        try:
            volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        except CollectorError as exc:
            raise AuthenticationError("device credential is missing or invalid") from exc
        secret = self.validate_secret(secret)
        with self.service.database.connect() as connection:
            row = connection.execute(
                """
                SELECT dc.secret_salt, dc.secret_hash, v.consent_active
                FROM device_credentials dc
                JOIN volunteers v ON v.id = dc.volunteer_id
                WHERE dc.volunteer_id = ?
                """,
                (volunteer_id,),
            ).fetchone()
        if not row:
            raise AuthenticationError("device credential is not registered")
        self._verify_row(secret, row)
        self.rate_limiter.check(category, self.device_key(volunteer_id, secret), ip)
        if not allow_revoked and not row["consent_active"]:
            raise ForbiddenError("volunteer consent has been revoked")
        return volunteer_id

    def _verify_row(self, secret: str, row) -> None:
        try:
            salt = bytes.fromhex(row["secret_salt"])
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("device credential is invalid") from exc
        actual = self._hash_secret(secret, salt)
        if not secrets.compare_digest(actual, row["secret_hash"]):
            raise AuthenticationError("device credential is invalid")
