"""
NAMOA GUI web layer (Sprint 6.12).

Dependency direction (strict):

    app/web (GUI)
        |
        v
    app/application (Application Services)
        |
        v
    app/services + app/database (authorities / persistence)

The web layer NEVER imports or touches repositories, domain
services, models, engines, or the database directly. Every read
and every action flows through the application services.

Components:

    composition   - composition root wiring application services
    serializers   - read models -> JSON-safe presentation dicts
    handlers      - page/API data assembly (thin, no persistence)
    templates     - server-rendered HTML (escaped)
    server        - stdlib http.server router + error handling
"""

from app.web.composition import build_services
from app.web.server import create_server

__all__ = [
    "build_services",
    "create_server",
]
