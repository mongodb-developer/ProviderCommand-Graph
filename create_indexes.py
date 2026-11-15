"""Create the app5.py indexes, including Voyage autoEmbed, without importing Streamlit.

Default: print a read-only plan. --apply creates only missing resources.
Existing incompatible search definitions are reported, never overwritten.
"""
from pymongo.errors import CollectionInvalid
from pymongo.operations import SearchIndexModel

if __package__:
    from ._common import SupportError, database, output, parser, run
    from .demo_config import (COLLECTIONS, EMBEDDING_MODEL, METRICS_COLLECTION,
                             REGULAR_INDEXES, VECTOR_INDEXES)
    from .time_series import ensure_timeseries_collection
else:
    from _common import SupportError, database, output, parser, run
    from demo_config import (COLLECTIONS, EMBEDDING_MODEL, METRICS_COLLECTION,
                             REGULAR_INDEXES, VECTOR_INDEXES)
    from time_series import ensure_timeseries_collection


def auto_embedding_definition(model=EMBEDDING_MODEL):
    """Same autoEmbed field configuration used by app5.py."""
    return {'fields': [{'type': 'autoEmbed', 'modality': 'text',
                        'path': 'searchText', 'model': model}]}


def matching_embedding_definition(index):
    definition = index.get('latestDefinition') or index.get('definition')
    if definition is None:
        return None
    return any(all(field.get(key) == expected for key, expected in
                   auto_embedding_definition()['fields'][0].items())
               for field in definition.get('fields', []) if isinstance(field, dict))


def plan_indexes(db):
    """Read-only inspection. Validate collection type before allowing any writes."""
    present = set(db.list_collection_names())
    ensure_timeseries_collection(db, apply=False)
    plan = {'createCollections': [name for name in COLLECTIONS if name not in present],
            'createRegularIndexes': [], 'createVectorIndexes': [],
            'existingVectorIndexes': [], 'warnings': []}
    for name, key_patterns in REGULAR_INDEXES.items():
        existing = list(db[name].list_indexes()) if name in present else []
        for keys in key_patterns:
            equivalent = any(tuple(item.get('key', {}).items()) == keys
                             and not item.get('sparse') and not item.get('partialFilterExpression')
                             for item in existing)
            if not equivalent:
                # Avoid an index-name conflict with a sparse/partial index.
                default_name = '_'.join(f'{field}_{direction}' for field, direction in keys)
                if any(item.get('name') == default_name for item in existing):
                    raise SupportError('An existing regular index has incompatible options; inspect it in Atlas before setup.')
                plan['createRegularIndexes'].append({'collection': name, 'keys': list(keys)})
    for collection, name in VECTOR_INDEXES:
        indexes = list(db[collection].list_search_indexes()) if collection in present else []
        found = next((item for item in indexes if item.get('name') == name), None)
        if found is None:
            plan['createVectorIndexes'].append({'collection': collection, 'name': name,
                                                'type': 'vectorSearch',
                                                'definition': auto_embedding_definition()})
        else:
            match = matching_embedding_definition(found)
            if match is False or found.get('type', 'vectorSearch') != 'vectorSearch':
                raise SupportError('A named vector index has an incompatible definition; no indexes were changed. Inspect it in Atlas.')
            if match is None:
                plan['warnings'].append(f'Could not inspect the definition of {name}; verify autoEmbed manually in Atlas.')
            plan['existingVectorIndexes'].append({
                'collection': collection, 'name': name,
                'status': found.get('status', 'UNKNOWN'),
                'queryable': found.get('queryable', False),
                'definitionVerified': match is True})
    return plan


def apply_plan(db, plan):
    """Create native time series first so a regular index cannot create the wrong type."""
    actions = [ensure_timeseries_collection(db, apply=True)]
    for name in plan['createCollections']:
        if name == METRICS_COLLECTION:
            continue
        try:
            db.create_collection(name)
            actions.append({'collection': name, 'action': 'created'})
        except CollectionInvalid:
            actions.append({'collection': name, 'action': 'already exists'})
    for item in plan['createRegularIndexes']:
        name = db[item['collection']].create_index(item['keys'])
        actions.append({'collection': item['collection'], 'index': name, 'action': 'created'})
    for item in plan['createVectorIndexes']:
        db[item['collection']].create_search_index(SearchIndexModel(
            name=item['name'], type='vectorSearch', definition=item['definition']))
        actions.append({'collection': item['collection'], 'index': item['name'],
                        'action': 'asynchronous build requested'})
    return actions


def indexes_ready(plan):
    return (not plan['createCollections'] and not plan['createRegularIndexes']
            and not plan['createVectorIndexes'] and not plan['warnings']
            and all(index['queryable'] and index['status'] == 'READY'
                    for index in plan['existingVectorIndexes']))


def main():
    cli = parser(__doc__)
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Create missing collections and indexes.')
    mode.add_argument('--check', action='store_true', help='Read-only readiness check; exit 1 if any resource is missing or not ready.')
    args = cli.parse_args()
    with database(args) as db:
        plan = plan_indexes(db)
        if args.apply:
            actions = apply_plan(db, plan)
            output({'database': args.database, 'actions': actions,
                    'note': 'No documents seeded. Vector indexes build asynchronously; run again with --check.'})
        else:
            output({'database': args.database, 'mode': 'check' if args.check else 'dry run',
                    'ready': indexes_ready(plan), 'plan': plan})
            if args.check and not indexes_ready(plan):
                return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(run(main))
