from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from sqlalchemy import delete, func, insert, select, text

from echooo.database import Store, tokens, users, uid, token_hash, ensure_default_domain


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def check_password(password: str, stored: str) -> bool:
    salt, expected = stored.split(":")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)


class Auth:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.Lock()
        self.failures: dict[str, list[float]] = {}

    def needs_setup(self) -> bool:
        with self.store.engine.connect() as c:
            return c.execute(select(func.count()).select_from(users)).scalar_one() == 0

    def setup(self, name: str, password: str) -> tuple[dict, str]:
        with self.lock, self.store.engine.begin() as c:
            if self.store.postgres:
                c.execute(text("SELECT pg_advisory_xact_lock(76823918)"))
            if c.execute(select(func.count()).select_from(users)).scalar_one():
                raise AuthError("This workspace is already set up. Please sign in.")
            user = {"id": uid(), "name": name, "password": hash_password(password), "created_at": time.time()}
            c.execute(insert(users).values(**user))
            ensure_default_domain(c, user["id"])
        return {"id": user["id"], "name": name}, self.issue(user["id"], "owner", 86400 * 7)

    def login(self, name: str, password: str, client: str) -> tuple[dict, str]:
        now = time.time()
        with self.lock:
            self.failures = {k: [t for t in v if t > now - 300] for k, v in self.failures.items() if any(t > now - 300 for t in v)}
            recent = self.failures.setdefault(client, [])
            if len(recent) >= 10:
                raise AuthError("Too many attempts. Please try again in five minutes.")
            recent.append(now)
        with self.store.engine.connect() as c:
            user = c.execute(select(users).where(users.c.name == name)).mappings().first()
        # Keep the expensive check for unknown names, too.
        valid = check_password(password, user["password"] if user else "00" * 16 + ":" + "00" * 64)
        if not user or not valid:
            raise AuthError("Incorrect username or password.")
        return {"id": user["id"], "name": user["name"]}, self.issue(user["id"], "owner", 86400 * 7)

    def issue(self, owner: str, kind: str, ttl: float, session_id: str | None = None) -> str:
        token = secrets.token_urlsafe(32)
        with self.store.engine.begin() as c:
            c.execute(delete(tokens).where(tokens.c.expires_at < time.time()))
            c.execute(insert(tokens).values(id=token_hash(token), owner_id=owner, kind=kind,
                session_id=session_id, expires_at=time.time() + ttl))
        return token

    def resolve(self, token: str | None, kind: str) -> dict:
        if not token:
            raise AuthError("Please sign in first.")
        with self.store.engine.connect() as c:
            row = c.execute(select(tokens).where(tokens.c.id == token_hash(token),
                tokens.c.kind == kind, tokens.c.expires_at > time.time())).mappings().first()
            if not row:
                raise AuthError("Your credential is no longer valid. Sign in again or request a new invitation.")
            owner = c.execute(select(users.c.name).where(users.c.id == row["owner_id"])).scalar_one()
        return {**dict(row), "name": owner}

    def consume_invite(self, token: str) -> dict:
        with self.lock, self.store.engine.begin() as c:
            # DELETE RETURNING makes invitation exchange one-time even across workers.
            row = c.execute(delete(tokens).where(tokens.c.id == token_hash(token),
                tokens.c.kind == "invite", tokens.c.expires_at > time.time()).returning(tokens)).mappings().first()
            if not row:
                raise AuthError("This invitation has been used or has expired. Ask the owner for a new one.")
            return dict(row)

    def revoke(self, token: str | None) -> None:
        if token:
            with self.store.engine.begin() as c:
                c.execute(delete(tokens).where(tokens.c.id == token_hash(token)))

    def revoke_room(self, owner: str, session_id: str) -> None:
        with self.store.engine.begin() as c:
            c.execute(delete(tokens).where(tokens.c.owner_id == owner, tokens.c.session_id == session_id))
