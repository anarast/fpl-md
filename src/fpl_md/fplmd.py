import asyncio
import json
import time
import logging
import os

from distutils.util import strtobool
from typing import Optional, Dict
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
cli_args: Optional[Dict] = None

team_handle_map = [
    {
        'id': 1415006,
        'handle': 'tarnasa',
    },
    {
        'id': 23366,
        'handle': 'torpy',
    },
    {
        'id': 7410,
        'handle': 'andante_nz',
    }
] 

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
        redis_conn.set(name=cid, value=json.dumps(raw_user), ex=300)
    else:
        raw_user = json.loads(raw_user)

    return User(raw_user, session=get_http_sess())


async def load_gw(gw_id, with_live: bool = True):
    client = await get_fpl_client()
    gw = await client.get_gameweek(gameweek_id=gw_id, include_live=with_live)
    return gw

def get_news(player_id: int, player, team_id: Optional[int] = None):
    if not team_id == None:
        # If team_id is passed in, cache the news against the player ID 
        # and the team ID so that we create a reply tweet for each FPL team
        cid = f"player_news:{player_id}:{team_id}"
    else:
        cid = f"player_news:{player_id}"

    old_news = redis_conn.get(cid)
    new_news = player['news']

    if (old_news != None):
        old_news = json.loads(old_news)
    
    if old_news == new_news:
        return {"text": old_news, "new": False}
    
    redis_conn.set(cid, json.dumps(new_news))

    logger.warning(f"Old news: {old_news} is obsolete")

    news_added = player['news_added']

    if (news_added is None):
        logger.warning("news_added is null")
        return {"text": new_news, "new": False}

    return {"text": new_news, "new": True}

async def load_players():
    client = await get_fpl_client()
    players = await client.get_players(
        return_json=True
    )

    return players

async def load_player(player_id: int, team_id: int):
    client = await get_fpl_client()
    player = await client.get_player(
        player_id=player_id,
        include_summary=True,
        return_json=True
    )

    news = get_news(player_id, player, team_id)

    return {"player": player, "news_text": news['text'], "new": news['new'] }

def tweet(
    api, 
    player,
    dry_run: Optional[bool] = False,
    team_handle: Optional[str] = None,
    team_name: Optional[str] = None
    ):
    player_name = player['web_name']
    news_added = player["news_added"]
    news = player['news']

    if len(news) == 0:
        news = "No news, player is now available"
    
    if team_handle == None:
        text = ""
    else:
        text = f"@{team_handle} Hi {team_name}, "
    
    text = text + f"{player_name}'s status has been updated: {news}. First updated at: {news_added}"
    
    logger.warning(text)

    if not dry_run:
        try:
            api.update_status(text)
        except Exception as e:
            logger.error("An exception occurred: " + str(e))
    else:
        logger.warning("Dry run is set to true, not sending tweet.")
    

async def fplmd(api, dry_run: bool):
    outer_sleep = 300
    inner_sleep = 60

    # All player notifications
    players = await load_players()
    for player in players:
        player_id = player['id']
        news = get_news(player_id, player)
        if news['new']:
            # Tweet the tweet
            tweet(
                api, 
                player,
                dry_run=dry_run
            )

    # Custom player notifications (replies)
    for team_handle in team_handle_map:
        team_id = team_handle['id']
        team = await load_team(team_id)
        gw = team.current_event
        picks = await get_picks(team, gw)

        for player in picks:
            player_id = player['element']
            player_details = await load_player(player_id, team_id)
            player = player_details["player"]
            news_is_new = player_details['new']
            time.sleep(inner_sleep)

            if news_is_new:
                # Tweet the tweet
                tweet(
                    api, 
                    player,
                    dry_run=dry_run,
                    team_name=team.player_first_name, 
                    team_handle=team_handle['handle'],
                )
            
        time.sleep(outer_sleep)

async def main():
    api = create_api()
    dry_run = strtobool(os.getenv("DRY_RUN"))
    logger.warning("Dry run: " + str(dry_run))
    while(True):
        try:
            await fplmd(api, dry_run)
        except Exception as e:
            logger.error("An exception occurred: " + str(e))
            session = get_http_sess()
            await session.close()
            break

asyncio.run(main())
