"""Usuários do painel: `panel_users.json`, senha com pbkdf2.

Módulo puro no molde de `contacts_store.py`: mesmo `flock` entre processos
(o servidor do painel pode rodar mais de um worker) e escrita atômica
(tmp + `os.replace`). Não importa o plugin nem o servidor.

Papéis: `admin` (acesso completo) e `atendente` (só responde e trabalha o
funil; `server.py` decide o que cada papel pode chamar). O admin do env
(`HERMES_DASHBOARD_BASIC_AUTH_USERNAME`/`_PASSWORD`) continua existindo fora
deste arquivo — este módulo só cobre usuários extras.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

WEAK_PASSWORDS = {"", "admin123", "admin", "password", "senha"}

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
ROLES = ("admin", "atendente")
MIN_PASSWORD_LENGTH = 10
PBKDF2_ITERATIONS = 200_000

_LOCAL = threading.RLock()
_HELD: dict[str, object] = {"fd": None, "depth": 0, "path": None}


def _lock_path_for(path: Path | str) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".lock")


@contextmanager
def _file_lock(path: Path | str) -> Iterator[None]:
    """Mesmo desenho de `contacts_store.file_lock`: exclusão mútua entre
    processos e threads, reentrante dentro do processo."""
    lock_file = _lock_path_for(path)
    with _LOCAL:
        if _HELD["depth"] == 0:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError:
                os.close(fd)
                raise
            _HELD["fd"] = fd
            _HELD["path"] = str(lock_file)
        _HELD["depth"] = int(_HELD["depth"]) + 1
        try:
            yield
        finally:
            _HELD["depth"] = int(_HELD["depth"]) - 1
            if _HELD["depth"] == 0:
                fd = _HELD["fd"]
                _HELD["fd"] = None
                _HELD["path"] = None
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)


def _read_all(path: Path | str) -> dict[str, dict]:
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("panel_users.json não contém objeto")
    return raw


def _write_all_atomic(path: Path | str, users: dict[str, dict]) -> None:
    """tmp + fsync + rename sob o lock, modo 0600 (mesmo cuidado de
    `management_store`: o arquivo guarda hash de senha)."""
    path = Path(path)
    with _file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(users, fh, ensure_ascii=False, indent=2)
                    fh.flush()
                    os.fsync(fh.fileno())
            except BaseException:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def _validate_username(username: str) -> str:
    username = str(username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError(
            "Usuário precisa ter de 3 a 32 caracteres, só letras minúsculas, "
            "números, ponto, hífen ou underscore."
        )
    return username


def _validate_name(name: str) -> str:
    name = str(name or "").strip()
    if not (2 <= len(name) <= 60):
        raise ValueError("Nome precisa ter de 2 a 60 caracteres.")
    return name


def _validate_role(role: str) -> str:
    role = str(role or "").strip()
    if role not in ROLES:
        raise ValueError(f"Papel inválido; use um de: {', '.join(ROLES)}.")
    return role


def _validate_password(password: str) -> str:
    password = str(password or "")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    if password in WEAK_PASSWORDS:
        raise ValueError("Senha fraca demais; escolha outra.")
    return password


def _hash_password(password: str) -> dict:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS,
    ).hex()
    return {"salt": salt, "iterations": PBKDF2_ITERATIONS, "hash": digest}


def _check_password(password: str, pbkdf2: dict) -> bool:
    try:
        salt = str(pbkdf2["salt"])
        iterations = int(pbkdf2["iterations"])
        expected = str(pbkdf2["hash"])
    except (KeyError, TypeError, ValueError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations,
    ).hex()
    return hmac.compare_digest(digest, expected)


def _public(record: dict) -> dict:
    """Nunca devolve `pbkdf2` (salt/hash)."""
    return {
        "username": record["username"],
        "name": record["name"],
        "role": record["role"],
        "active": bool(record["active"]),
        "created_utc": record.get("created_utc"),
    }


def list_users(path: Path | str) -> list[dict]:
    """Todos os usuários, sem hash/salt. Lista vazia se o arquivo não existe."""
    users = _read_all(path)
    return [_public(record) for record in users.values() if isinstance(record, dict)]


def get_user(path: Path | str, username: str) -> dict | None:
    """Um usuário, sem hash/salt. `None` se não existe."""
    username = str(username or "").strip().lower()
    users = _read_all(path)
    record = users.get(username)
    return _public(record) if isinstance(record, dict) else None


def create_user(path: Path | str, *, username: str, name: str, password: str, role: str) -> dict:
    username = _validate_username(username)
    name = _validate_name(name)
    role = _validate_role(role)
    password = _validate_password(password)
    with _file_lock(path):
        users = _read_all(path)
        if username in users:
            raise ValueError("Já existe um usuário com esse nome.")
        record = {
            "username": username,
            "name": name,
            "role": role,
            "active": True,
            "pbkdf2": _hash_password(password),
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        users[username] = record
        _write_all_atomic(path, users)
        return _public(record)


def verify_login(path: Path | str, username: str, password: str) -> dict | None:
    """Usuário ativo cuja senha bate; `None` em qualquer outro caso (usuário
    ausente, inativo, senha errada, ou arquivo inexistente — sem criar nada)."""
    username = str(username or "").strip().lower()
    password = str(password or "")
    if not username or not password:
        return None
    users = _read_all(path)
    record = users.get(username)
    if not isinstance(record, dict):
        return None
    if not record.get("active"):
        return None
    if not _check_password(password, record.get("pbkdf2") or {}):
        return None
    return _public(record)


def set_password(path: Path | str, username: str, password: str) -> dict:
    username = _validate_username(username)
    password = _validate_password(password)
    with _file_lock(path):
        users = _read_all(path)
        record = users.get(username)
        if not isinstance(record, dict):
            raise ValueError("Usuário não encontrado.")
        record["pbkdf2"] = _hash_password(password)
        users[username] = record
        _write_all_atomic(path, users)
        return _public(record)


def set_active(path: Path | str, username: str, active: bool) -> dict:
    username = _validate_username(username)
    with _file_lock(path):
        users = _read_all(path)
        record = users.get(username)
        if not isinstance(record, dict):
            raise ValueError("Usuário não encontrado.")
        record["active"] = bool(active)
        users[username] = record
        _write_all_atomic(path, users)
        return _public(record)
