"""Provider, ontology and architecture graph pipelines extracted from app5.py."""
if __package__:
    from ._common import database, output, parser, run
    from .demo_config import GRAPH_COLLECTION, ONTOLOGY_COLLECTION, ARCHITECTURE_COLLECTION
else:
    from _common import database, output, parser, run
    from demo_config import GRAPH_COLLECTION, ONTOLOGY_COLLECTION, ARCHITECTURE_COLLECTION


def connected_graph_pipeline(root_id, hops):
    return [{"$match": {"_id": root_id}}, {"$graphLookup": {
        "from": GRAPH_COLLECTION, "startWith": "$neighbors",
        "connectFromField": "neighbors", "connectToField": "_id",
        "as": "connected", "maxDepth": hops - 1, "depthField": "hopDepth"}}]

def ancestor_pipeline(concept_id):
    return [
        {
            "$match": {
                "_id": concept_id,
            }
        },
        {
            "$graphLookup": {
                "from": ONTOLOGY_COLLECTION,
                "startWith": "$parentId",
                "connectFromField": "parentId",
                "connectToField": "_id",
                "as": "ancestors",
                "depthField": "traversalDepth",
            }
        },
        {
            "$project": {
                "_id": 1,
                "code": 1,
                "name": 1,
                "conceptType": 1,
                "parentId": 1,
                "description": 1,
                "synonyms": 1,
                "ancestors": 1,
            }
        },
    ]

def descendant_pipeline(concept_id):
    return [
        {
            "$match": {
                "_id": concept_id,
            }
        },
        {
            "$graphLookup": {
                "from": ONTOLOGY_COLLECTION,
                "startWith": "$_id",
                "connectFromField": "_id",
                "connectToField": "parentId",
                "as": "descendants",
                "depthField": "traversalDepth",
            }
        },
    ]

def architecture_graph_pipeline(node_ids):
    return [
        {
            "$match": {
                "_id": {
                    "$in": node_ids,
                }
            }
        },
        {
            "$graphLookup": {
                "from": ARCHITECTURE_COLLECTION,
                "startWith": "$_id",
                "connectFromField": "_id",
                "connectToField": "dependsOn",
                "as": "downstream",
                "depthField": "impactDepth",
            }
        },
        {
            "$graphLookup": {
                "from": ARCHITECTURE_COLLECTION,
                "startWith": "$dependsOn",
                "connectFromField": "dependsOn",
                "connectToField": "_id",
                "as": "upstream",
                "depthField": "dependencyDepth",
            }
        },
    ]

def main():
    cli = parser(__doc__)
    cli.add_argument('--kind', choices=('provider', 'ancestors', 'descendants', 'architecture'), default='provider')
    cli.add_argument('--node', action='append', help='Starting ID. Repeat only for architecture queries.')
    cli.add_argument('--hops', type=int, choices=range(1, 5), default=2)
    cli.add_argument('--explain', action='store_true', help='Print the pipeline without connecting.')
    args = cli.parse_args()
    ids = args.node or (['provider-1001'] if args.kind == 'provider' else None)
    if not ids:
        cli.error('--node is required for ontology and architecture queries.')
    if args.kind != 'architecture' and len(ids) != 1:
        cli.error('Only architecture queries accept multiple --node arguments.')
    if args.kind == 'provider':
        collection, pipeline = GRAPH_COLLECTION, connected_graph_pipeline(ids[0], args.hops)
    elif args.kind == 'ancestors':
        collection, pipeline = ONTOLOGY_COLLECTION, ancestor_pipeline(ids[0])
    elif args.kind == 'descendants':
        collection, pipeline = ONTOLOGY_COLLECTION, descendant_pipeline(ids[0])
    else:
        collection, pipeline = ARCHITECTURE_COLLECTION, architecture_graph_pipeline(ids)
    if args.explain:
        output(pipeline)
        return 0
    with database(args) as db:
        rows = list(db[collection].aggregate(pipeline, maxTimeMS=args.timeout_ms))
        output({'collection': collection, 'results': rows})


if __name__ == '__main__':
    raise SystemExit(run(main))
