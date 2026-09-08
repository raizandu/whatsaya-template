"""Lock entre processos e escrita atômica de personal_contacts.json.

O plugin (dentro do gateway) e o painel (container próprio) gravam o mesmo
arquivo. O lock de thread do plugin não atravessa processos, então os dois lados
seguram um `flock` no arquivo ao lado (`personal_contacts.json.lock`) durante o
ler-mesclar-gravar. Reentrante dentro do processo: o plugin chama a gravação
atômica por dentro de outra seção já travada.
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_LOCAL = threading.RLock()
_HELD: dict[str, object] = {"fd": None, "depth": 0, "path": None}


def lock_path_for(path: Path | str) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".lock")


@contextmanager
def file_lock(path: Path | str) -> Iterator[None]:
    """Exclusão mútua entre processos e threads para o arquivo de contatos."""
    lock_file = lock_path_for(path)
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


def read_contacts(path: Path | str) -> dict:
    """Conteúdo cru do arquivo; {} quando não existe. JSON inválido levanta ValueError."""
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("personal_contacts.json não contém objeto")
    return raw


def write_contacts_atomic(path: Path | str, contacts: dict) -> None:
    """tmp + fsync + rename, sob o lock. Nunca deixa JSON parcial no disco."""
    path = Path(path)
    with file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(contacts, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def update_record(path: Path | str, keys: list[str] | tuple[str, ...], fields: dict) -> dict:
    """Ler-mesclar-gravar de campos em uma ou mais chaves (o telefone e seu espelho
    `@lid`), tudo sob o mesmo lock. Valor None remove o campo. Retorna o arquivo
    resultante."""
    path = Path(path)
    with file_lock(path):
        contacts = read_contacts(path)
        for key in keys:
            if not key:
                continue
            record = contacts.get(key)
            record = dict(record) if isinstance(record, dict) else {}
            for name, value in fields.items():
                if value is None:
                    record.pop(name, None)
                else:
                    record[name] = value
            contacts[key] = record
        write_contacts_atomic(path, contacts)
        return contacts
