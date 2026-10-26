from app.database.db import get_connection


def add_excluded_path(path: str, notes: str = ""):
    conn = get_connection()

    conn.execute(
        """
        INSERT OR IGNORE INTO excluded_paths
        (path, notes)
        VALUES (?, ?)
        """,
        (path, notes),
    )

    conn.commit()
    conn.close()


def get_excluded_paths():
    conn = get_connection()

    cursor = conn.execute(
        """
        SELECT path
        FROM excluded_paths
        WHERE enabled = 1
        """
    )

    paths = [row[0] for row in cursor.fetchall()]

    conn.close()

    return paths
