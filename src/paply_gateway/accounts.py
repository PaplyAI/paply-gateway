import asyncio
import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import time

SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LENGTH = 32


class AccountExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshSessionError(Exception):
    pass


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    display_name: str
    created_at: int


def normalize_email(value: str) -> str:
    return value.strip().lower()


def _password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_LENGTH,
    )
    return "$".join(
        (
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(digest).decode(),
        )
    )


def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_value, digest_value = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value)
        expected = base64.urlsafe_b64decode(digest_value)
        actual = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, actual)


def _refresh_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


DUMMY_PASSWORD_HASH = _password_hash("paply-dummy-password-not-used")


class AccountStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paply_accounts (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paply_refresh_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES paply_accounts(id) ON DELETE CASCADE,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS paply_refresh_sessions_user_id
                    ON paply_refresh_sessions(user_id);
                CREATE INDEX IF NOT EXISTS paply_refresh_sessions_expires_at
                    ON paply_refresh_sessions(expires_at);
                """
            )

    async def ping(self) -> None:
        await asyncio.to_thread(self._ping_sync)

    def _ping_sync(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    async def create_account(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        password: str,
    ) -> Account:
        return await asyncio.to_thread(
            self._create_account_sync,
            user_id,
            normalize_email(email),
            display_name.strip(),
            password,
        )

    def _create_account_sync(
        self,
        user_id: str,
        email: str,
        display_name: str,
        password: str,
    ) -> Account:
        created_at = int(time())
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO paply_accounts
                        (id, email, display_name, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, email, display_name, _password_hash(password), created_at),
                )
        except sqlite3.IntegrityError as error:
            raise AccountExistsError from error
        return Account(user_id, email, display_name, created_at)

    async def delete_account(self, user_id: str) -> None:
        await asyncio.to_thread(self._delete_account_sync, user_id)

    def _delete_account_sync(self, user_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM paply_accounts WHERE id = ?", (user_id,))

    async def authenticate(self, email: str, password: str) -> Account:
        return await asyncio.to_thread(
            self._authenticate_sync,
            normalize_email(email),
            password,
        )

    def _authenticate_sync(self, email: str, password: str) -> Account:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, display_name, password_hash, created_at
                FROM paply_accounts WHERE email = ?
                """,
                (email,),
            ).fetchone()
        encoded = DUMMY_PASSWORD_HASH if row is None else row["password_hash"]
        password_matches = _password_matches(password, encoded)
        if row is None or not password_matches:
            raise InvalidCredentialsError
        return Account(row["id"], row["email"], row["display_name"], row["created_at"])

    async def account(self, user_id: str) -> Account | None:
        return await asyncio.to_thread(self._account_sync, user_id)

    def _account_sync(self, user_id: str) -> Account | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, display_name, created_at
                FROM paply_accounts WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return Account(row["id"], row["email"], row["display_name"], row["created_at"])

    async def create_refresh_session(
        self,
        user_id: str,
        *,
        expires_at: int,
    ) -> str:
        return await asyncio.to_thread(
            self._create_refresh_session_sync,
            user_id,
            expires_at,
        )

    def _create_refresh_session_sync(self, user_id: str, expires_at: int) -> str:
        token = secrets.token_urlsafe(48)
        now = int(time())
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM paply_refresh_sessions WHERE expires_at <= ?",
                (now,),
            )
            connection.execute(
                """
                INSERT INTO paply_refresh_sessions
                    (token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (_refresh_hash(token), user_id, now, expires_at),
            )
        return token

    async def rotate_refresh_session(
        self,
        token: str,
        *,
        expires_at: int,
    ) -> tuple[Account, str]:
        return await asyncio.to_thread(
            self._rotate_refresh_session_sync,
            token,
            expires_at,
        )

    def _rotate_refresh_session_sync(
        self,
        token: str,
        expires_at: int,
    ) -> tuple[Account, str]:
        now = int(time())
        new_token = secrets.token_urlsafe(48)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT a.id, a.email, a.display_name, a.created_at, s.expires_at
                FROM paply_refresh_sessions AS s
                JOIN paply_accounts AS a ON a.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (_refresh_hash(token),),
            ).fetchone()
            if row is None or row["expires_at"] <= now:
                connection.execute(
                    "DELETE FROM paply_refresh_sessions WHERE token_hash = ?",
                    (_refresh_hash(token),),
                )
                raise InvalidRefreshSessionError
            connection.execute(
                "DELETE FROM paply_refresh_sessions WHERE token_hash = ?",
                (_refresh_hash(token),),
            )
            connection.execute(
                """
                INSERT INTO paply_refresh_sessions
                    (token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (_refresh_hash(new_token), row["id"], now, expires_at),
            )
        return (
            Account(row["id"], row["email"], row["display_name"], row["created_at"]),
            new_token,
        )

    async def revoke_refresh_session(self, token: str) -> None:
        await asyncio.to_thread(self._revoke_refresh_session_sync, token)

    def _revoke_refresh_session_sync(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM paply_refresh_sessions WHERE token_hash = ?",
                (_refresh_hash(token),),
            )
