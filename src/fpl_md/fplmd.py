import asyncio
import json
import time
import logging

from typing import Optional
from .api import create_api

import aiohttp
import redis
from fpl import FPL
from fpl.models import User

redis_conn = redis.Redis(host='redis-service', port=6379)
# redis_conn = redis.Redis(host='localhost', port=6379)
http_sess: Optional[aiohttp.ClientSession] = None
fpl_client: Optional[FPL] = None
logger = logging.getLogger()

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
        redis_conn.set(name=cid, value=raw_picks, ex=300)

    picks = json.loads(raw_picks)
        
    return picks[str(gw)]


async def load_team(team_id: int):
    cid = f"team:{team_id}"
    raw_user = redis_conn.get(cid)
    if raw_user is None:
        client = await get_fpl_client()
        raw_user = await client.get_user(team_id, return_json=True)
        redis_conn.set(cid, json.dumps(raw_user))
    else:
        raw_user = json.loads(raw_user)

    return User(raw_user, session=get_http_sess())


async def load_gw(gw_id, with_live: bool = True):
    client = await get_fpl_client()
    gw = await client.get_gameweek(gameweek_id=gw_id, include_live=with_live)
    return gw


async def load_player(player_id: int):
    client = await get_fpl_client()
    player = await client.get_player(
        player_id=player_id,
        include_summary=True,
        return_json=True
    )
    # Cache the player 'news' so we can tell when it's been updated.
    cid = f"player_news:{player_id}"
    redis_conn.set(cid, json.dumps(player['news']))

    return player

def news_is_new(player_id: int, news: str) -> bool:
    cid = f"player_news:{player_id}"

    old_news = redis_conn.get(cid)

    if (old_news is None):
        return True

    return json.loads(old_news) != news

def tweet(api, team_name: str, player_name: str, news: str, chance_of_playing: int):
    text = f"Hi {team_name}, {player_name}'s status has been updated: {news}. "

    if chance_of_playing != None:
        text = text + f"Their chance of playing this round is estimated at {str(chance_of_playing)}%."

    print(text)
    logger.info(text)
    api.update_status(text)

async def fplmd(api):
    sleep = 3
    team_ids = [5615599, 2005835, 7410, 1415006, 23366]

    for team_id in team_ids:
        team = await load_team(team_id)
        print(team)
        picks = await get_picks(team)

        for player in picks:
            player_id = player['element']
            player_details = await load_player(player_id)
            news = player_details['news']

            if news_is_new(player_id=player_id, news=news):
                chance_of_playing = player_details['chance_of_playing_this_round']
                player_name = f"{player_details['first_name']} {player_details['second_name']}"
                print(f"News: {news}")
                print(f"Player: {player_name}")
                print(f"Chance of playing this round: {str(chance_of_playing)}")

                if len(news) == 0:
                    news = "No news, player is available"

                # Tweet the tweet
                tweet(
                    api, 
                    team_name=team.player_first_name, 
                    player_name=player_name, 
                    news=news, 
                    chance_of_playing=chance_of_playing
                )
                print(f"Sleeping for 20 seconds...")
                time.sleep(20)
            
        print(f"Sleeping for {sleep} seconds...")
        time.sleep(sleep)

    session = get_http_sess()
    await session.close()

def main():
    api = create_api()

    while True:
        asyncio.run(fplmd(api))

    
if __name__ == '__main__':
    main()
