from app.utils.logger import logger
from pathlib import Path
import sqlite3

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "data" / "media.db"


def get_connection(database_path=None):

    path = (
        database_path
        if database_path
        else DATABASE_PATH
    )

    connection = sqlite3.connect(path)

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA foreign_keys = ON;"
    )

    return connection
