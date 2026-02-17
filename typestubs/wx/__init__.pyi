# Minimal wx type stub for CI type-checking without installing wxPython.
# wxPython requires native GTK/Cocoa libs and cannot be pip-installed on
# headless Linux CI runners without a lengthy source build.  This stub
# lets pyright resolve ``import wx`` and treat all attributes as Any.

from typing import Any

def __getattr__(name: str) -> Any: ...
