"""CLI plumbing only: masked credentials, bounded requests, JSON and safe errors."""
import argparse
from contextlib import contextmanager
from getpass import getpass
import json
import sys

from bson import json_util
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError

if __package__:
    from .demo_config import DATABASE_NAME
else:
    from demo_config import DATABASE_NAME


class SupportError(ValueError):
    """Safe, fixed application validation message."""


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument('--database', default=DATABASE_NAME,
                        help='Database name (default: %(default)s).')
    result.add_argument('--timeout-ms', type=int, default=10000,
                        help='Connection and server operation timeout in milliseconds.')
    return result


def output(value):
    print(json.dumps(value, default=json_util.default, indent=2))


@contextmanager
def database(args):
    if not 1000 <= args.timeout_ms <= 60000:
        raise SupportError('--timeout-ms must be between 1000 and 60000.')
    if not sys.stdin.isatty():
        raise SupportError('Run from an interactive terminal so the URI can be entered without echo.')
    uri = getpass('Atlas connection string (hidden): ').strip()
    if not uri.startswith(('mongodb://', 'mongodb+srv://')):
        raise SupportError('Connection string must start with mongodb:// or mongodb+srv://.')
    client = None
    try:
        client = MongoClient(uri, appname='providercommand-support',
                             serverSelectionTimeoutMS=args.timeout_ms,
                             connectTimeoutMS=args.timeout_ms,
                             socketTimeoutMS=args.timeout_ms, tz_aware=True)
        uri = ''
        client.admin.command('ping')
        yield client[args.database]
    finally:
        uri = ''
        if client is not None:
            client.close()


def run(main):
    """Return actionable error categories without echoing driver connection details."""
    try:
        code = main()
        return int(code or 0)
    except KeyboardInterrupt:
        print('Cancelled.', file=sys.stderr)
        return 130
    except EOFError:
        print('No connection string entered.', file=sys.stderr)
        return 2
    except SupportError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, TypeError):
        print('Invalid connection configuration. Check the URI and database name.', file=sys.stderr)
        return 2
    except ConnectionFailure:
        print('Connection failed. Check Atlas network access and connectivity.', file=sys.stderr)
        return 2
    except OperationFailure as exc:
        if exc.code == 18:
            message = 'Authentication failed. Check the database credentials.'
        elif exc.code == 13:
            message = 'Permission denied. Check collection and index permissions.'
        else:
            message = 'Database operation failed. Check feature availability and permissions in Atlas.'
        print(message, file=sys.stderr)
        return 2
    except PyMongoError:
        print('MongoDB request failed. Check the URI, deployment capabilities, and connection.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    print('Import this helper from the other support scripts.')
