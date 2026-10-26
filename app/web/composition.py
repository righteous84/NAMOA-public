"""
Compatibility seam for the NAMOA GUI.

The application-service composition root lives in
app/application/composition.py (shared by the GUI and the CLI). This
module remains the web layer's single sanctioned wiring import point:
every other module under app/web consumes only app.application, and
this file is the one place allowed to reference the concrete wiring.
"""

from app.application.composition import (
    Services,
    build_services,
)

__all__ = [
    "Services",
    "build_services",
]
