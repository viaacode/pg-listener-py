# Std
import os
import asyncio
import argparse
# 3d Party
import psycopg
# meemoo
# internal
from cloudevents.events import (
    CEMessageMode,
    Event,
    EventAttributes,
    EventOutcome,
    PulsarBinding,
)
from viaa.configuration import ConfigParser
from viaa.observability import logging

APP_NAME = "pg-listener-py"

# Init the config and the logger
config_parser = ConfigParser()
config = config_parser.app_cfg
log = logging.get_logger(__name__, config=config_parser)


def main(args: argparse.Namespace):
    pg_channel_name = args.channel_name or config["db"]["channel"]

    log.info(f'Starting listener on channel {pg_channel_name}')

    conn = psycopg.connect(
        host=config["db"]["host"],
        dbname=config["db"]["name"],
        user=config["db"]["user"],
        password=config["db"]["passwd"]
    )

    cursor = conn.cursor()
    cursor.execute(f'LISTEN {pg_channel_name};')
    conn.commit()

    def handle_notify():
        try:
            for notify in conn.notifies(stop_after=0):
                print(notify.payload)
        except:
            log.error('Error occurred')
            raise

    loop = asyncio.get_event_loop()
    loop.add_reader(conn, handle_notify)
    loop.run_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Python service that publishes Postgres LISTEN/NOTIFY events to Pulsar.")
    parser.add_argument(
        '-c',
        '--channel-name',
        nargs='?',
        type=str,
        help="Name of the channel to listen to. If provided, overrides the configuration value."
    )
    args = parser.parse_args()

    try:
        log.info(f'Starting')
        main(args)
    finally:
        log.info('Exiting')
