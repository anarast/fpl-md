import asyncio
import time
import logging
import os

import redis

from datetime import datetime
from distutils.util import strtobool
from typing import Optional, Dict
from dotenv import load_dotenv

from .api import create_api
from .db import db_connect
from .utils import get_http_sess, get_picks, load_team, load_players

load_dotenv()
redis_conn = redis.Redis(host=os.getenv("REDIS_HOST"), port=6379)
db_conn = db_connect()

logger = logging.getLogger()
logging.basicConfig(level=logging.INFO)

def update_news(player_id: int, player: Dict, team_id: Optional[int] = None) -> bool:
    ''' Updates the news and returns true if the news is new, returns false if the news is not new'''
    select_cur = db_conn.cursor()

    if team_id == None:
        select_query = f"SELECT id, news FROM player_news where player_id=:player_id and team_id is null"
        select_cur.execute(select_query, { "player_id": player_id })
    else:
        select_query = f"SELECT id, news FROM player_news where player_id=:player_id and team_id=:team_id"
        select_cur.execute(select_query, { "player_id": player_id, "team_id": team_id })
    
    existing_player_news = select_cur.fetchone();
    new_news = player['news']
    news_added = player['news_added']

    if existing_player_news is None:
        insert_cur = db_conn.cursor()
        insert_query = "insert into player_news (player_id, news, team_id) values(:player_id, :news, :team_id)"
        insert_cur.execute(insert_query, {"player_id": player_id, "news": new_news, "team_id": team_id })
        db_conn.commit()

        return False

    old_news = existing_player_news['news']
    
    if old_news == new_news:
        return False
    
    update_query = f"update player_news set news=:news where id=:id"
    update_cur = db_conn.cursor()
    update_cur.execute(update_query, {"id": existing_player_news['id'], "news": new_news})
    db_conn.commit()

    logger.info(f"Old news: {old_news} is obsolete")

    if news_added is None:
        return False

    return True


def tweet_player_status(
    api, 
    player_name: str,
    news: str,
    news_added: str,
    dry_run: Optional[bool] = False,
    team_handle: Optional[str] = None,
    ):
    if len(news) == 0:
        news = "No news, player is now available"
    
    if team_handle == None:
        text = ""
    else:
        text = f"@{team_handle} "
    
    text = text + f"{player_name}'s status has been updated: {news}. First updated at: {news_added}"
    
    logger.warning("Tweeting: " + text)

    tweet(api, text, dry_run)

def tweet(api, text: str, dry_run: bool, mention_id: Optional[int] = None):
    if not dry_run:
        try:
            logger.info(text)
            # The tweets have to be unique or Twitter throws an error.
            current_time = datetime.now()
            api.update_status(text + f" Timestamp: {current_time}", mention_id)
        except Exception as e:
            logger.error("An exception occurred: " + str(e))
    else:
        logger.warning("Dry run is set to true, not sending tweet.")


def is_subscribed(handle: str):
    exists_cur = db_conn.cursor()
    exists_query = "select id from subscriptions where handle=:handle and subscribed=:subscribed"

    subscription_exists = exists_cur.execute(exists_query, {"handle": handle, "subscribed": 1})
    subscription = subscription_exists.fetchone()

    if subscription is None:
        return None

    return subscription['id']
    

async def validate_mention(mention_text: str) -> Dict: 
    split_mention = mention_text.split()

    if split_mention[1] is None or not split_mention[1].isnumeric():
        return None

    team_id = split_mention[1]
    team = await load_team(int(team_id))

    if team is None:
        return None

    return { 
        'team_name': team.name, 
        'team_id': team_id
        }

def add_subscription(api, mention, subscribed_team_id: str, team_name: str, dry_run):
    handle = mention.user.screen_name
    mention_id = mention.id

    if is_subscribed(handle) == None:
        logger.info(f"Adding subscription for {handle}")
        insert_cur = db_conn.cursor()
        insert_query = "insert into subscriptions (subscribed, handle, team_id, mention_id) values(:subscribed, :handle, :team_id, :mention_id)"
        insert_cur.execute(insert_query, {"subscribed": 1, "handle": handle, "team_id": subscribed_team_id, "mention_id": mention_id})
        db_conn.commit()
        
        text = f"@{handle} You've been subscribed to updates for the FPL team '{team_name}'. If you would like to unsubscribe, reply with the text 'Stop'."

        tweet(api, text, dry_run, mention_id)

def remove_subscription(api, mention, dry_run: Optional[bool] = False):
    handle = mention.user.screen_name
    mention_id = mention.id
    subscription_id = is_subscribed(handle)

    logger.info(f"Removing subscription for {handle}")

    # If the subscription exists and subscribed is set to 'true', 
    # update the subscribed column to 'false'
    if subscription_id != None:
        update_cur = db_conn.cursor()
        update_query = "update subscriptions set subscribed=:subscribed, mention_id=:mention_id where id=:id"
        update_cur.execute(update_query, { "id": subscription_id, "subscribed": 0, "mention_id": mention_id })
        db_conn.commit()

        text = f"@{handle} You've been unsubscribed from player updates."

        tweet(api, text, dry_run, mention_id)
    

async def check_subscriptions(api, dry_run: Optional[bool] = False):
    logger.info(f"Checking subscriptions")
    # Only get mentions that are more recent than the most recent mention_id
    # in the subscriptions table, so that we don't handle the same mentions
    # multiple times.
    select_cur = db_conn.cursor()
    query = "select mention_id from subscriptions order by mention_id desc"
    latest_mention = select_cur.execute(query).fetchone()

    if latest_mention is None:
        latest_mention_id = None
    else:
        latest_mention_id = latest_mention["mention_id"] + 1

    mentions = api.mentions_timeline(latest_mention_id)

    for mention in mentions:
        mention_text = (mention.text.strip()).lower()
        if "stop" in mention_text:
            remove_subscription(api, mention, dry_run)
        
        team_data = await validate_mention(mention.text)
        if not team_data == None:
            add_subscription(api, mention, team_data['team_id'], team_data['team_name'], dry_run)

async def fplmd(api, dry_run: bool):
    # All player notifications
    logger.info("Handling all player notifications")
    players = await load_players()
    player_news_map = {}
    for player in players:
        # Build up a map of player IDs and news so that we
        # don't have to call the API again for the picks below
        player_id = player['id']
        player_data = {
            'news': player['news'],
            'news_added': player['news_added'],
            'web_name': player['web_name'],
        }
        player_news_map[player_id] = player_data
        news_is_new = update_news(player_id, player_data)
        if news_is_new:
            # Tweet the tweet
            tweet_player_status(
                api, 
                player['web_name'],
                player['news'],
                player['news_added'],
                dry_run=dry_run
            )

    # Custom player notifications (replies)
    # Get all subscriptions where subscribed = 1
    select_cur = db_conn.cursor()
    query = f"SELECT handle, team_id FROM subscriptions where subscribed=:subscribed"
    select_cur.execute(query, {"subscribed": 1})
    subscriptions = select_cur.fetchall()

    logger.info("Handling subscription notifications")

    for subscription in subscriptions:
        team_id = subscription['team_id']
        handle = subscription['handle']
        team = await load_team(team_id)
        gw = team.current_event
        picks = await get_picks(team, gw)

        for pick in picks:
            player_id = pick['element']
            player_data = player_news_map[player_id]
            news_is_new = update_news(player_id, player_data, team_id)

            if news_is_new:
                # Tweet the tweet
                tweet_player_status(
                    api, 
                    player_data['web_name'],
                    player_data['news'],
                    player_data['news_added'],
                    dry_run=dry_run,
                    team_handle=handle,
                )


async def main():
    api = create_api()
    dry_run = strtobool(os.getenv("DRY_RUN"))
    logger.warning("Dry run: " + str(dry_run))
    sleep = 240
    while(True):
        try:
            await check_subscriptions(api, dry_run)
            await fplmd(api, dry_run)
            logger.warning(f"Sleeping for: {str(sleep)} seconds...")
            time.sleep(sleep)
        except Exception as e:
            logger.error("An exception occurred: " + str(e))
            session = get_http_sess()
            await session.close()
            break

asyncio.run(main())
