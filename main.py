# std
import argparse
import asyncio
import json
import logging as std_logging

# 3rd party
from psycopg import AsyncConnection, Error as PsycopgError, sql
import pulsar
from pulsar import Client as PulsarClient
from retry import retry

# meemoo internal
from cloudevents.events import (
    CEMessageMode,
    Event,
    EventAttributes,
    PulsarBinding,
)
from viaa.configuration import ConfigParser
from viaa.observability import logging

# initialize the config and the logger
config_parser = ConfigParser()
config = config_parser.app_cfg
log = logging.get_logger(__name__, config=config_parser)

APP_NAME = config["self"]["name"]


@retry(pulsar.ConnectError, tries=10, delay=1, backoff=2)
def get_pulsar_client():
    """Return a Pulsar client."""
    url = "pulsar://{host}:{port}/"
    url = url.format(**config["pulsar"])
    log.info(f"Connecting to Pulsar using service URL `{url}'")

    # pass a logger to avoid unformatted logging to stdout
    pulsar_logger = std_logging.getLogger("pulsar")
    pulsar_logger.setLevel(std_logging.CRITICAL)
    try:
        client = PulsarClient(service_url=url, logger=pulsar_logger)
        return client
    except Exception as e:
        error_message = f"failed to create Pulsar client: {e}"
        log.error(error_message, error=e)
        raise Exception(error_message)


@retry(pulsar.ConnectError, tries=10, delay=1, backoff=2)
def get_pulsar_producer(client):
    """Return a Pulsar producer."""
    topic = "persistent://public/{namespace}/{topic}".format(
        namespace=config["pulsar"]["namespace"],
        topic=config["pulsar"]["topic"],
    )
    log.info(f"Creating producer `{APP_NAME}' on topic `{topic}")
    producer = client.create_producer(
        topic=topic,
        producer_name=APP_NAME,
    )
    return producer


def send_pulsar_event(producer, notification):
    def get_cloudevent_data(notification):
        if data := notification.get("data"):
            return data
        else:
            message = "got a notification without data"
            log.error(message, pg_notification=notification)
            raise ValueError(message)

    def get_cloudevent_subject(notification):
        if essence_name := notification.get("essence_name"):
            return essence_name

        data = get_cloudevent_data(notification)
        if essence_id := data.get("essence_id"):
            return f"N/A ({str(essence_id)})"
        else:
            message = "got a notification without essence name or ID"
            log.error(message, pg_notification=notification)
            raise ValueError(message)

    data = get_cloudevent_data(notification)
    subject = get_cloudevent_subject(notification)
    if correlation_id := data.get("correlation_id"):
        del data["correlation_id"]
        attributes = EventAttributes(
            type=config["pulsar"]["topic"],
            source=APP_NAME,
            subject=subject,
            correlation_id=correlation_id,
        )
    else:
        log.warning(
            "`{name}' received a Postgres notification without correlation_id".format(
                name=producer.producer_name(),
            ),
            notification=notification,
        )
        attributes = EventAttributes(
            type=config["pulsar"]["topic"],
            source=APP_NAME,
            subject=subject,
        )

    event = Event(attributes, data)
    create_msg = PulsarBinding.to_protocol(event, CEMessageMode.STRUCTURED.value)

    message_id = producer.send(
        create_msg.data,
        properties=create_msg.attributes,
        event_timestamp=event.get_event_time_as_int(),
    )
    log.info(
        "`{name}' sent event with ID {id} to `{topic}'".format(
            name=producer.producer_name(),
            id=message_id,
            topic=producer.topic(),
        ),
        subject=subject,
    )


async def listen_forever(config, channel, producer):
    """
    Keep a Postgres LISTEN connection active, reconnecting when needed.

    If reconnecting doesn't work, just fail so we notice the failures in
    OpenShift.
    """
    (retry, max_retries) = (0, 5)
    sleep_seconds = 2
    listen = sql.SQL("LISTEN {channel}").format(channel=sql.Identifier(channel))
    while True:
        try:
            async with await AsyncConnection.connect(
                **config, autocommit=True
            ) as connection:
                retry = 0  # reset retry counter
                await connection.cursor().execute(listen)
                log.info(f"Started to LISTEN to `{channel}'")
                async for notify in connection.notifies():
                    try:
                        payload = json.loads(notify.payload)
                        log.info("Got a Postgres notification", notification=payload)
                        send_pulsar_event(producer, payload)
                    except Exception as e:
                        log.error(f"Failed to handle Postgres notification: {e}")
        except PsycopgError as e:
            if retry <= max_retries:
                s = sleep_seconds ** (retry := retry + 1)
                log.warning(f"{e}: sleeping for {s} second(s) (retry #{retry})")
                await asyncio.sleep(s)
            else:
                raise e


def main(args: argparse.Namespace):
    client = get_pulsar_client()
    producer = get_pulsar_producer(client)
    pg_config = config["db"]
    if pg_channel_name := args.channel_name:
        pg_config.pop("channel")
    else:
        pg_channel_name = pg_config.pop("channel")
    try:
        asyncio.run(listen_forever(pg_config, pg_channel_name, producer))
    except Exception as e:
        log.error(f"{e}: attempting to cleanly stop listening")
    finally:
        producer.close()
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Python service that publishes Postgres LISTEN/NOTIFY "
        "events to Pulsar.",
    )
    parser.add_argument(
        "-c",
        "--channel-name",
        nargs="?",
        type=str,
        help="Name of the channel to listen to.  If provided, overrides the "
        "configuration value.",
    )
    args = parser.parse_args()

    try:
        log.info(f"Starting `{APP_NAME}' main()")
        main(args)
    finally:
        log.info(f"Exiting `{APP_NAME}'")
