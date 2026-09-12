"""Kompatibilitaets-Wrapper fuer den Lore-HTML-Builder.

Die eigentliche Implementierung liegt in `build_lore_html_impl.py`, damit
dieses Modul klein bleibt und statische Analyse-Regeln erfuellt.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_impl_module():
    if __package__:
        from . import build_lore_html_impl as impl

        return impl

    impl_path = Path(__file__).with_name("build_lore_html_impl.py")
    spec = importlib.util.spec_from_file_location("build_lore_html_impl", impl_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Konnte Implementierungsmodul nicht laden: {impl_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_impl = _load_impl_module()

# Haupt-API explizit weiterreichen fuer stabile Imports.
build = _impl.build
main = _impl.main


def __getattr__(name: str):
    return getattr(_impl, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_impl)))


if __name__ == "__main__":
    main()
