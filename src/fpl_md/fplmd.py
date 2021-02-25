import asyncio
import json
import time
import logging
import os

from typing import Optional
from .api import create_api

import aiohttp
import redis
from fpl import FPL
from fpl.models import User
from dotenv import load_dotenv

load_dotenv()
redis_conn = redis.Redis(host=os.getenv("REDIS_HOST"), port=6379)
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

def get_news(player_id: int, player, team_id: int):
    cid = f"player_news:{player_id}:{team_id}"

    old_news = redis_conn.get(cid)
    new_news = player['news']

    if (old_news is None):
        redis_conn.set(cid, json.dumps(""))
        return {"text": "", "new": False}

    old_news = json.loads(old_news)
    if old_news == new_news:
        return {"text": old_news, "new": False}
    
    redis_conn.set(cid, json.dumps(new_news))

    logger.info(f"Old news: {old_news} is obsolete")

    return {"text": new_news, "new": True}
    

async def load_player(player_id: int, team_id: int):
    client = await get_fpl_client()
    player = await client.get_player(
        player_id=player_id,
        include_summary=True,
        return_json=True
    )

    news = get_news(player_id, player, team_id)

    print(str(news))
    
    return {"player": player, "news_text": news['text'], "new": news['new'] }

def tweet(api, team_name: str, player_name: str, news: str, chance_of_playing: int, news_added: str):
    text = f"Hi {team_name}, {player_name}'s status has been updated: {news}."

    if chance_of_playing != None:
        text = text + f" Their chance of playing this round is estimated at {str(chance_of_playing)}%."

    text = text + f" Updated at: {news_added}"

    print(text)
    logger.info(text)
    try:
        api.update_status(text)
    except Exception as e:
        print("An exception occurred: " + str(e))
        logger.error("An exception occurred: " + str(e))

async def fplmd(api):
    outer_sleep = 60
    inner_sleep = 10
    team_ids = [1415006, 7410, 5615599, 2005835, 23366, 620397]

    for team_id in team_ids:
        team = await load_team(team_id)
        print(team)
        picks = await get_picks(team)

        for player in picks:
            player_id = player['element']
            player_details = await load_player(player_id, team_id)
            player = player_details["player"]
            news_is_new = player_details['new']
            news = player_details['news_text']
            print("news is new: " + str(news_is_new))
            print(f"Sleeping for {inner_sleep} seconds...")
            time.sleep(inner_sleep)

            if news_is_new:
                chance_of_playing = player['chance_of_playing_this_round']
                player_name = f"{player['first_name']} {player['second_name']}"
                news_added = player["news_added"]
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
                    chance_of_playing=chance_of_playing,
                    news_added=news_added
                )
            
        print(f"Sleeping for {outer_sleep} seconds...")
        time.sleep(outer_sleep)


async def main():
    api = create_api()
    while(True):
        try:
            await fplmd(api)
        except Exception as e:
            print("An exception occurred: " + str(e))
            logger.error("An exception occurred: " + str(e))
            session = get_http_sess()
            await session.close()
            break

asyncio.run(main())
