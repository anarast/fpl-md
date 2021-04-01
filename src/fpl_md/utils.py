import os
import json

import aiohttp
import redis

from fpl import FPL
from fpl.models import User
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
http_sess: Optional[aiohttp.ClientSession] = None
fpl_client: Optional[FPL] = None
redis_conn = redis.Redis(host=os.getenv("REDIS_HOST"), port=6379)

def get_http_sess() -> aiohttp.ClientSession:
    global http_sess
    if http_sess is None:
        http_sess = aiohttp.ClientSession()
    return http_sess


async def get_fpl_client() -> FPL:
    global fpl_client
    if fpl_client is not None:
        return fpl_client

    return FPL(get_http_sess())

async def get_picks(user: User, gw: Optional[int] = None):
    if gw is None:
        gw = user.current_event

    cid = f"picks:{user.id}:{gw}"
    raw_picks = redis_conn.get(cid)
    if raw_picks is None:
        picks = await user.get_picks(gw)
        raw_picks = json.dumps(picks)
        redis_conn.set(name=cid, value=raw_picks, ex=600)

    picks = json.loads(raw_picks)

    return picks[str(gw)]

async def load_team(team_id: int):
    cid = f"team:{team_id}"
    raw_user = redis_conn.get(cid)
    if raw_user is None:
        client = await get_fpl_client()
        raw_user = await client.get_user(team_id, return_json=True)
        redis_conn.set(name=cid, value=json.dumps(raw_user), ex=600)
    else:
        raw_user = json.loads(raw_user)

    return User(raw_user, session=get_http_sess())

async def load_players():
    client = await get_fpl_client()
    players = await client.get_players(
        return_json=True
    )

    return players