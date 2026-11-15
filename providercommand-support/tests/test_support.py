"""Behavioral tests; no Atlas credentials, network, or Streamlit required."""
from contextlib import redirect_stderr
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from _common import run
from create_indexes import (apply_plan, auto_embedding_definition, indexes_ready, plan_indexes)
from demo_config import COLLECTIONS, METRICS_COLLECTION, VECTOR_INDEXES
from graph_queries import ancestor_pipeline, connected_graph_pipeline, descendant_pipeline
from provider_locations import estimate_patient_cost, provider_location_pipeline
from time_series import ensure_timeseries_collection, metrics_pipeline
from vector_search import architecture_search_pipeline, vector_search_pipeline


class Collection:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.regular, self.search, self.opts = [], [], {}

    def options(self):
        return self.opts

    def list_indexes(self):
        return self.regular

    def list_search_indexes(self):
        return self.search

    def create_index(self, keys):
        self.db.writes.append(('regular', self.name))
        name = '_'.join(f'{k}_{v}' for k, v in keys)
        self.regular.append({'key': dict(keys), 'name': name})
        return name

    def create_search_index(self, model):
        self.db.writes.append(('search', self.name))
        self.search.append(dict(model.document, latestDefinition=model.document['definition'],
                                status='BUILDING', queryable=False))


class Database:
    def __init__(self):
        self.collections, self.writes = {}, []

    def list_collection_names(self):
        return list(self.collections)

    def __getitem__(self, key):
        # Read handles must not create a collection, matching PyMongo.
        return self.collections[key]

    def create_collection(self, name, **options):
        self.writes.append(('collection', name))
        self.collections[name] = Collection(self, name)
        self.collections[name].opts = options
        return self.collections[name]


def provision():
    db = Database()
    apply_plan(db, plan_indexes(db))
    return db


class IndexTests(unittest.TestCase):
    def test_autoembed_uses_text_and_voyage(self):
        field = auto_embedding_definition()['fields'][0]
        self.assertEqual(field, {'type': 'autoEmbed', 'modality': 'text',
                                 'path': 'searchText', 'model': 'voyage-4'})

    def test_dry_run_never_writes(self):
        db = Database()
        plan = plan_indexes(db)
        self.assertFalse(db.writes)
        self.assertEqual(set(plan['createCollections']), set(COLLECTIONS))
        self.assertEqual(len(plan['createVectorIndexes']), 2)
        self.assertFalse(indexes_ready(plan))

    def test_timeseries_created_before_any_indexes_and_repeat_is_noop(self):
        db = provision()
        self.assertEqual(db.writes[0], ('collection', METRICS_COLLECTION))
        self.assertEqual(db[METRICS_COLLECTION].options()['timeseries']['metaField'], 'metadata')
        plan = plan_indexes(db)
        self.assertFalse(plan['createCollections'])
        self.assertFalse(plan['createRegularIndexes'])
        self.assertFalse(plan['createVectorIndexes'])
        previous = list(db.writes)
        apply_plan(db, plan)
        self.assertEqual(db.writes, previous)

    def test_building_is_not_ready(self):
        db = provision()
        self.assertFalse(indexes_ready(plan_indexes(db)))
        for collection, _ in VECTOR_INDEXES:
            db[collection].search[0].update(status='READY', queryable=True)
        self.assertTrue(indexes_ready(plan_indexes(db)))

    def test_wrong_collection_type_stops_before_writes(self):
        db = Database()
        db.create_collection(METRICS_COLLECTION)
        previous = list(db.writes)
        with self.assertRaises(ValueError):
            plan_indexes(db)
        self.assertEqual(previous, db.writes)

    def test_incompatible_named_vector_index_is_not_overwritten(self):
        db = provision()
        collection, _ = VECTOR_INDEXES[0]
        db[collection].search[0]['latestDefinition'] = auto_embedding_definition('different-model')
        previous = list(db.writes)
        with self.assertRaises(ValueError):
            plan_indexes(db)
        self.assertEqual(previous, db.writes)

    def test_uninspectable_definition_never_reports_ready(self):
        db = provision()
        collection, _ = VECTOR_INDEXES[0]
        db[collection].search[0].pop('latestDefinition')
        db[collection].search[0].pop('definition')
        self.assertFalse(indexes_ready(plan_indexes(db)))


class QueryTests(unittest.TestCase):
    def test_both_searches_use_query_text_and_scores(self):
        for builder in (vector_search_pipeline, architecture_search_pipeline):
            pipeline = builder('heart specialist')
            search = pipeline[0]['$vectorSearch']
            self.assertEqual(search['query'], {'text': 'heart specialist'})
            self.assertNotIn('queryVector', search)
            self.assertEqual(pipeline[1]['$project']['score'], {'$meta': 'vectorSearchScore'})

    def test_graph_depth_and_ontology_direction(self):
        graph = connected_graph_pipeline('provider-1001', 1)[1]['$graphLookup']
        self.assertEqual(graph['maxDepth'], 0)
        self.assertEqual(graph['connectFromField'], 'neighbors')
        ancestors = ancestor_pipeline('cardiology')[1]['$graphLookup']
        descendants = descendant_pipeline('cardiology')[1]['$graphLookup']
        self.assertEqual(ancestors['connectFromField'], 'parentId')
        self.assertEqual(descendants['connectToField'], 'parentId')

    def test_measurements_have_demo_filter_and_separate_aggregates(self):
        pipeline = metrics_pipeline(7)
        self.assertEqual(pipeline[0]['$match']['metadata.demoSource'], 'ontology-graph-v4')
        self.assertEqual(pipeline[1]['$group']['arrivals'], {'$sum': '$arrivals'})
        self.assertEqual(pipeline[1]['$group']['occupancyPct'], {'$avg': '$occupancyPct'})
        self.assertEqual(pipeline[1]['$group']['_id']['day']['$dateToString']['timezone'], 'America/Chicago')

    def test_location_filters_apply_after_unwinding_and_plan_is_scoped(self):
        pipeline = provider_location_pipeline(['cardiology'], 'Chicago', 'Spanish', 'choice-plus', True)
        self.assertEqual(pipeline[0]['$unwind'], '$taxEntities')
        self.assertEqual(pipeline[1]['$unwind'], '$taxEntities.locations')
        self.assertTrue(pipeline[2]['$match']['taxEntities.locations.acceptingNewPatients'])
        plan = pipeline[3]['$set']['selectedPlan']['$first']['$filter']
        self.assertEqual(plan['input'], '$taxEntities.locations.planContracts')
        self.assertEqual(plan['cond']['$eq'][1], 'choice-plus')

    def test_cost_estimate_is_capped_at_out_of_pocket_remaining(self):
        service = {'allowedAmount': 200, 'copay': 20, 'coinsurance': .2, 'deductibleApplies': True}
        result = estimate_patient_cost(service, 100, 50)
        self.assertEqual(result['deductibleApplied'], 100)
        self.assertEqual(result['coinsurance'], 16)
        self.assertEqual(result['estimatedResponsibility'], 50)

    def test_raw_configuration_errors_do_not_echo_credentials(self):
        def fail():
            raise ValueError('mongodb://user:DO_NOT_ECHO@host')
        capture = io.StringIO()
        with redirect_stderr(capture):
            self.assertEqual(run(fail), 2)
        self.assertNotIn('DO_NOT_ECHO', capture.getvalue())


if __name__ == '__main__':
    unittest.main()
