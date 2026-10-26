import sys

from app.database.migrate import run_migrations

from app.cli import run as run_cli


def serve_command(args):
    """
    Launch the NAMOA GUI (Sprint 6.12).

    Usage:
      python -m app.main serve [host] [port] [--db PATH]
    """

    host = "127.0.0.1"
    port = 8080
    database_path = None

    positional = []

    index = 0

    while index < len(args):

        argument = args[index]

        if argument == "--db":
            if index + 1 >= len(args):
                print("Missing path after --db")
                return
            database_path = args[index + 1]
            index += 2
            continue

        positional.append(argument)
        index += 1

    if len(positional) >= 1:
        host = positional[0]

    if len(positional) >= 2:
        try:
            port = int(positional[1])
        except ValueError:
            print(f"Invalid port: {positional[1]}")
            return

    from app.web.composition import build_services
    from app.web.server import create_server

    # Bring the configured database through the established numbered
    # migration mechanism before the GUI touches the schema. A normal
    # restart therefore results in a usable schema (e.g. migration 031
    # notifications/scan-progress) without any manual repair.
    run_migrations(database_path=database_path)

    service_factory = (
        lambda: build_services(
            database_path=database_path,
        )
    )

    # Startup backstop for transient optimisation previews: every
    # in-memory preview context is gone after a restart, so any
    # owned artifacts left behind are orphans. Sweep them before
    # serving; cleanup never fails startup.
    try:
        startup_services = service_factory()

        sweep_report = (
            startup_services.preview_service.startup_cleanup()
        )

        removed = sweep_report.get("removed", [])

        if removed:
            print(
                f"Cleaned up {len(removed)} abandoned "
                "preview artifact(s)."
            )
    except Exception as error:
        print(f"Preview startup cleanup skipped: {error}")

    server = create_server(
        service_factory,
        host=host,
        port=port,
        database_path=database_path,
    )

    print(f"NAMOA GUI listening on http://{host}:{port}")
    print("(Ctrl+C to stop)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping NAMOA GUI")
    finally:
        server.server_close()


def main():

    if len(sys.argv) < 2:
        print("""
NAMOA

Not Another Media Optimizer... Actually.

Usage:
  python -m app.main migrate
  python -m app.main serve [host] [port] [--db PATH]
  python -m app.main <operational command>

Operational commands (scan, status, media, recommendations,
queue, explain, provenance, library, analyse, export):

  python -m app.main help
""")
        return

    command = sys.argv[1]

    if command == "migrate":
        run_migrations()

    elif command == "serve":
        serve_command(sys.argv[2:])

    else:
        # Operational workflows are implemented in the CLI module,
        # which consumes application services only (never scanner
        # or pipeline internals directly).
        raise SystemExit(
            run_cli(sys.argv[1:])
        )


if __name__ == "__main__":
    main()
