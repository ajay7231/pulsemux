import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlsplit
from cryptography.fernet import Fernet, MultiFernet
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from .database import database, get_db
from .models import User, LoginSession

COOKIE = "pulsemux_session"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def cipher():
    keys = os.getenv("PLATFORM_ENCRYPTION_KEYS", "")
    if not keys:
        if os.getenv("PLATFORM_ENV") == "production":
            raise RuntimeError("PLATFORM_ENCRYPTION_KEYS must be set in production")
        path = database().data_dir / "secret.key"
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(Fernet.generate_key())
        except FileExistsError:
            pass
        keys = path.read_text().strip()
    return MultiFernet([Fernet(key.strip().encode()) for key in keys.split(",")])


def encrypt(value):
    return cipher().encrypt(json.dumps(value).encode()).decode()


def decrypt(value):
    return json.loads(cipher().decrypt(value.encode()))


def password_hash(password):
    salt = secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
    return f"pbkdf2$600000${salt.hex()}${value.hex()}"


def verify_password(password, stored):
    try:
        _, rounds, salt, expected = stored.split("$")
        value = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds)
        )
        return hmac.compare_digest(value.hex(), expected)
    except (ValueError, TypeError):
        return False


def check_origin(request):
    origin = request.headers.get("origin")
    expected = (
        os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        or f'{ {"ws":"http","wss":"https"}.get(request.url.scheme, request.url.scheme)}://{request.headers.get("host", "")}'
    )
    if origin and origin != expected:
        raise HTTPException(403, "Cross-origin request rejected")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site request rejected")


def current_user(request: Request, db: Session = Depends(get_db)):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
    token = request.cookies.get(COOKIE, "")
    login = db.get(LoginSession, digest(token)) if token else None
    user = (
        db.get(User, login.user_id)
        if login and login.expires_at > time.time()
        else None
    )
    if not user or not user.active:
        raise HTTPException(401, "Sign in to continue")
    return user


def editor(user=Depends(current_user)):
    if user.role not in {"admin", "operator"}:
        raise HTTPException(403, "Operator access required")
    return user


def admin(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


def set_login(response: Response, db, user):
    token = secrets.token_urlsafe(40)
    db.add(
        LoginSession(
            token_hash=digest(token), user_id=user.id, expires_at=time.time() + 43200
        )
    )
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=os.getenv("PLATFORM_ENV") == "production",
        samesite="strict",
        max_age=43200,
        path="/",
    )


def websocket_user(ws):
    check_origin(ws)
    token = ws.cookies.get(COOKIE, "")
    with database().Session() as db:
        login = db.get(LoginSession, digest(token)) if token else None
        user = (
            db.get(User, login.user_id)
            if login and login.expires_at > time.time()
            else None
        )
        if not user or not user.active:
            raise HTTPException(401, "Sign in to continue")
        return user
