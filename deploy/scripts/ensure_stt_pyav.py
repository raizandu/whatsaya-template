#!/usr/bin/env python3
"""Pin the PyAV release required by the bundled faster-whisper decoder."""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys


PYAV_VERSION = "18.1.0"
PYAV_SPEC = f"av=={PYAV_VERSION}"


def _installed_version(target: Path | None) -> str | None:
    if target is None:
        try:
            return importlib.metadata.version("av")
        except importlib.metadata.PackageNotFoundError:
            return None
    for dist in importlib.metadata.distributions(path=[str(target)]):
        if (dist.metadata.get("Name") or "").casefold() == "av":
            return dist.version
    return None


def _uv_binary() -> str | None:
    if uv := shutil.which("uv"):
        return uv
    try:
        from hermes_cli.managed_uv import resolve_uv

        return resolve_uv()
    except Exception:
        return None


def ensure_pyav(target: Path, *, uv: str | None = None, run=subprocess.run) -> bool:
    """Install the pinned wheel in Hermes' durable lazy target when needed."""
    core_version = _installed_version(None)
    if core_version and core_version != PYAV_VERSION:
        raise RuntimeError("pyav_core_conflict")
    if core_version == PYAV_VERSION:
        return False

    if _installed_version(target) == PYAV_VERSION:
        return False

    uv = uv or _uv_binary()
    if not uv:
        raise RuntimeError("uv_unavailable")
    result = run(
        [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--target",
            str(target),
            "--no-deps",
            PYAV_SPEC,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("pyav_install_failed")
    if _installed_version(target) != PYAV_VERSION:
        raise RuntimeError("pyav_version_unverified")
    return True


def main() -> int:
    raw_target = os.environ.get("HERMES_LAZY_INSTALL_TARGET", "").strip()
    if not raw_target:
        print("[setup] PyAV guard ignorado: Hermes não usa target lazy durável")
        return 0

    target = Path(raw_target)
    try:
        changed = ensure_pyav(target)
    except Exception as exc:
        code = str(exc) if str(exc).isidentifier() else "pyav_setup_failed"
        print(f"[setup] PyAV guard falhou: {code}")
        return 1
    state = "fixado" if changed else "já compatível"
    print(f"[setup] PyAV {PYAV_VERSION} {state} no target lazy do Hermes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
