"""Load the pure modules by path so they import without Home Assistant.

custom_components/culligan_azure/__init__.py imports Home Assistant, so a
package import would drag it in. health, resin and capabilities have no
imports of their own and are what the pure suite exercises.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType

COMPONENT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "culligan_azure"
)


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"culligan_pure_{name}", COMPONENT / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
