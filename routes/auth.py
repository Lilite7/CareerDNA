import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "careerdna.db")

SECRET_KEY = os.getenv(
    "CAREERDNA_SECRET",
    "careerdna-development-secret-change-this",
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

security = HTTPBearer()


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_table():
    conn = get_db()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()


# ============================================================
# REQUEST MODELS
# ============================================================

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ============================================================
# PASSWORD HASHING
# ============================================================

def hash_password(password: str, salt: bytes | None = None):

    if salt is None:
        salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        120000,
    )

    return (
        base64.b64encode(salt).decode(),
        base64.b64encode(password_hash).decode(),
    )


def verify_password(password: str, stored: str):

    try:
        salt_b64, hash_b64 = stored.split("$")

        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            120000,
        )

        return hmac.compare_digest(actual, expected)

    except Exception:
        return False


# ============================================================
# TOKEN
# ============================================================

def create_token(user_id: int, email: str):

    payload = {
        "user_id": user_id,
        "email": email,
        "exp": int(time.time()) + 60 * 60 * 24,
    }

    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(
            payload,
            separators=(",", ":"),
        ).encode()
    ).decode()

    signature = hmac.new(
        SECRET_KEY.encode(),
        encoded_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    return f"{encoded_payload}.{signature}"


def decode_token(token: str):

    try:
        payload_part, signature = token.split(".")

        expected_signature = hmac.new(
            SECRET_KEY.encode(),
            payload_part.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(
            signature,
            expected_signature,
        ):
            raise ValueError("Invalid signature")

        payload = json.loads(
            base64.urlsafe_b64decode(
                payload_part.encode()
            )
        )

        if payload["exp"] < int(time.time()):
            raise ValueError("Token expired")

        return payload

    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session",
        )


# ============================================================
# CURRENT USER
# ============================================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    return decode_token(credentials.credentials)


# ============================================================
# REGISTER
# ============================================================

@router.post("/register")
def register(data: RegisterRequest):

    name = data.name.strip()
    email = data.email.lower().strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Name is required",
        )

    if len(data.password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least 6 characters",
        )

    conn = get_db()

    existing = conn.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
        """,
        (email,),
    ).fetchone()

    if existing:
        conn.close()

        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists",
        )

    salt, password_hash = hash_password(data.password)

    stored_hash = f"{salt}${password_hash}"

    cursor = conn.execute(
        """
        INSERT INTO users
        (
            name,
            email,
            password_hash
        )
        VALUES (?, ?, ?)
        """,
        (
            name,
            email,
            stored_hash,
        ),
    )

    conn.commit()

    user_id = cursor.lastrowid

    conn.close()

    token = create_token(
        user_id,
        email,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "name": name,
            "email": email,
        },
    }


# ============================================================
# LOGIN
# ============================================================

@router.post("/login")
def login(data: LoginRequest):

    email = data.email.lower().strip()

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE email = ?
        """,
        (email,),
    ).fetchone()

    conn.close()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if not verify_password(
        data.password,
        user["password_hash"],
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    token = create_token(
        user["id"],
        user["email"],
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
        },
    }


# ============================================================
# CURRENT USER
# ============================================================

@router.get("/me")
def me(
    user=Depends(get_current_user)
):

    conn = get_db()

    row = conn.execute(
        """
        SELECT
            id,
            name,
            email,
            created_at
        FROM users
        WHERE id = ?
        """,
        (user["user_id"],),
    ).fetchone()

    conn.close()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return dict(row)