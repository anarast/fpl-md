import os
import sqlite3
import logging

from sqlite3.dbapi2 import Error

logger = logging.getLogger()

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), 'fplmd.db')

def db_connect(db_path=DEFAULT_PATH):
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Error as e:
        logger.error("An error occurred connecting to the database: " + e)

    return conn