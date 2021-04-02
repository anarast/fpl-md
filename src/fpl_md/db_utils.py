from typing import Dict, Optional
from .db import db_connect

db_conn = db_connect()

def db_select_one(query: str, params: Optional[Dict] = None):
  select_cur = db_conn.cursor()
  
  if params is None:
    select_cur.execute(query)
  else:
    select_cur.execute(query, params)
  
  return select_cur.fetchone();

def db_select_all(query: str, params: Optional[Dict] = None):
  select_cur = db_conn.cursor()
  
  if params is None:
    select_cur.execute(query)
  else:
    select_cur.execute(query, params)
  
  return select_cur.fetchall();

def db_write(query: str, params: Dict):
  write_cur = db_conn.cursor()
  write_cur.execute(query, params)
  db_conn.commit()
  
