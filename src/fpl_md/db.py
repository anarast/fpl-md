import sqlite3
import logging
import os

from sqlite3.dbapi2 import Error

logger = logging.getLogger()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "fplmd.db")

def db_connect():
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Error as e:
        logger.error("An error occurred connecting to the database: " + e)

    return conn