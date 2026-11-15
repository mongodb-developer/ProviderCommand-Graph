# ProviderCommand Graph — extracted Python building blocks

The salient database operations from `app5.py`, separated into reusable modules and runnable command-line examples. The working Streamlit application is unchanged. No Streamlit or pandas dependency is required for these scripts.

Unzip this folder, then copy `scripts/`, `tests/`, `docs/`, and `requirements-support.txt` into your repository. Keep your existing `app5.py`, screenshot, and main README.

## What is included

| Module | Extracted capability |
| --- | --- |
| `scripts/create_indexes.py` | Both Voyage `autoEmbed` index definitions, supporting regular indexes, missing collection setup, and readiness inspection. |
| `scripts/vector_search.py` | Patient-search and architecture-search `$vectorSearch` pipelines, with natural-language `query.text` and similarity scores. |
| `scripts/graph_queries.py` | Provider relationship traversal, ontology ancestors and descendants, and upstream/downstream architecture dependencies. |
| `scripts/time_series.py` | Native hospital time series setup and the daily occupancy, ED wait, and arrivals aggregation. |
| `scripts/provider_locations.py` | Location-scoped provider filtering, plan selection, and the illustrative patient cost calculation. |
| `scripts/demo_config.py` | Collection names, index names, model, and regular index key patterns shared with the demo. |
| `scripts/_common.py` | Masked URI prompt, connection lifecycle, command-line options, JSON output, and safe connection errors. |
| `tests/test_support.py` | Offline behavioral checks using a recording database double. |
| `docs/maintenance.md` | Operating details and the correspondence to `app5.py`. |

## Install

Run from your repository root with Python 3.10 or later:

```bash
python -m pip install -r requirements-support.txt
```

## Create the automated embedding indexes

```bash
# Read-only preview: shows what is missing and reports existing vector index status.
python scripts/create_indexes.py

# Create missing resources; existing compatible definitions are retained.
python scripts/create_indexes.py --apply

# Read-only readiness check; returns 1 while resources are missing or indexes are building.
python scripts/create_indexes.py --check
```

Each database command prompts for the Atlas URI without echoing it. The URI is not supplied through a command-line argument, saved in a file, or written to source code. Run these commands from an interactive terminal.

The setup creates two `vectorSearch` indexes using `autoEmbed`, text field `searchText`, and model `voyage-4`:

- `healthcare_autoembed_v4` on `healthcare`.
- `architecture_autoembed_v4` on `domain_documents`.

It also creates the regular indexes used by `app5.py` and ensures `hospital_metrics` is a native time series collection before creating its compound index. Existing incompatible collection types or named search index definitions stop setup; they are never automatically replaced.

Setup inserts **no sample documents**. Use the existing app's seed button to populate the demo. Vector indexes build asynchronously. Atlas must support the configured Automated Embedding feature and model, and the database identity needs the appropriate collection and index permissions.

## Run the extracted queries

```bash
python scripts/vector_search.py "I need a doctor who performs heart catheterization"
python scripts/vector_search.py "Which systems depend on the Provider API?" --target architecture
python scripts/graph_queries.py --node provider-1001 --hops 2
python scripts/graph_queries.py --kind ancestors --node interventional_cardiology
python scripts/graph_queries.py --kind descendants --node cardiology
python scripts/time_series.py --days 30
python scripts/provider_locations.py --city Chicago --language Spanish --accepting-only
```

All query scripts accept `--explain` to print their pipeline **without a connection or credentials**:

```bash
python scripts/vector_search.py "heart specialist" --explain
python scripts/graph_queries.py --node provider-1001 --hops 2 --explain
python scripts/time_series.py --days 7 --explain
```

The database default is `healthcare_ontology_demo_v4`, matching `app5.py`. Override it with `--database NAME`. Results are printed as JSON, using Extended JSON for BSON-specific values.

## Reuse from Python

```python
from scripts.create_indexes import auto_embedding_definition
from scripts.vector_search import vector_search_pipeline
from scripts.graph_queries import connected_graph_pipeline
from scripts.time_series import metrics_pipeline
from scripts.provider_locations import estimate_patient_cost

index_definition = auto_embedding_definition()
patient_search = vector_search_pipeline("heart catheterization")
provider_graph = connected_graph_pipeline("provider-1001", hops=2)
hospital_trends = metrics_pipeline(days=30)
```

These functions build definitions or pipelines; they do not open connections or execute database operations when imported. Keep a graph depth between 1 and 4 and a measurement window of 7, 14, or 30 days to match the demo UI. The CLI validates those ranges.

## Run the offline checks

```bash
python -m unittest discover -s tests -v
```

Tests cover safe index setup, repeat execution, readiness, conflicting definitions, query construction, location-scoped contracts, the cost cap, and credential-safe errors. They do not prove live Atlas feature availability or replace a live integration test.
