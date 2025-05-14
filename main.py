# std
import argparse
import asyncio
import json
import logging as std_logging

# 3rd party
from psycopg import connect as pg_connect, sql
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
            return str(essence_id)
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
        log.warn(
            f"Received a notification without a correlation_id",
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
    log.info(f"sent a Pulsar event with ID {message_id}", subject=subject)


def main(args: argparse.Namespace):
    client = get_pulsar_client()
    producer = get_pulsar_producer(client)

    pg_channel_name = args.channel_name or config["db"]["channel"]
    db_host = config["db"]["host"]

    log.info(f"Starting listener on channel `{pg_channel_name}' on host `{db_host}'.")

    conn = pg_connect(
        host=config["db"]["host"],
        dbname=config["db"]["name"],
        user=config["db"]["user"],
        password=config["db"]["password"],
    )

    cursor = conn.cursor()
    sql_statement = sql.SQL("LISTEN {channel}").format(
        channel=sql.Identifier(pg_channel_name)
    )
    cursor.execute(sql_statement)
    conn.commit()

    def handle_notify():
        try:
            for notify in conn.notifies(stop_after=0):
                payload = json.loads(notify.payload)
                log.debug("Got a Postgres notification", payload=payload)
                send_pulsar_event(producer, payload)

        except Exception as e:
            log.error(f"Error occurred while handling Postgres notification: {e}")
            raise

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.add_reader(conn, handle_notify)
    loop.run_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Python service that publishes Postgres LISTEN/NOTIFY events to Pulsar."  # noqa: E501
    )
    parser.add_argument(
        "-c",
        "--channel-name",
        nargs="?",
        type=str,
        help="Name of the channel to listen to. If provided, overrides the configuration value.",  # noqa: E501
    )
    args = parser.parse_args()

    try:
        log.info(f"Starting `{APP_NAME}' main()")
        main(args)
    finally:
        log.info(f"Exiting `{APP_NAME}'")
