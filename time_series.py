"""Native hospital time series setup and the daily aggregation extracted from app5.py."""
from pymongo.errors import CollectionInvalid
if __package__:
    from ._common import SupportError, database, output, parser, run
    from .demo_config import DEMO_SOURCE, METRICS_COLLECTION
else:
    from _common import SupportError, database, output, parser, run
    from demo_config import DEMO_SOURCE, METRICS_COLLECTION


def ensure_timeseries_collection(db, apply=False):
    """Never implicitly create a regular collection under the measurement name."""
    if METRICS_COLLECTION in db.list_collection_names():
        options = db[METRICS_COLLECTION].options().get('timeseries', {})
        if options.get('timeField') != 'timestamp' or options.get('metaField') != 'metadata':
            raise SupportError('hospital_metrics exists with incompatible collection options; no changes made.')
        return {'collection': METRICS_COLLECTION, 'action': 'already exists', 'nativeTimeSeries': True}
    if apply:
        try:
            db.create_collection(METRICS_COLLECTION, timeseries={
                'timeField': 'timestamp', 'metaField': 'metadata', 'granularity': 'hours'})
        except CollectionInvalid:
            # Another operator may have created the collection after our read.
            return ensure_timeseries_collection(db, apply=False)
    return {'collection': METRICS_COLLECTION, 'action': 'created' if apply else 'would create',
            'nativeTimeSeries': True}


# metrics_pipeline(days) below is extracted unchanged from app5.py.

def metrics_pipeline(days):
    from datetime import datetime, timedelta, timezone
    return [
        {"$match": {"metadata.demoSource": DEMO_SOURCE,
                    "timestamp": {"$gte": datetime.now(timezone.utc) - timedelta(days=days)}}},
        {"$group": {"_id": {"hospitalId": "$metadata.hospitalId", "day": {
            "$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp", "timezone": "America/Chicago"}}},
                    "occupancyPct": {"$avg": "$occupancyPct"},
                    "edWaitMinutes": {"$avg": "$edWaitMinutes"},
                    "arrivals": {"$sum": "$arrivals"}, "samples": {"$sum": 1}}},
        {"$sort": {"_id.day": 1}},
        {"$project": {"_id": 0, "hospitalId": "$_id.hospitalId", "day": "$_id.day",
                      "occupancyPct": 1, "edWaitMinutes": 1, "arrivals": 1, "samples": 1}}]

def main():
    cli = parser(__doc__)
    cli.add_argument('--days', type=int, choices=(7, 14, 30), default=30)
    cli.add_argument('--setup', action='store_true', help='Check or create the native time series collection.')
    cli.add_argument('--apply', action='store_true', help='Create the collection with --setup; otherwise no writes.')
    cli.add_argument('--explain', action='store_true', help='Print the aggregation without connecting.')
    args = cli.parse_args()
    if args.apply and not args.setup:
        cli.error('--apply requires --setup.')
    if args.explain and (args.setup or args.apply):
        cli.error('--explain cannot be combined with --setup or --apply.')
    if args.explain:
        output(metrics_pipeline(args.days))
        return 0
    with database(args) as db:
        if args.setup:
            output(ensure_timeseries_collection(db, apply=args.apply))
        else:
            result = ensure_timeseries_collection(db)
            if result['action'] == 'would create':
                raise SupportError('Time series collection missing. Seed the app or run with --setup --apply.')
            rows = list(db[METRICS_COLLECTION].aggregate(metrics_pipeline(args.days), maxTimeMS=args.timeout_ms))
            output({'days': args.days, 'rows': rows,
                    'note': 'Only ontology-graph-v4 synthetic measurements; no seed data is inserted by this script.'})


if __name__ == '__main__':
    raise SystemExit(run(main))
