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
from .fpl_utils import get_http_sess, get_picks, load_team, load_players
from .db_utils import db_select_one, db_write, db_select_all

load_dotenv()
redis_conn = redis.Redis(host=os.getenv("REDIS_HOST"), port=6379)

logger = logging.getLogger()
# logging.basicConfig(level=logging.INFO)

def update_news(player_id: int, player: Dict, team_id: Optional[int] = None) -> bool:
    ''' Updates the news and returns true if the news is new, returns false if the news is not new'''
    if team_id == None:
        select_query = f"SELECT id, news FROM player_news where player_id=:player_id and team_id is null"
        select_params = { "player_id": player_id }
    else:
        select_query = f"SELECT id, news FROM player_news where player_id=:player_id and team_id=:team_id"
        select_params = { "player_id": player_id, "team_id": team_id }
        
    existing_player_news = db_select_one(query=select_query, params=select_params)
    new_news = player['news']
    news_added = player['news_added']

    if existing_player_news is None:
        insert_query = "insert into player_news (player_id, news, team_id) \
            values(:player_id, :news, :team_id)"
        insert_params = { "player_id": player_id, "news": new_news, "team_id": team_id }
        db_write(query=insert_query, params=insert_params)

        return False

    old_news = existing_player_news['news']

    if old_news == new_news:
        return False
    
    update_query = f"update player_news set news=:news where id=:id"
    update_params = { "id": existing_player_news['id'], "news": new_news }
    db_write(query=update_query, params=update_params)

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
    team_handle: Optional[str] = None
    ):
    if len(news) == 0:
        news = "Player is now available"
    
    if team_handle == None:
        text = ""
    else:
        text = f"@{team_handle} "
    
    text = text + f"{player_name}'s status has been updated: {news}. First updated at: {news_added}"
    
    # We don't need to add the timestamp because we've already added one above which should make
    # the tweet unique.
    tweet(api=api, text=text, dry_run=dry_run, add_timestamp=False)

def tweet(
    api, 
    text: str, 
    dry_run: bool, 
    add_timestamp: bool,
    mention_id: Optional[int] = None
    ):
    logger.info(text)

    if not dry_run:
        try:
            # The tweets have to be unique or Twitter throws an error.
            if add_timestamp:
                current_time = datetime.now()
                text = text + f" Timestamp: {current_time}"
            
            api.update_status(text, mention_id)
        except Exception as e:
            logger.error("An exception occurred: " + str(e))
    else:
        logger.warning("Dry run is set to true, not sending tweet.")


def is_subscribed(handle: str):
    exists_query = "select id from subscriptions where handle=:handle and subscribed=:subscribed"
    params = { "handle": handle, "subscribed": 1 }

    subscription = db_select_one(query=exists_query, params=params)

    if subscription is None:
        return None
    
    logger.info("Is subscribed:")
    logger.info(subscription)

    return subscription['id']
    

async def validate_mention(mention_text: str) -> Dict: 
    split_mention = mention_text.split()

    if split_mention[1] is None or not split_mention[1].isnumeric():
        return None

    team_id = split_mention[1]
    team = await load_team(int(team_id))

    if team is None:
        return None

    return { 'team_name': team.name, 'team_id': team_id }

def add_subscription(api, mention, subscribed_team_id: str, team_name: str, dry_run: bool):
    handle = mention.user.screen_name
    mention_id = mention.id

    if is_subscribed(handle) == None:
        logger.info(f"Adding subscription for {handle}")
        insert_query = "insert into subscriptions (subscribed, handle, team_id, mention_id) \
            values(:subscribed, :handle, :team_id, :mention_id)"
        insert_params = {
                "subscribed": 1, 
                "handle": handle, 
                "team_id": subscribed_team_id, 
                "mention_id": mention_id
                }
        db_write(query=insert_query, params=insert_params)
        
        text = f"@{handle} You've been subscribed to player updates for the FPL team '{team_name}'. \
            If you would like to unsubscribe, reply to this tweet with the text 'Stop'."

        tweet(api=api, text=text, dry_run=dry_run, add_timestamp=True, mention_id=mention_id)

def remove_subscription(api, mention, dry_run: Optional[bool] = False):
    handle = mention.user.screen_name
    mention_id = mention.id
    subscription_id = is_subscribed(handle)

    logger.info(f"Removing subscription for {handle}")

    # If the subscription exists and subscribed is set to 'true', 
    # update the subscribed column to 'false'
    if subscription_id != None:
        update_query = "update subscriptions set subscribed=:subscribed, mention_id=:mention_id where id=:id"
        update_params = { 
                "id": subscription_id, 
                "subscribed": 0, 
                "mention_id": mention_id 
                }

        db_write(query=update_query, params=update_params)

        text = f"@{handle} You've been unsubscribed from player updates."

        tweet(api=api, text=text, dry_run=dry_run, add_timestamp=True, mention_id=mention_id)
    

async def check_subscriptions(api, dry_run: Optional[bool] = False):
    logger.debug(f"Checking subscriptions")
    # Only get mentions that are more recent than the most recent mention_id
    # in the subscriptions table, so that we don't handle the same mentions
    # multiple times.
    query = "select mention_id from subscriptions order by mention_id desc"
    latest_mention = db_select_one(query=query)

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
    logger.debug("Handling all player notifications")
    # Get all the players from the FPL API
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
    query = f"SELECT handle, team_id FROM subscriptions where subscribed=:subscribed"
    subscriptions = db_select_all(query=query, params={"subscribed": 1})

    logger.debug("Handling subscription notifications")

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
    sleep = 60
    while(True):
        try:
            await check_subscriptions(api, dry_run)
            await fplmd(api, dry_run)
            logger.info(f"Sleeping for: {str(sleep)} seconds...")
            time.sleep(sleep)
        except Exception as e:
            logger.error("An exception occurred: " + str(e))
            session = get_http_sess()
            await session.close()
            break

asyncio.run(main())
