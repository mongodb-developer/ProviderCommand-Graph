"""Patient and architecture vector pipelines extracted from app5.py.

Atlas Automated Embedding generates query embeddings from query.text.
This module does not invoke an LLM or call an external embeddings client.
"""
if __package__:
    from ._common import database, output, parser, run
    from .demo_config import (HEALTHCARE_COLLECTION, DOMAIN_DOCUMENTS_COLLECTION,
                             VECTOR_INDEX_NAME, ARCHITECTURE_VECTOR_INDEX_NAME)
else:
    from _common import database, output, parser, run
    from demo_config import (HEALTHCARE_COLLECTION, DOMAIN_DOCUMENTS_COLLECTION,
                             VECTOR_INDEX_NAME, ARCHITECTURE_VECTOR_INDEX_NAME)


def vector_search_pipeline(query_text):
    return [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "searchText",
                "query": {
                    "text": query_text,
                },
                "numCandidates": 50,
                "limit": 5,
            }
        },
        {
            "$project": {
                "_id": 1,
                "conceptId": 1,
                "title": 1,
                "searchText": 1,
                "score": {
                    "$meta": "vectorSearchScore"
                },
            }
        },
    ]

def architecture_search_pipeline(query_text):
    return [
        {
            "$vectorSearch": {
                "index": ARCHITECTURE_VECTOR_INDEX_NAME,
                "path": "searchText",
                "query": {
                    "text": query_text,
                },
                "numCandidates": 50,
                "limit": 4,
            }
        },
        {
            "$project": {
                "_id": 1,
                "title": 1,
                "contentType": 1,
                "owner": 1,
                "lastUpdated": 1,
                "architectureNodeIds": 1,
                "searchText": 1,
                "score": {
                    "$meta": "vectorSearchScore"
                },
            }
        },
    ]

def main():
    cli = parser(__doc__)
    cli.add_argument('query', help='Natural-language query; quote multiword text.')
    cli.add_argument('--target', choices=('healthcare', 'architecture'), default='healthcare')
    cli.add_argument('--explain', action='store_true', help='Print the pipeline without connecting.')
    args = cli.parse_args()
    if not args.query.strip():
        cli.error('Query must contain text.')
    pipeline = (vector_search_pipeline(args.query) if args.target == 'healthcare'
                else architecture_search_pipeline(args.query))
    if args.explain:
        output(pipeline)
        return 0
    collection = HEALTHCARE_COLLECTION if args.target == 'healthcare' else DOMAIN_DOCUMENTS_COLLECTION
    with database(args) as db:
        rows = list(db[collection].aggregate(pipeline, maxTimeMS=args.timeout_ms))
        output({'collection': collection, 'matches': rows})


if __name__ == '__main__':
    raise SystemExit(run(main))
