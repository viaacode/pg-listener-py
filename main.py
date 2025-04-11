# Std
import os
import asyncio
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


def main():
    log.info(f'Starting listener on channel {config["db"]["channel"]}')
    conn = psycopg.connect(
        host=config["db"]["host"],
        dbname=config["db"]["name"],
        user=config["db"]["user"],
        password=config["db"]["passwd"]
    )

    cursor = conn.cursor()
    cursor.execute(f'LISTEN {config["db"]["channel"]};')
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
    try:
        log.info(f'Starting')
        main()
    finally:
        log.info('Exiting')
