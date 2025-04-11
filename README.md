# pg-listener-py

Python service that publishes Postgres LISTEN/NOTIFY events to Pulsar.

See:
- [PostgreSQL NOTIFY](https://www.postgresql.org/docs/current/sql-notify.html)
- [PostgreSQL LISTEN](https://www.postgresql.org/docs/current/sql-listen.html)

## Prerequisites

* Python 3.10+
* Access to the meemoo PyPI (VPN required)

## Development and testing

1. Clone this repository and change into the new dir:

```bash
git clone git@github.com:viaacode/pg-listener-py.git
cd pg-listener-py
```

2. Init and activate a  virtual env:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install the library and the dev/test dependencies:

```bash
(.venv) python -m pip install . \
    --extra-index-url http://do-prd-mvn-01.do.viaa.be:8081/repository/pypi-all/simple \
    --trusted-host do-prd-mvn-01.do.viaa.be
```

## Usage

1. Fill in and export the environment variables in `.env`:

```bash
(.venv) export $(grep -v '^#' .env | xargs)
```

2. Run with:

```bash
(.venv) python main.py
```

3. Login to the configured database and test with:

```bash
db_name=> NOTIFY a_channel_name, 'a string payload';
```
