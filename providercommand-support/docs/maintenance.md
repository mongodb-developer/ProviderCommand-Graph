# Maintenance and source map

## What came from app5.py

| Extracted functions or definitions | Module |
| --- | --- |
| `vector_search_pipeline`, `architecture_search_pipeline` | `scripts/vector_search.py` |
| `connected_graph_pipeline`, `ancestor_pipeline`, `descendant_pipeline`, `architecture_graph_pipeline` | `scripts/graph_queries.py` |
| `metrics_pipeline` | `scripts/time_series.py` |
| `provider_location_pipeline`, `estimate_patient_cost` | `scripts/provider_locations.py` |
| Index field configuration from `create_auto_embedding_index`, regular key patterns from seed helpers | `scripts/create_indexes.py`, `scripts/demo_config.py` |
| Native collection options from `seed_connected_data` | `scripts/time_series.py` |

The query-builder and cost functions were copied unchanged from the working `app5.py`. Index creation and collection setup were adapted to accept a database argument, operate without Streamlit session state, preview changes, and preserve existing compatible resources. The CLI wrappers and tests are new support code.

This is an additive support pack. `app5.py` does not import these modules automatically. If the app's schema changes later, update both copies or explicitly refactor the app to use these modules.

## Collection setup

To inspect just the native time series collection:

```bash
python scripts/time_series.py --setup
python scripts/time_series.py --setup --apply
```

The collection uses `timestamp` as `timeField`, `metadata` as `metaField`, and `hours` as granularity. No TTL policy is configured by these scripts. Creating a collection does not populate it.

`create_indexes.py --apply` also creates missing regular collections, the native time series collection, and supporting indexes. It does not delete, update, reseed, or export application documents. Setup is incremental: if a request fails after earlier resources were created, inspect the next dry-run plan before retrying.

## Graph traversal

Provider graph traversal follows the stored `neighbors` list in either direction. Directed labels live in outgoing `links`. The `connected` result may contain the root again through a cycle; deduplicate by `_id` before rendering, as the app does.

Ontology queries use `concepts.parentId`. Ancestors walk toward broader categories; descendants walk toward child categories. Architecture queries accept one or more starting IDs and return separate upstream and downstream arrays:

```bash
python scripts/graph_queries.py --kind architecture --node YOUR_ARCHITECTURE_NODE_ID --explain
```

Use actual IDs from your seeded `architecture_nodes` collection when executing that query.

## Provider and contract context

`provider_location_pipeline` unwinds tax entities and locations before applying city, language, specialty, and accepting-new-patient filters. It then selects the plan contract from that exact location. Supplying a plan ID does not imply that all locations accept that plan.

`provider_locations.py --concept` accepts resolved concept IDs; repeat the flag to include multiple IDs. It does not perform vector search or automatically expand ontology descendants. `estimate_patient_cost` is a simplified demonstration calculation, not a benefits adjudication engine.

## Time series interpretation

The metrics pipeline filters to `metadata.demoSource = ontology-graph-v4`. Other measurements are intentionally excluded. It groups hourly observations into America/Chicago calendar days, calculates daily average occupancy and wait time, and sums arrivals. Window boundary days may be partial. Reseed through the app if the synthetic measurement history has aged out of the selected window.

The graph tab and vector result tab remain independent. Extracting their backend operations does not automatically connect the UI entry points.

## Permissions and diagnostics

Read-only query scripts require access to the relevant collections. Index preview and readiness checks also inspect collection options, regular indexes, and search indexes. `--apply` requires creation permissions. A read-only account may be able to query data while being unable to inspect or create indexes.

Exit codes: **0** for success, **1** for an incomplete `--check`, **2** for configuration or database failures, and **130** for cancellation. CLI argument errors also return 2. Driver errors are reported by category rather than echoing connection details.

Native time series collections do not support MongoDB Search or change streams. Keep searchable text in the regular collections, as this demo does. Automated Embedding availability and model support depend on the Atlas deployment. See the current official documentation:

- [Automated Embedding](https://www.mongodb.com/docs/vector-search/crud-embeddings/automated-embedding/)
- [Time series limitations](https://www.mongodb.com/docs/manual/core/timeseries/timeseries-limitations/)
