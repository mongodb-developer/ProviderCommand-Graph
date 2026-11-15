"""Names shared with the working app5.py demo; importing this module has no side effects."""
DATABASE_NAME = "healthcare_ontology_demo_v4"
HEALTHCARE_COLLECTION = "healthcare"
ONTOLOGY_COLLECTION = "concepts"
PROVIDERS_COLLECTION = "providers"
DOMAIN_DOCUMENTS_COLLECTION = "domain_documents"
ARCHITECTURE_COLLECTION = "architecture_nodes"
GRAPH_COLLECTION = "provider_graph"
FACILITY_COLLECTION = "hospitals"
METRICS_COLLECTION = "hospital_metrics"
DEMO_SOURCE = "ontology-graph-v4"
VECTOR_INDEX_NAME = "healthcare_autoembed_v4"
ARCHITECTURE_VECTOR_INDEX_NAME = "architecture_autoembed_v4"
EMBEDDING_MODEL = "voyage-4"
COLLECTIONS = (
    HEALTHCARE_COLLECTION, ONTOLOGY_COLLECTION, PROVIDERS_COLLECTION,
    DOMAIN_DOCUMENTS_COLLECTION, ARCHITECTURE_COLLECTION, GRAPH_COLLECTION,
    FACILITY_COLLECTION, METRICS_COLLECTION,
)
# These are the same key patterns created by app5.py's seed helpers.
REGULAR_INDEXES = {
    ONTOLOGY_COLLECTION: [(('parentId', 1),), (('name', 1),), (('code', 1),)],
    HEALTHCARE_COLLECTION: [(('conceptId', 1),)],
    PROVIDERS_COLLECTION: [
        (('specialtyConceptIds', 1),), (('taxEntities.taxId', 1),),
        (('taxEntities.locations.locationId', 1),),
        (('taxEntities.locations.address.city', 1),),
        (('taxEntities.locations.languages', 1),),
        (('taxEntities.locations.planContracts.planId', 1),),
    ],
    DOMAIN_DOCUMENTS_COLLECTION: [(('architectureNodeIds', 1),)],
    ARCHITECTURE_COLLECTION: [(('dependsOn', 1),)],
    GRAPH_COLLECTION: [(('neighbors', 1),), (('kind', 1),)],
    METRICS_COLLECTION: [(('metadata.hospitalId', 1), ('timestamp', 1))],
}
VECTOR_INDEXES = (
    (HEALTHCARE_COLLECTION, VECTOR_INDEX_NAME),
    (DOMAIN_DOCUMENTS_COLLECTION, ARCHITECTURE_VECTOR_INDEX_NAME),
)
