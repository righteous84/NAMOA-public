from pathlib import Path

from app.database.db import get_connection

try:
    from app.database.migration_handlers import MIGRATION_HANDLERS
except ImportError:
    MIGRATION_HANDLERS = {}


MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def ensure_migrations_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_name TEXT NOT NULL UNIQUE,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()


def get_applied_migrations(conn):
    cursor = conn.execute(
        "SELECT migration_name FROM migrations"
    )

    return {row[0] for row in cursor.fetchall()}


def apply_migration(conn, migration_path):
    print(f"Applying {migration_path.name} ...")

    handler = MIGRATION_HANDLERS.get(
        migration_path.name
    )

    if handler:
        handler(conn)

    else:
        sql = migration_path.read_text(
            encoding="utf-8"
        )

        conn.executescript(sql)

    conn.execute(
        """
        INSERT INTO migrations (migration_name)
        VALUES (?)
        """,
        (migration_path.name,),
    )

    conn.commit()

    print(f"✓ Applied {migration_path.name}")


def run_migrations(database_path=None):
    conn = get_connection(database_path)

    ensure_migrations_table(conn)

    applied = get_applied_migrations(conn)

    migration_files = sorted(
        MIGRATIONS_DIR.glob("*.sql")
    )

    if not migration_files:
        print("No migrations found.")
        return

    print("\n===================================")
    print(" Securestack Migration Engine")
    print("===================================\n")

    for migration in migration_files:

        if migration.name in applied:
            print(
                f"Skipping {migration.name} "
                "(already applied)"
            )
            continue

        apply_migration(
            conn,
            migration,
        )

    print("\n===================================")
    print(" Database is up to date")
    print("===================================\n")

    conn.close()


if __name__ == "__main__":
    run_migrations()
