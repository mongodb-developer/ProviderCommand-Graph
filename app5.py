import html
import json
import time

import pandas as pd
import streamlit as st
from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError
from pymongo.operations import SearchIndexModel


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Provider Intelligence + Connected Care Graph V5",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# MONGODB ATLAS
#
# Paste your Atlas URI into the sidebar connection form.
# Credentials are held in session memory, never written to this script.
# ============================================================

DATABASE_NAME = "healthcare_ontology_demo_v4"
HEALTHCARE_COLLECTION = "healthcare"
ONTOLOGY_COLLECTION = "concepts"
PROVIDERS_COLLECTION = "providers"
DOMAIN_DOCUMENTS_COLLECTION = "domain_documents"
ARCHITECTURE_COLLECTION = "architecture_nodes"

VECTOR_INDEX_NAME = "healthcare_autoembed_v4"
ARCHITECTURE_VECTOR_INDEX_NAME = "architecture_autoembed_v4"
EMBEDDING_MODEL = "voyage-4"

def _disconnect_atlas():
    """Close this session's connection and discard previously queried results."""
    previous = st.session_state.pop("_atlas_client", None)
    if previous is not None:
        previous.close()
    for key in ["semantic_results", "matched_concept_id", "provider_matches",
                "provider_pipeline", "architecture_results", "architecture_graph",
                "logs", "last_action", "last_latency"]:
        st.session_state.pop(key, None)
    st.session_state["atlas_uri_input"] = ""
    st.session_state.pop("_connection_notice", None)


def _connect_atlas():
    # Submit callbacks run before the form is rebuilt. Clear the field immediately.
    uri = st.session_state.get("atlas_uri_input", "").strip()
    _disconnect_atlas()
    if not uri.startswith(("mongodb://", "mongodb+srv://")):
        st.session_state["_connection_notice"] = (
            "error", "Paste a MongoDB connection string starting with mongodb:// or mongodb+srv://.")
        return
    candidate = None
    try:
        candidate = MongoClient(uri, serverSelectionTimeoutMS=5000,
                                connectTimeoutMS=5000, appname="ontology-demo-graph")
        candidate.admin.command("ping")
        st.session_state["_atlas_client"] = candidate
        st.session_state["_connection_notice"] = ("success", "Connected to Atlas.")
    except (PyMongoError, ValueError, TypeError):
        if candidate is not None:
            candidate.close()
        # Driver exceptions can contain connection details. Do not display or log them.
        st.session_state["_connection_notice"] = (
            "error", "Could not connect. Check the URI, credentials, Atlas network access, and database permissions.")
    finally:
        uri = ""


with st.sidebar:
    st.markdown("### Atlas connection")
    with st.form("atlas_connection_form", clear_on_submit=True):
        st.text_input("Connection string", type="password", key="atlas_uri_input",
                      placeholder="Paste your Atlas connection string",
                      help="Used only for this session. The app does not write it to a file.")
        st.form_submit_button("Connect", on_click=_connect_atlas, use_container_width=True)
    notice = st.session_state.get("_connection_notice")
    if notice:
        if notice[0] == "error":
            st.error(notice[1])
        else:
            st.success(notice[1])
    st.button("Disconnect", on_click=_disconnect_atlas,
              disabled=st.session_state.get("_atlas_client") is None,
              use_container_width=True)
    st.caption("Connection stays in this session's memory. Disconnect closes it and clears retrieved results.")

client = st.session_state.get("_atlas_client")

db = client[DATABASE_NAME] if client else None

healthcare_collection = (
    db[HEALTHCARE_COLLECTION]
    if db is not None
    else None
)

ontology_collection = (
    db[ONTOLOGY_COLLECTION]
    if db is not None
    else None
)

providers_collection = (
    db[PROVIDERS_COLLECTION]
    if db is not None
    else None
)

domain_documents_collection = (
    db[DOMAIN_DOCUMENTS_COLLECTION]
    if db is not None
    else None
)

architecture_collection = (
    db[ARCHITECTURE_COLLECTION]
    if db is not None
    else None
)


# ============================================================
# ONTOLOGY SEED DATA
# ============================================================

ONTOLOGY_ROWS = [
    (
        "healthcare_provider",
        "PROVIDER",
        "Healthcare Provider",
        "root",
        None,
        "A person or organization that delivers healthcare services.",
        ["medical provider", "care provider"],
    ),
    (
        "individual_provider",
        "INDIVIDUAL",
        "Individual Provider",
        "provider_category",
        "healthcare_provider",
        "An individual qualified to provide healthcare services.",
        ["individual practitioner", "clinician"],
    ),
    (
        "organization_provider",
        "ORGANIZATION",
        "Organization Provider",
        "provider_category",
        "healthcare_provider",
        "An organization that provides healthcare services.",
        ["healthcare organization", "facility provider"],
    ),
    (
        "physician",
        "PHYSICIAN",
        "Physician",
        "profession",
        "individual_provider",
        "A medical professional licensed to practice medicine.",
        ["doctor", "medical doctor"],
    ),
    (
        "advanced_practice",
        "ADVANCED_PRACTICE",
        "Advanced Practice Provider",
        "profession",
        "individual_provider",
        "A clinician with advanced education and clinical responsibilities.",
        ["APP", "advanced practice clinician"],
    ),
    (
        "nurse_practitioner",
        "NP",
        "Nurse Practitioner",
        "specialty",
        "advanced_practice",
        "An advanced practice registered nurse providing clinical care.",
        ["NP", "advanced practice nurse"],
    ),
    (
        "physician_assistant",
        "PA",
        "Physician Assistant",
        "specialty",
        "advanced_practice",
        "A licensed clinician who practices medicine collaboratively.",
        ["PA", "physician associate"],
    ),
    (
        "primary_care",
        "PRIMARY_CARE",
        "Primary Care",
        "specialty_group",
        "physician",
        "First-contact and continuing care for general health needs.",
        ["general medicine", "primary medicine"],
    ),
    (
        "family_medicine",
        "207Q00000X",
        "Family Medicine",
        "specialty",
        "primary_care",
        "Comprehensive care for individuals and families across all ages.",
        ["family practice", "family doctor"],
    ),
    (
        "internal_medicine",
        "207R00000X",
        "Internal Medicine",
        "specialty",
        "primary_care",
        "Prevention, diagnosis, and treatment of adult diseases.",
        ["internist", "adult medicine"],
    ),
    (
        "pediatrics",
        "208000000X",
        "Pediatrics",
        "specialty",
        "primary_care",
        "Medical care for infants, children, and adolescents.",
        ["pediatric medicine", "children's doctor"],
    ),
    (
        "cardiology",
        "CARDIOLOGY",
        "Cardiology",
        "specialty_group",
        "internal_medicine",
        "Diagnosis and treatment of diseases of the heart and circulation.",
        ["heart medicine", "cardiovascular medicine"],
    ),
    (
        "cardiovascular_disease",
        "207RC0000X",
        "Cardiovascular Disease",
        "specialty",
        "cardiology",
        "Management of diseases affecting the heart and blood vessels.",
        ["cardiologist", "heart specialist"],
    ),
    (
        "interventional_cardiology",
        "207RI0011X",
        "Interventional Cardiology",
        "subspecialty",
        "cardiovascular_disease",
        "Catheter-based diagnosis and treatment of cardiovascular disease.",
        [
            "interventional cardiologist",
            "heart catheterization specialist",
        ],
    ),
    (
        "cardiac_electrophysiology",
        "207RC0001X",
        "Clinical Cardiac Electrophysiology",
        "subspecialty",
        "cardiovascular_disease",
        "Diagnosis and treatment of abnormal heart rhythms.",
        ["electrophysiologist", "heart rhythm specialist"],
    ),
    (
        "endocrinology",
        "207RE0101X",
        "Endocrinology, Diabetes and Metabolism",
        "subspecialty",
        "internal_medicine",
        "Treatment of hormonal, metabolic, and endocrine disorders.",
        ["endocrinologist", "diabetes specialist"],
    ),
    (
        "gastroenterology",
        "207RG0100X",
        "Gastroenterology",
        "subspecialty",
        "internal_medicine",
        "Diagnosis and treatment of digestive system disorders.",
        ["gastroenterologist", "digestive specialist"],
    ),
    (
        "pulmonology",
        "207RP1001X",
        "Pulmonary Disease",
        "subspecialty",
        "internal_medicine",
        "Diagnosis and treatment of respiratory system diseases.",
        ["pulmonologist", "lung specialist"],
    ),
    (
        "surgery",
        "SURGERY",
        "Surgery",
        "specialty_group",
        "physician",
        "Medical treatment involving operative procedures.",
        ["surgical medicine", "surgeon"],
    ),
    (
        "general_surgery",
        "208600000X",
        "General Surgery",
        "specialty",
        "surgery",
        "Surgical treatment involving abdominal and other organ systems.",
        ["general surgeon"],
    ),
    (
        "vascular_surgery",
        "2086S0129X",
        "Vascular Surgery",
        "subspecialty",
        "general_surgery",
        "Surgical treatment of diseases of the vascular system.",
        ["vascular surgeon", "blood vessel surgeon"],
    ),
    (
        "neurological_surgery",
        "207T00000X",
        "Neurological Surgery",
        "specialty",
        "surgery",
        "Surgical treatment of disorders affecting the nervous system.",
        ["neurosurgery", "neurosurgeon", "brain surgeon"],
    ),
    (
        "orthopedic_surgery",
        "207X00000X",
        "Orthopaedic Surgery",
        "specialty",
        "surgery",
        "Surgical treatment of musculoskeletal conditions.",
        ["orthopedic surgeon", "bone surgeon"],
    ),
    (
        "hospital",
        "282N00000X",
        "General Acute Care Hospital",
        "facility",
        "organization_provider",
        "A facility providing inpatient acute medical care.",
        ["acute care hospital", "general hospital"],
    ),
    (
        "clinic",
        "261Q00000X",
        "Clinic or Center",
        "facility_group",
        "organization_provider",
        "An organization delivering outpatient healthcare services.",
        ["medical clinic", "outpatient center"],
    ),
    (
        "ambulatory_surgical_center",
        "261QA1903X",
        "Ambulatory Surgical Center",
        "facility",
        "clinic",
        "A facility providing same-day surgical care.",
        ["ASC", "outpatient surgery center"],
    ),
    (
        "urgent_care",
        "261QU0200X",
        "Urgent Care",
        "facility",
        "clinic",
        "A facility providing immediate non-emergency treatment.",
        ["walk-in clinic", "immediate care"],
    ),
]


def build_ontology_documents():
    fields = [
        "_id",
        "code",
        "name",
        "conceptType",
        "parentId",
        "description",
        "synonyms",
    ]

    return [
        dict(zip(fields, row))
        for row in ONTOLOGY_ROWS
    ]


# ============================================================
# SEMANTIC SEARCH DOCUMENTS
#
# These are deliberately phrased like user requests.
# Atlas automatically embeds searchText.
# ============================================================

HEALTHCARE_DOCUMENTS = [
    {
        "_id": "search-001",
        "conceptId": "interventional_cardiology",
        "title": "Heart catheterization and stent procedures",
        "searchText": (
            "Find a doctor who performs heart catheterization, "
            "angioplasty, coronary intervention, or places cardiac stents."
        ),
    },
    {
        "_id": "search-002",
        "conceptId": "cardiac_electrophysiology",
        "title": "Abnormal heart rhythm treatment",
        "searchText": (
            "Find a heart rhythm specialist who treats arrhythmia, "
            "atrial fibrillation, or performs cardiac ablation."
        ),
    },
    {
        "_id": "search-003",
        "conceptId": "cardiovascular_disease",
        "title": "General heart disease care",
        "searchText": (
            "Find a cardiologist for chest pain, coronary artery disease, "
            "high blood pressure, or general heart problems."
        ),
    },
    {
        "_id": "search-004",
        "conceptId": "endocrinology",
        "title": "Diabetes and hormone care",
        "searchText": (
            "Find a diabetes doctor or hormone specialist for thyroid, "
            "metabolism, insulin, or endocrine problems."
        ),
    },
    {
        "_id": "search-005",
        "conceptId": "gastroenterology",
        "title": "Digestive system care",
        "searchText": (
            "Find a digestive specialist for stomach pain, reflux, "
            "intestinal problems, liver disease, or colonoscopy."
        ),
    },
    {
        "_id": "search-006",
        "conceptId": "pulmonology",
        "title": "Lung and breathing care",
        "searchText": (
            "Find a lung doctor for asthma, COPD, breathing difficulty, "
            "sleep-related breathing problems, or pulmonary disease."
        ),
    },
    {
        "_id": "search-007",
        "conceptId": "family_medicine",
        "title": "Family primary care",
        "searchText": (
            "Find a regular family doctor for checkups, preventive care, "
            "common illnesses, and ongoing primary care."
        ),
    },
    {
        "_id": "search-008",
        "conceptId": "internal_medicine",
        "title": "Adult primary care",
        "searchText": (
            "Find an adult medicine doctor or internist for general "
            "medical care and chronic health conditions."
        ),
    },
    {
        "_id": "search-009",
        "conceptId": "pediatrics",
        "title": "Medical care for children",
        "searchText": (
            "Find a doctor for my child, infant, teenager, vaccinations, "
            "well-child visits, or childhood illness."
        ),
    },
    {
        "_id": "search-010",
        "conceptId": "vascular_surgery",
        "title": "Blood vessel surgery",
        "searchText": (
            "Find a surgeon for blocked arteries, vascular disease, "
            "aneurysm, circulation problems, or blood vessel surgery."
        ),
    },
    {
        "_id": "search-011",
        "conceptId": "neurological_surgery",
        "title": "Brain and spine surgery",
        "searchText": (
            "Find a brain or spine surgeon for a neurological condition, "
            "brain tumor, spinal compression, or neurosurgery."
        ),
    },
    {
        "_id": "search-012",
        "conceptId": "orthopedic_surgery",
        "title": "Bone and joint surgery",
        "searchText": (
            "Find a bone or joint surgeon for knee, hip, shoulder, "
            "fracture, arthritis, or musculoskeletal surgery."
        ),
    },
    {
        "_id": "search-013",
        "conceptId": "nurse_practitioner",
        "title": "Nurse practitioner care",
        "searchText": (
            "Find an advanced practice nurse or nurse practitioner "
            "for routine clinical care."
        ),
    },
    {
        "_id": "search-014",
        "conceptId": "physician_assistant",
        "title": "Physician assistant care",
        "searchText": (
            "Find a physician assistant or physician associate "
            "for evaluation and treatment."
        ),
    },
    {
        "_id": "search-015",
        "conceptId": "hospital",
        "title": "Acute inpatient hospital",
        "searchText": (
            "Find a general hospital providing acute inpatient "
            "medical and surgical care."
        ),
    },
    {
        "_id": "search-016",
        "conceptId": "ambulatory_surgical_center",
        "title": "Same-day surgery center",
        "searchText": (
            "Find an outpatient surgery center or ambulatory surgical "
            "facility for a same-day procedure."
        ),
    },
    {
        "_id": "search-017",
        "conceptId": "urgent_care",
        "title": "Immediate walk-in treatment",
        "searchText": (
            "Find a walk-in clinic for an illness or injury that needs "
            "immediate treatment but is not an emergency."
        ),
    },
]


# ============================================================
# DEEPLY NESTED PROVIDER DATA
#
# A provider can have multiple Tax IDs. Each Tax ID can have
# multiple practice locations, and every location owns its own
# availability, hours, languages, services, and plan contracts.
# ============================================================

PROVIDER_DOCUMENTS = [
    {
        "_id": "provider-1001",
        "npi": "1447289012",
        "name": "Dr. Maya Patel",
        "credentials": ["MD", "FACC"],
        "specialtyConceptIds": [
            "interventional_cardiology",
            "cardiovascular_disease",
        ],
        "taxEntities": [
            {
                "taxId": "36-1234567",
                "legalName": "HeartCare Medical Group",
                "locations": [
                    {
                        "locationId": "loc-chicago-heart-01",
                        "name": "HeartCare Chicago",
                        "address": {
                            "line1": "401 N Michigan Ave",
                            "city": "Chicago",
                            "state": "IL",
                            "zip": "60611",
                        },
                        "acceptingNewPatients": True,
                        "languages": ["English", "Spanish", "Hindi"],
                        "staffHours": {
                            "monday": "8:00 AM - 5:00 PM",
                            "tuesday": "8:00 AM - 5:00 PM",
                            "wednesday": "8:00 AM - 6:00 PM",
                            "thursday": "8:00 AM - 5:00 PM",
                            "friday": "8:00 AM - 3:00 PM",
                        },
                        "specialtyConceptIds": [
                            "interventional_cardiology",
                            "cardiovascular_disease",
                        ],
                        "planContracts": [
                            {
                                "planId": "choice-plus",
                                "planName": "Choice Plus PPO",
                                "networkStatus": "in-network",
                                "services": [
                                    {
                                        "serviceCode": "99214",
                                        "label": "Specialist office visit",
                                        "allowedAmount": 210.00,
                                        "copay": 40.00,
                                        "coinsurance": 0.10,
                                        "deductibleApplies": False,
                                    },
                                    {
                                        "serviceCode": "93458",
                                        "label": "Cardiac catheterization",
                                        "allowedAmount": 2850.00,
                                        "copay": 100.00,
                                        "coinsurance": 0.20,
                                        "deductibleApplies": True,
                                    },
                                ],
                            },
                            {
                                "planId": "medicare-advantage",
                                "planName": "Medicare Advantage",
                                "networkStatus": "in-network",
                                "services": [
                                    {
                                        "serviceCode": "99214",
                                        "label": "Specialist office visit",
                                        "allowedAmount": 165.00,
                                        "copay": 35.00,
                                        "coinsurance": 0.00,
                                        "deductibleApplies": False,
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "locationId": "loc-evanston-heart-02",
                        "name": "HeartCare Evanston",
                        "address": {
                            "line1": "1000 Central St",
                            "city": "Evanston",
                            "state": "IL",
                            "zip": "60201",
                        },
                        "acceptingNewPatients": False,
                        "languages": ["English", "Hindi"],
                        "staffHours": {
                            "monday": "9:00 AM - 4:00 PM",
                            "wednesday": "9:00 AM - 4:00 PM",
                            "friday": "9:00 AM - 1:00 PM",
                        },
                        "specialtyConceptIds": ["cardiovascular_disease"],
                        "planContracts": [
                            {
                                "planId": "choice-plus",
                                "planName": "Choice Plus PPO",
                                "networkStatus": "in-network",
                                "services": [
                                    {
                                        "serviceCode": "99214",
                                        "label": "Specialist office visit",
                                        "allowedAmount": 195.00,
                                        "copay": 40.00,
                                        "coinsurance": 0.10,
                                        "deductibleApplies": False,
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
            {
                "taxId": "36-7654321",
                "legalName": "Lakeshore Cardiac Partners",
                "locations": [
                    {
                        "locationId": "loc-oakbrook-heart-03",
                        "name": "Lakeshore Cardiac Oak Brook",
                        "address": {
                            "line1": "1200 Jorie Blvd",
                            "city": "Oak Brook",
                            "state": "IL",
                            "zip": "60523",
                        },
                        "acceptingNewPatients": True,
                        "languages": ["English", "Spanish"],
                        "staffHours": {
                            "tuesday": "8:00 AM - 5:00 PM",
                            "thursday": "8:00 AM - 5:00 PM",
                        },
                        "specialtyConceptIds": ["interventional_cardiology"],
                        "planContracts": [
                            {
                                "planId": "choice-plus",
                                "planName": "Choice Plus PPO",
                                "networkStatus": "in-network",
                                "services": [
                                    {
                                        "serviceCode": "99214",
                                        "label": "Specialist office visit",
                                        "allowedAmount": 220.00,
                                        "copay": 40.00,
                                        "coinsurance": 0.10,
                                        "deductibleApplies": False,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    },
    {
        "_id": "provider-1002",
        "npi": "1558390123",
        "name": "Dr. Marcus Chen",
        "credentials": ["MD", "FHRS"],
        "specialtyConceptIds": ["cardiac_electrophysiology"],
        "taxEntities": [
            {
                "taxId": "36-9988776",
                "legalName": "Chicago Rhythm Institute",
                "locations": [
                    {
                        "locationId": "loc-chicago-rhythm-01",
                        "name": "Chicago Rhythm Institute",
                        "address": {
                            "line1": "675 N Saint Clair St",
                            "city": "Chicago",
                            "state": "IL",
                            "zip": "60611",
                        },
                        "acceptingNewPatients": True,
                        "languages": ["English", "Mandarin"],
                        "staffHours": {
                            "monday": "7:30 AM - 4:30 PM",
                            "tuesday": "7:30 AM - 4:30 PM",
                            "thursday": "7:30 AM - 4:30 PM",
                        },
                        "specialtyConceptIds": ["cardiac_electrophysiology"],
                        "planContracts": [
                            {
                                "planId": "choice-plus",
                                "planName": "Choice Plus PPO",
                                "networkStatus": "in-network",
                                "services": [
                                    {
                                        "serviceCode": "99214",
                                        "label": "Specialist office visit",
                                        "allowedAmount": 215.00,
                                        "copay": 40.00,
                                        "coinsurance": 0.10,
                                        "deductibleApplies": False,
                                    },
                                    {
                                        "serviceCode": "93656",
                                        "label": "Cardiac ablation",
                                        "allowedAmount": 4800.00,
                                        "copay": 150.00,
                                        "coinsurance": 0.20,
                                        "deductibleApplies": True,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    },
    {
        "_id": "provider-1003",
        "npi": "1669401234",
        "name": "Dr. Elena Rodriguez",
        "credentials": ["MD"],
        "specialtyConceptIds": ["endocrinology"],
        "taxEntities": [
            {
                "taxId": "36-5544332",
                "legalName": "Lakeview Endocrine Associates",
                "locations": [
                    {
                        "locationId": "loc-chicago-endo-01",
                        "name": "Lakeview Endocrine Associates",
                        "address": {
                            "line1": "3000 N Halsted St",
                            "city": "Chicago",
                            "state": "IL",
                            "zip": "60657",
                        },
                        "acceptingNewPatients": True,
                        "languages": ["English", "Spanish"],
                        "staffHours": {
                            "monday": "8:30 AM - 5:00 PM",
                            "tuesday": "8:30 AM - 5:00 PM",
                            "wednesday": "10:00 AM - 7:00 PM",
                            "friday": "8:30 AM - 2:00 PM",
                        },
                        "specialtyConceptIds": ["endocrinology"],
                        "planContracts": [
                            {
                                "planId": "choice-plus",
                                "planName": "Choice Plus PPO",
                                "networkStatus": "in-network",
                                "services": [
                                    {
                                        "serviceCode": "99214",
                                        "label": "Specialist office visit",
                                        "allowedAmount": 185.00,
                                        "copay": 40.00,
                                        "coinsurance": 0.10,
                                        "deductibleApplies": False,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    },
    {
        "_id": "provider-1004",
        "npi": "1770512345",
        "name": "Dr. Amina Hassan",
        "credentials": ["MD", "FAAP"],
        "specialtyConceptIds": ["pediatrics"],
        "taxEntities": [
            {
                "taxId": "36-2233445",
                "legalName": "Northside Children's Health",
                "locations": [
                    {
                        "locationId": "loc-chicago-peds-01",
                        "name": "Northside Children's Health",
                        "address": {
                            "line1": "4800 N Western Ave",
                            "city": "Chicago",
                            "state": "IL",
                            "zip": "60625",
                        },
                        "acceptingNewPatients": True,
                        "languages": ["English", "Arabic", "Spanish"],
                        "staffHours": {
                            "monday": "8:00 AM - 7:00 PM",
                            "tuesday": "8:00 AM - 7:00 PM",
                            "saturday": "9:00 AM - 1:00 PM",
                        },
                        "specialtyConceptIds": ["pediatrics"],
                        "planContracts": [
                            {
                                "planId": "choice-plus",
                                "planName": "Choice Plus PPO",
                                "networkStatus": "in-network",
                                "services": [
                                    {
                                        "serviceCode": "99393",
                                        "label": "Well-child visit",
                                        "allowedAmount": 160.00,
                                        "copay": 0.00,
                                        "coinsurance": 0.00,
                                        "deductibleApplies": False,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    },
    {
        "_id": "provider-1005",
        "npi": "1881623456",
        "name": "Dr. James Wilson",
        "credentials": ["MD"],
        "specialtyConceptIds": ["orthopedic_surgery"],
        "taxEntities": [
            {
                "taxId": "36-6677889",
                "legalName": "Midwest Bone and Joint",
                "locations": [
                    {
                        "locationId": "loc-oakbrook-ortho-01",
                        "name": "Midwest Bone and Joint Oak Brook",
                        "address": {
                            "line1": "1801 W 22nd St",
                            "city": "Oak Brook",
                            "state": "IL",
                            "zip": "60523",
                        },
                        "acceptingNewPatients": True,
                        "languages": ["English"],
                        "staffHours": {
                            "monday": "8:00 AM - 5:00 PM",
                            "wednesday": "8:00 AM - 5:00 PM",
                            "friday": "8:00 AM - 3:00 PM",
                        },
                        "specialtyConceptIds": ["orthopedic_surgery"],
                        "planContracts": [
                            {
                                "planId": "choice-plus",
                                "planName": "Choice Plus PPO",
                                "networkStatus": "in-network",
                                "services": [
                                    {
                                        "serviceCode": "99214",
                                        "label": "Specialist office visit",
                                        "allowedAmount": 205.00,
                                        "copay": 40.00,
                                        "coinsurance": 0.10,
                                        "deductibleApplies": False,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    },
]


# ============================================================
# UNSTRUCTURED DOMAIN DOCUMENTS + ARCHITECTURE GRAPH
# ============================================================

DOMAIN_DOCUMENTS = [
    {
        "_id": "doc-provider-directory",
        "title": "Provider Directory Current-State Architecture",
        "contentType": "architecture_diagram_text",
        "owner": "Provider Platform",
        "lastUpdated": "2026-09-28",
        "architectureNodeIds": [
            "provider_source",
            "provider_directory",
            "provider_api",
        ],
        "searchText": (
            "Current-state provider architecture diagram. Provider source "
            "feeds tax identifiers, practice locations, languages, office "
            "hours, and new-patient availability into Provider Directory. "
            "Provider Directory publishes normalized provider and location "
            "records through Provider API. Location changes are propagated "
            "to FindCare and Eligibility Service through Provider API."
        ),
    },
    {
        "_id": "doc-findcare-repository",
        "title": "FindCare Domain Repository Notes",
        "contentType": "repository_markdown",
        "owner": "FindCare",
        "lastUpdated": "2026-10-02",
        "architectureNodeIds": ["findcare", "provider_api"],
        "searchText": (
            "FindCare consumes Provider API data for typeahead, geographic "
            "search, specialty matching, location availability, language, "
            "and network filtering. FindCare depends on timely location-level "
            "updates from Provider Directory."
        ),
    },
    {
        "_id": "doc-eligibility-service",
        "title": "Eligibility Service Integration Contract",
        "contentType": "api_contract",
        "owner": "Eligibility Platform",
        "lastUpdated": "2026-09-30",
        "architectureNodeIds": [
            "eligibility_service",
            "provider_api",
            "plan_contracts",
        ],
        "searchText": (
            "Eligibility Service resolves the member plan, active coverage, "
            "network tier, deductible balance, and remaining out-of-pocket "
            "maximum. It combines provider location network participation "
            "from Provider API with plan contract data."
        ),
    },
    {
        "_id": "doc-benefit-engine",
        "title": "Benefit Engine Cost Estimation ADR",
        "contentType": "architecture_decision_record",
        "owner": "Benefit Engine",
        "lastUpdated": "2026-10-04",
        "architectureNodeIds": [
            "benefit_engine",
            "eligibility_service",
            "plan_contracts",
        ],
        "searchText": (
            "Benefit Engine produces a pre-service patient cost estimate from "
            "the contracted allowed amount, copay, deductible remaining, "
            "coinsurance, and out-of-pocket remaining. Estimates are not "
            "adjudicated claims and must be labeled as illustrative."
        ),
    },
    {
        "_id": "doc-member-experience",
        "title": "Member Portal Provider Search Flow",
        "contentType": "domain_document",
        "owner": "Member Experience",
        "lastUpdated": "2026-10-05",
        "architectureNodeIds": [
            "member_portal",
            "findcare",
            "benefit_engine",
        ],
        "searchText": (
            "The Member Portal asks FindCare for matching providers and exact "
            "practice locations, then calls Benefit Engine for plan-specific "
            "cost estimates. Results include new-patient status, spoken "
            "languages, office hours, network status, and estimated cost."
        ),
    },
    {
        "_id": "doc-location-runbook",
        "title": "Provider Location Change Runbook",
        "contentType": "operations_runbook",
        "owner": "Provider Operations",
        "lastUpdated": "2026-10-06",
        "architectureNodeIds": [
            "provider_source",
            "provider_directory",
            "provider_api",
            "findcare",
        ],
        "searchText": (
            "When a practice location closes or changes availability, update "
            "the source provider record, validate the Tax ID and location ID, "
            "publish through Provider Directory and Provider API, invalidate "
            "FindCare cache entries, and verify downstream member search."
        ),
    },
]


ARCHITECTURE_NODES = [
    {
        "_id": "provider_source",
        "name": "Provider Source Systems",
        "nodeType": "source",
        "owner": "Provider Operations",
        "dependsOn": [],
        "description": "Authoritative provider, Tax ID, and location feeds.",
    },
    {
        "_id": "provider_directory",
        "name": "Provider Directory",
        "nodeType": "data_product",
        "owner": "Provider Platform",
        "dependsOn": ["provider_source"],
        "description": "Canonical provider and practice-location store.",
    },
    {
        "_id": "provider_api",
        "name": "Provider API",
        "nodeType": "service",
        "owner": "Provider Platform",
        "dependsOn": ["provider_directory"],
        "description": "Publishes provider and location data to consumers.",
    },
    {
        "_id": "plan_contracts",
        "name": "Plan Contract Store",
        "nodeType": "data_product",
        "owner": "Network Contracting",
        "dependsOn": [],
        "description": "Plan, network, contracted rate, and benefit data.",
    },
    {
        "_id": "eligibility_service",
        "name": "Eligibility Service",
        "nodeType": "service",
        "owner": "Eligibility Platform",
        "dependsOn": ["provider_api", "plan_contracts"],
        "description": "Resolves member coverage and network participation.",
    },
    {
        "_id": "benefit_engine",
        "name": "Benefit Engine",
        "nodeType": "service",
        "owner": "Benefit Engine",
        "dependsOn": ["eligibility_service", "plan_contracts"],
        "description": "Calculates illustrative patient cost estimates.",
    },
    {
        "_id": "findcare",
        "name": "FindCare",
        "nodeType": "application",
        "owner": "FindCare",
        "dependsOn": ["provider_api"],
        "description": "Provider discovery, specialty, and location search.",
    },
    {
        "_id": "member_portal",
        "name": "Member Portal",
        "nodeType": "channel",
        "owner": "Member Experience",
        "dependsOn": ["findcare", "benefit_engine"],
        "description": "Member-facing provider and cost experience.",
    },
]


# ============================================================
# SESSION STATE
# ============================================================

if "logs" not in st.session_state:
    st.session_state.logs = [
        "[BOOT] INFO  app=healthcare_semantic_ontology_v4",
        f"[BOOT] INFO  database={DATABASE_NAME}",
        f"[BOOT] INFO  vector_source={HEALTHCARE_COLLECTION}",
        f"[BOOT] INFO  ontology={ONTOLOGY_COLLECTION}",
        f"[BOOT] INFO  providers={PROVIDERS_COLLECTION}",
        f"[BOOT] INFO  architecture={ARCHITECTURE_COLLECTION}",
        "[BOOT] READY waiting for demo action...",
    ]

if "last_action" not in st.session_state:
    st.session_state.last_action = "READY"

if "last_latency" not in st.session_state:
    st.session_state.last_latency = None

if "query_text" not in st.session_state:
    st.session_state.query_text = (
        "I need a doctor who performs heart catheterization"
    )

if "semantic_results" not in st.session_state:
    st.session_state.semantic_results = []

if "matched_concept_id" not in st.session_state:
    st.session_state.matched_concept_id = None

if "provider_matches" not in st.session_state:
    st.session_state.provider_matches = []

if "provider_pipeline" not in st.session_state:
    st.session_state.provider_pipeline = []

if "architecture_query" not in st.session_state:
    st.session_state.architecture_query = (
        "If provider location availability changes, which systems are affected?"
    )

if "architecture_results" not in st.session_state:
    st.session_state.architecture_results = []

if "architecture_graph" not in st.session_state:
    st.session_state.architecture_graph = []


def add_log(message):
    stamp = time.strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{stamp}] {message}")
    st.session_state.logs = st.session_state.logs[-20:]


# ============================================================
# ATLAS OPERATIONS
# ============================================================

def atlas_status():
    if client is None:
        return False, "Use the Atlas connection form in the sidebar."

    try:
        client.admin.command("ping")
        return True, "ATLAS CONNECTED"
    except Exception:
        return False, "Atlas connection unavailable. Reconnect using the sidebar and check network access."


def collection_count(collection):
    if collection is None:
        return 0

    try:
        return collection.count_documents({})
    except PyMongoError:
        return 0


def get_vector_index_status(collection, index_name):
    if collection is None:
        return {
            "exists": False,
            "ready": False,
            "status": "NOT CONFIGURED",
        }

    try:
        indexes = list(
            collection.list_search_indexes()
        )

        for index in indexes:
            if index.get("name") == index_name:
                status = index.get("status", "UNKNOWN")
                queryable = index.get("queryable", False)

                return {
                    "exists": True,
                    "ready": bool(queryable),
                    "status": status,
                }

        return {
            "exists": False,
            "ready": False,
            "status": "NOT CREATED",
        }

    except PyMongoError as exc:
        return {
            "exists": False,
            "ready": False,
            "status": f"UNAVAILABLE: {exc}",
        }


def create_auto_embedding_index(collection, index_name):
    current_status = get_vector_index_status(
        collection,
        index_name,
    )

    if current_status["exists"]:
        add_log(
            f"INDEX {index_name} already exists "
            f"status={current_status['status']}"
        )
        return

    model = SearchIndexModel(
        definition={
            "fields": [
                {
                    "type": "autoEmbed",
                    "modality": "text",
                    "path": "searchText",
                    "model": EMBEDDING_MODEL,
                }
            ]
        },
        name=index_name,
        type="vectorSearch",
    )

    collection.create_search_index(
        model=model
    )

    add_log(
        f"INDEX created={index_name} "
        f"model={EMBEDDING_MODEL}"
    )
    add_log(
        "INDEX asynchronous build started"
    )


# ============================================================
# V4: CONNECTED PROVIDER GRAPH + NATIVE TIME SERIES
# All people, affiliations, facilities and measurements are synthetic.
# pip install streamlit pandas pymongo[srv]
# streamlit run app5.py
# ============================================================
GRAPH_COLLECTION = "provider_graph"
FACILITY_COLLECTION = "hospitals"
METRICS_COLLECTION = "hospital_metrics"
DEMO_SOURCE = "ontology-graph-v4"

HOSPITALS = [
    {"_id": "hospital-chicago", "name": "Demo Chicago Heart Hospital", "city": "Chicago", "state": "IL", "beds": 240},
    {"_id": "hospital-evanston", "name": "Demo Evanston Medical Center", "city": "Evanston", "state": "IL", "beds": 180},
    {"_id": "hospital-oakbrook", "name": "Demo Oak Brook Specialty Hospital", "city": "Oak Brook", "state": "IL", "beds": 120},
]


def build_provider_graph():
    """Project documents into labeled nodes; keep edge meaning separate from layout."""
    nodes = {}
    edges = []

    def node(key, label, kind, **properties):
        if key not in nodes:
            nodes[key] = {"_id": key, "name": label, "kind": kind,
                          "properties": properties, "neighbors": [], "links": []}
        return key

    def edge(source, target, label):
        item = {"source": source, "target": target, "label": label}
        if item not in edges:
            edges.append(item)

    for h in HOSPITALS:
        node(h["_id"], h["name"], "Hospital", **h)
        city = node("city:" + h["city"], h["city"], "City", state=h["state"])
        edge(h["_id"], city, "LOCATED_IN")
    concepts = build_ontology_documents()
    for concept in concepts:
        node("concept:" + concept["_id"], concept["name"], "Concept",
             definition=concept["description"], code=concept["code"],
             conceptType=concept["conceptType"], synonyms=concept["synonyms"])
    for concept in concepts:
        if concept["parentId"]:
            edge("concept:" + concept["_id"], "concept:" + concept["parentId"], "IS_A")
    for p in PROVIDER_DOCUMENTS:
        pid = node(p["_id"], p["name"], "Doctor", npi=p["npi"], credentials=p["credentials"])
        for cid in p["specialtyConceptIds"]:
            edge(pid, "concept:" + cid, "SPECIALIZES_IN")
        affiliations = set()
        for entity in p["taxEntities"]:
            gid = node("group:" + entity["taxId"], entity["legalName"], "Medical group", taxId=entity["taxId"])
            edge(pid, gid, "MEMBER_OF")
            for loc in entity["locations"]:
                lid = node(loc["locationId"], loc["name"], "Practice location",
                           address=loc["address"], languages=loc["languages"],
                           acceptingNewPatients=loc["acceptingNewPatients"], hours=loc["staffHours"])
                edge(pid, lid, "PRACTICES_AT")
                edge(gid, lid, "OPERATES")
                city = node("city:" + loc["address"]["city"], loc["address"]["city"], "City", state="IL")
                edge(lid, city, "LOCATED_IN")
                for h in HOSPITALS:
                    if h["city"] == loc["address"]["city"]:
                        affiliations.add(h["_id"])
                for plan in loc["planContracts"]:
                    # Contract is scoped to provider + tax entity + location.
                    # A shared plan node alone must never imply universal acceptance.
                    contract = node("contract:" + pid + ":" + entity["taxId"] + ":" + lid + ":" + plan["planId"],
                                    plan["planName"] + " contract", "Plan contract",
                                    providerId=pid, locationId=lid, taxId=entity["taxId"], **plan)
                    edge(pid, contract, "HAS_CONTRACT")
                    edge(contract, lid, "APPLIES_AT")
        for hid in sorted(affiliations):
            edge(pid, hid, "AFFILIATED_WITH")
    for e in edges:
        nodes[e["source"]]["links"].append(e)
        for a, b in [(e["source"], e["target"]), (e["target"], e["source"])]:
            if b not in nodes[a]["neighbors"]:
                nodes[a]["neighbors"].append(b)
    return list(nodes.values())


def build_metric_samples(now=None):
    """Hourly synthetic observations; stable metadata identifies each hospital series."""
    import math
    import random
    from datetime import datetime, timedelta, timezone
    rng = random.Random(47)
    end = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    rows = []
    for i, h in enumerate(HOSPITALS):
        for hour in range(30 * 24):
            ts = end - timedelta(hours=30 * 24 - hour)
            load = math.sin((ts.hour - 8) * math.pi / 12)
            occupancy = round(max(35, min(98, 72 + i * 5 + load * 9 + rng.uniform(-5, 5))), 1)
            rows.append({"timestamp": ts,
                         "metadata": {"hospitalId": h["_id"], "demoSource": DEMO_SOURCE},
                         "occupancyPct": occupancy,
                         "edWaitMinutes": round(max(4, 20 + i * 7 + load * 11 + rng.uniform(-5, 5)), 1),
                         "arrivals": max(0, round(9 + load * 5 + rng.uniform(-3, 3)))})
    return rows


def seed_connected_data():
    from pymongo import ReplaceOne
    # Separate V4 database protects the original V2 demo.
    graph = build_provider_graph()
    db[GRAPH_COLLECTION].bulk_write([ReplaceOne({"_id": n["_id"]}, n, upsert=True) for n in graph])
    db[FACILITY_COLLECTION].bulk_write([ReplaceOne({"_id": h["_id"]}, h, upsert=True) for h in HOSPITALS])
    db[GRAPH_COLLECTION].create_index("neighbors")
    db[GRAPH_COLLECTION].create_index("kind")
    if METRICS_COLLECTION not in db.list_collection_names():
        db.create_collection(METRICS_COLLECTION, timeseries={
            "timeField": "timestamp", "metaField": "metadata", "granularity": "hours"})
    else:
        options = db[METRICS_COLLECTION].options().get("timeseries", {})
        if options.get("timeField") != "timestamp" or options.get("metaField") != "metadata":
            raise PyMongoError("hospital_metrics must be a native time series collection with timestamp / metadata fields.")
    # Metadata-only delete is supported on older time series versions too.
    db[METRICS_COLLECTION].delete_many({"metadata.demoSource": DEMO_SOURCE})
    db[METRICS_COLLECTION].insert_many(build_metric_samples())
    db[METRICS_COLLECTION].create_index([("metadata.hospitalId", 1), ("timestamp", 1)])
    add_log(f"V4 graph nodes={len(graph)}; native time series observations=2160")


def connected_graph_pipeline(root_id, hops):
    return [{"$match": {"_id": root_id}}, {"$graphLookup": {
        "from": GRAPH_COLLECTION, "startWith": "$neighbors",
        "connectFromField": "neighbors", "connectToField": "_id",
        "as": "connected", "maxDepth": hops - 1, "depthField": "hopDepth"}}]


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


def preview_daily_metrics(days):
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    groups = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for r in build_metric_samples():
        if r["timestamp"] < cutoff:
            continue
        key = (r["metadata"]["hospitalId"], r["timestamp"].astimezone(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d"))
        g = groups.setdefault(key, {"hospitalId": key[0], "day": key[1], "occupancyPct": 0,
                                    "edWaitMinutes": 0, "arrivals": 0, "samples": 0})
        for metric in ["occupancyPct", "edWaitMinutes", "arrivals"]:
            g[metric] += r[metric]
        g["samples"] += 1
    for g in groups.values():
        for metric in ["occupancyPct", "edWaitMinutes"]:
            g[metric] /= g["samples"]
    return sorted(groups.values(), key=lambda g: g["day"])


def graph_html(nodes, root, daily):
    # No CDN or additional graph package. SVG keeps labels crisp when zooming.
    payload = json.dumps({"nodes": nodes, "root": root, "daily": daily}, default=str).replace("<", "\\u003c")
    return GRAPH_HTML.replace("__PAYLOAD__", payload)


GRAPH_HTML = r'''<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;font:13px system-ui;color:#e6e8f1;background:#20232d}
.shell{border:1px solid #414553;border-radius:14px;overflow:hidden}.toolbar{display:flex;gap:12px;align-items:center;padding:12px 16px;background:#292d39;border-bottom:1px solid #414553}
button{background:#3c4253;color:#fff;border:1px solid #5a6277;padding:7px 12px;border-radius:7px;cursor:pointer}.hint{color:#b5bbcd;font-size:12px}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 290px}#graph{width:100%;height:570px;touch-action:none;cursor:grab;background:radial-gradient(ellipse at center,#303644,#20232d)}
#details{padding:20px;border-left:1px solid #414553;max-height:570px;overflow:auto}h2{font-size:19px;line-height:1.35;margin:10px 0}h3{font-size:13px;margin-top:23px}.badge{font-size:10px;font-weight:700;letter-spacing:1px;color:#85edb0;text-transform:uppercase}
pre{white-space:pre-wrap;word-break:break-word;font:11px/1.6 ui-monospace,monospace;color:#c3c9da}.legend{display:flex;gap:15px;flex-wrap:wrap;padding:12px 16px;border-top:1px solid #414553;font-size:11px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
#graph text{user-select:none}.edge-label{font-size:9px;fill:#c8cedd;paint-order:stroke;stroke:#252a35;stroke-width:4px;stroke-linejoin:round}.node-label{font-size:11px;fill:#f2f4fb;paint-order:stroke;stroke:#252a35;stroke-width:4px;font-weight:600}.spark{width:100%;height:100px} .stat{font-size:25px;color:#84efae;margin:8px 0}.sub{font-size:11px;color:#bac1d1}
@media(max-width:720px){.layout{grid-template-columns:1fr}#details{max-height:260px;border-left:0;border-top:1px solid #414553}#graph{height:420px}}
</style></head><body><div class="shell"><div class="toolbar"><b>CONNECTED CARE GRAPH</b><button id="reset">Fit graph</button><button id="motion">Pause layout</button><span class="hint">Drag nodes · Scroll to zoom · Drag background to pan · Click for details</span></div><div class="layout"><svg id="graph" role="img" aria-label="Interactive provider relationship graph"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#68758a"/></marker></defs><g id="world"></g></svg><aside id="details"></aside></div><div class="legend" id="legend"></div></div>
<script>
const data=__PAYLOAD__;
const colors={'Doctor':'#69e4a6','Hospital':'#ad8aff','City':'#5cc8ef','Concept':'#f7c66a','Medical group':'#ef91bd','Practice location':'#8ca9ff','Plan contract':'#f39f6b'};
const svg=document.querySelector('#graph'),world=document.querySelector('#world'),ns='http://www.w3.org/2000/svg';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let W=svg.clientWidth,H=svg.clientHeight,scale=1,px=0,py=0,selected=data.root,paused=false,frames=0,raf=null;
const nodes=data.nodes.map((n,i)=>({...n,x:W/2+Math.cos(i*2.4)*150,y:H/2+Math.sin(i*2.4)*150,vx:0,vy:0}));
const byId=new Map(nodes.map(n=>[n._id,n]));const edges=nodes.flatMap(n=>n.links||[]).filter(e=>byId.has(e.source)&&byId.has(e.target));
function el(tag,attrs,parent){const x=document.createElementNS(ns,tag);Object.entries(attrs||{}).forEach(([k,v])=>x.setAttribute(k,v));parent.append(x);return x}
const edgeEls=edges.map(e=>{const g=el('g',{},world);return {e,line:el('line',{stroke:'#68758a','stroke-width':1.3,'marker-end':'url(#arrow)'},g),label:el('text',{'class':'edge-label','text-anchor':'middle'},g)}});
edgeEls.forEach(x=>x.label.textContent=x.e.label);
const nodeEls=nodes.map(n=>{const g=el('g',{'tabindex':0,'role':'button','aria-label':n.name},world);const c=el('circle',{r:n._id===data.root?27:21,fill:colors[n.kind]||'#999',stroke:'#20232d','stroke-width':3},g);const t=el('text',{'class':'node-label',y:39,'text-anchor':'middle'},g);t.textContent=n.name.length>29?n.name.slice(0,27)+'…':n.name;el('title',{},g).textContent=n.name+' · '+n.kind;g.addEventListener('pointerdown',ev=>startDrag(ev,n));g.addEventListener('keydown',ev=>{if(ev.key==='Enter')inspect(n)});return {n,g,c}});
function transform(){world.setAttribute('transform',`translate(${px},${py}) scale(${scale})`)}
function paint(){edgeEls.forEach(({e,line,label})=>{const a=byId.get(e.source),b=byId.get(e.target),dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1;line.setAttribute('x1',a.x+dx/d*25);line.setAttribute('y1',a.y+dy/d*25);line.setAttribute('x2',b.x-dx/d*27);line.setAttribute('y2',b.y-dy/d*27);label.setAttribute('x',(a.x+b.x)/2);label.setAttribute('y',(a.y+b.y)/2-5);const active=e.source===selected||e.target===selected;line.setAttribute('stroke',active?'#a2adc4':'#566074');line.setAttribute('stroke-width',active?2.2:1);});nodeEls.forEach(({n,g,c})=>{g.setAttribute('transform',`translate(${n.x},${n.y})`);c.setAttribute('stroke',n._id===selected?'#fff':'#20232d');});transform()}
function tick(){raf=null;if(paused)return;for(let i=0;i<nodes.length;i++){const a=nodes[i];for(let j=i+1;j<nodes.length;j++){const b=nodes[j],dx=b.x-a.x,dy=b.y-a.y,d=Math.max(20,Math.hypot(dx,dy)),f=1700/(d*d);a.vx-=dx/d*f;a.vy-=dy/d*f;b.vx+=dx/d*f;b.vy+=dy/d*f;}}
edges.forEach(e=>{const a=byId.get(e.source),b=byId.get(e.target),dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-150)*0.008;a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f});nodes.forEach(n=>{if(n.fixed)return;n.vx=(n.vx+(W/2-n.x)*0.0015)*0.78;n.vy=(n.vy+(H/2-n.y)*0.0015)*0.78;n.x+=n.vx;n.y+=n.vy;});paint();frames++;if(frames<360)raf=requestAnimationFrame(tick);else fit()}
function restart(){frames=0;if(!raf&&!paused)raf=requestAnimationFrame(tick)}
function fit(){if(!nodes.length)return;const xs=nodes.map(n=>n.x),ys=nodes.map(n=>n.y),minX=Math.min(...xs)-100,maxX=Math.max(...xs)+100,minY=Math.min(...ys)-60,maxY=Math.max(...ys)+80;scale=Math.min(1.4,W/(maxX-minX),H/(maxY-minY));px=W/2-(minX+maxX)/2*scale;py=H/2-(minY+maxY)/2*scale;transform()}
let drag=null;function startDrag(ev,n){ev.preventDefault();ev.stopPropagation();svg.setPointerCapture(ev.pointerId);drag={n,x:ev.clientX,y:ev.clientY,moved:false};n.fixed=true;inspect(n)}
svg.addEventListener('pointerdown',ev=>{svg.setPointerCapture(ev.pointerId);drag={x:ev.clientX,y:ev.clientY,moved:false}});
svg.addEventListener('pointermove',ev=>{if(!drag)return;let dx=ev.clientX-drag.x,dy=ev.clientY-drag.y;drag.moved=true;if(drag.n){drag.n.x+=dx/scale;drag.n.y+=dy/scale}else{px+=dx;py+=dy}drag.x=ev.clientX;drag.y=ev.clientY;paint()});
function endDrag(){if(drag?.n){drag.n.fixed=false;restart()}drag=null}svg.addEventListener('pointerup',endDrag);svg.addEventListener('pointercancel',endDrag);
svg.addEventListener('wheel',ev=>{ev.preventDefault();const r=svg.getBoundingClientRect(),x=ev.clientX-r.left,y=ev.clientY-r.top,s=Math.max(.15,Math.min(4,scale*(ev.deltaY>0?.9:1.1)));px=x-(x-px)*s/scale;py=y-(y-py)*s/scale;scale=s;transform()},{passive:false});
function inspect(n){selected=n._id;const links=edges.filter(e=>e.source===n._id||e.target===n._id);let body=`<span class="badge" style="color:${colors[n.kind]}">${esc(n.kind)}</span><h2>${esc(n.name)}</h2>`;
if(n.kind==='Concept')body+='<p class="sub">Ontology concept: defines a category and how it relates to broader categories. Doctors and facilities are instances connected to these meanings.</p>';
if(n.kind==='Hospital'){const rows=data.daily.filter(r=>r.hospitalId===n._id);if(rows.length){const last=rows.at(-1),vals=rows.map(r=>r.edWaitMinutes),max=Math.max(1,...vals)*1.15,pts=vals.map((v,i)=>`${10+i*230/Math.max(1,vals.length-1)},${85-v/max*70}`).join(' ');body+=`<h3>ED WAIT TREND</h3><div class="stat">${last.edWaitMinutes.toFixed(1)} min</div><div class="sub">Latest daily average · ${esc(last.day)}</div><svg class="spark" viewBox="0 0 250 100" role="img" aria-label="Emergency department wait time trend"><line x1="10" y1="85" x2="240" y2="85" stroke="#68758a"/><polyline points="${pts}" fill="none" stroke="#ad8aff" stroke-width="3"/></svg><div class="sub">${esc(rows[0].day)} → ${esc(last.day)}<br>Daily aggregates; synthetic hourly measurements.</div>`}else body+='<p>No measurements in this date range.</p>'}
body+='<h3>RELATIONSHIPS</h3>'+links.map(e=>`<p class="sub">${esc(byId.get(e.source).name)}<br><b style="color:#e6e8f1">${esc(e.label)}</b> → ${esc(byId.get(e.target).name)}</p>`).join('');body+='<h3>PROPERTIES</h3><pre>'+esc(JSON.stringify(n.properties,null,2))+'</pre>';document.querySelector('#details').innerHTML=body;paint()}
document.querySelector('#legend').innerHTML=Object.entries(colors).map(([k,c])=>`<span><i class="dot" style="background:${c}"></i>${k}</span>`).join('');document.querySelector('#reset').onclick=fit;document.querySelector('#motion').onclick=()=>{paused=!paused;document.querySelector('#motion').textContent=paused?'Resume layout':'Pause layout';if(!paused)restart()};new ResizeObserver(()=>{W=svg.clientWidth;H=svg.clientHeight;fit()}).observe(svg);if(byId.has(data.root))inspect(byId.get(data.root));restart();
</script></body></html>'''


def render_connected_explorer(preview=False):
    import streamlit.components.v1 as components
    st.markdown("### Connected care explorer")
    st.caption("Synthetic demonstration data · hospital affiliations are illustrative, not verified provider directory facts.")
    if preview:
        st.info("PREVIEW — graph and measurements generated locally. Configure Atlas and seed V4 to run database traversal and native time series aggregations.")
    else:
        st.success("ATLAS DATA — graph traversal and measurement aggregations execute against MongoDB.")
    st.write("Start with a doctor. Follow their hospital affiliation to its city, then click the hospital to see how wait times change. Gold nodes explain the specialty ontology.")
    a, b, c = st.columns([2, 1, 1])
    with a:
        if preview:
            doctors = [n for n in build_provider_graph() if n["kind"] == "Doctor"]
        else:
            doctors = list(db[GRAPH_COLLECTION].find({"kind": "Doctor"}))
        if not doctors:
            st.info("Seed V4 data from the sidebar to create the connected graph and time series collection.")
            return
        doctor_by_id = {n["_id"]: n for n in doctors}
        root = st.selectbox("Start with a doctor", list(doctor_by_id), format_func=lambda k: doctor_by_id[k]["name"], key="v4_doctor")
    with b:
        hops = st.slider("Relationship depth", 1, 4, 2, key="v4_depth")
    with c:
        days = st.selectbox("Measurement window", [7, 14, 30], index=2, format_func=lambda d: f"Last {d} days", key="v4_days")
    categories = st.multiselect("Show relationship categories", ["Hospital", "City", "Concept", "Medical group", "Practice location", "Plan contract"],
                                default=["Hospital", "City", "Concept"], key="v4_categories")
    started = time.perf_counter()
    try:
        if preview:
            all_nodes = {n["_id"]: n for n in build_provider_graph()}
            visited, frontier = {root}, {root}
            for _ in range(hops):
                frontier = {neighbor for nid in frontier for neighbor in all_nodes[nid]["neighbors"]} - visited
                visited |= frontier
            nodes = [all_nodes[nid] for nid in sorted(visited)]
            daily = preview_daily_metrics(days)
        else:
            results = list(db[GRAPH_COLLECTION].aggregate(connected_graph_pipeline(root, hops), maxTimeMS=10000))
            nodes = []
            if results:
                first = dict(results[0])
                related = first.pop("connected", [])
                unique = {n["_id"]: n for n in [first] + related}
                nodes = list(unique.values())
            daily = list(db[METRICS_COLLECTION].aggregate(metrics_pipeline(days), maxTimeMS=10000))
    except PyMongoError as exc:
        st.error(f"Connected explorer query failed: {exc}")
        return
    # Keep the selected doctor plus requested types; do not pull other doctors
    # into the view just because they share a city, concept or hospital.
    nodes = [n for n in nodes if n["_id"] == root or n["kind"] in categories]
    visible = {n["_id"] for n in nodes}
    edge_count = sum(1 for n in nodes for e in n["links"] if e["target"] in visible)
    st.caption(f"{len(nodes)} nodes · {edge_count} relationships · {hops} hop(s) · query + preparation {(time.perf_counter()-started)*1000:.1f} ms")
    components.html(graph_html(nodes, root, daily), height=695, scrolling=True)
    st.markdown("#### Read the ontology through a real example")
    st.write("Dr. Maya Patel SPECIALIZES_IN Interventional Cardiology. That specialty IS_A Cardiovascular Disease specialty, which IS_A Cardiology. The classification explains the match; AFFILIATED_WITH and LOCATED_IN explain where care is delivered.")
    st.caption("Graph depth counts every relationship. Increase depth to reveal broader specialty categories. Category filters affect display after traversal.")
    st.markdown("#### Hospital trends")
    # Independent selector intentionally provides the same metrics in accessible native charts.
    hospitals = HOSPITALS if preview else list(db[FACILITY_COLLECTION].find({}))
    if not hospitals:
        st.info("No hospitals seeded.")
        return
    hospital_by_id = {h["_id"]: h for h in hospitals}
    hid = st.selectbox("Facility for detailed charts", list(hospital_by_id), format_func=lambda k: hospital_by_id[k]["name"], key="v4_facility")
    st.caption("Clicking a hospital in the graph updates its embedded detail panel. This selector independently controls the charts below. Dates use America/Chicago.")
    frame = pd.DataFrame([r for r in daily if r["hospitalId"] == hid])
    if not frame.empty:
        frame = frame.sort_values("day").set_index("day")
        latest = frame.iloc[-1]
        m1, m2, m3 = st.columns(3)
        m1.metric("Latest daily avg occupancy", f"{latest['occupancyPct']:.1f}%")
        m2.metric("Latest daily avg ED wait", f"{latest['edWaitMinutes']:.1f} min")
        m3.metric("Arrivals in selected window", f"{int(frame['arrivals'].sum()):,}")
        left, right = st.columns(2)
        with left:
            st.caption("Daily average ED wait · minutes")
            st.line_chart(frame[["edWaitMinutes"]])
        with right:
            st.caption("Daily average occupied beds · percent")
            st.line_chart(frame[["occupancyPct"]])
        st.caption("Hourly measurements are grouped into local calendar days; boundary days may be partial.")
        with st.expander("Daily measurements"):
            st.dataframe(frame.drop(columns=["hospitalId"]), use_container_width=True)
    else:
        st.info("No measurements in this date range. Reseed to refresh the rolling synthetic history.")
    with st.expander("How this consolidates the application"):
        st.table(pd.DataFrame([
            {"Workload": "Provider directory and relationships", "MongoDB storage": "Regular documents + provider_graph", "Demo operation": "Document reads and $graphLookup"},
            {"Workload": "Semantic provider / document discovery", "MongoDB storage": "Regular collections + automated embedding indexes", "Demo operation": "Existing patient search and architecture copilot"},
            {"Workload": "Hospital measurements over time", "MongoDB storage": "Native hospital_metrics time series collection", "Demo operation": "$match → $group → daily charts"},
        ]))
        st.write("Shared IDs connect the workloads in one application. Search runs on regular collections; time series stores numeric observations. Native time series collections do not support Search indexes or change streams. Keep searchable narrative and current-state / alert documents in regular collections when those capabilities are needed.")
        st.caption("This demo illustrates consolidation patterns; replacing existing systems still depends on their query, retention and throughput requirements.")
    with st.expander("MongoDB pipelines and measurement shape"):
        st.code(json.dumps(connected_graph_pipeline(root, hops), indent=2), language="json")
        st.code(json.dumps(metrics_pipeline(days), indent=2, default=str), language="json")
        st.code(json.dumps(build_metric_samples()[-1], indent=2, default=str), language="json")
        st.code('db.create_collection("hospital_metrics", timeseries={"timeField": "timestamp", "metaField": "metadata", "granularity": "hours"})', language="python")
        st.caption("The graph collection contains a projection of provider and concept documents. Reseeding refreshes it; production applications need an explicit projection update strategy.")



def seed_demo():
    if (
        healthcare_collection is None
        or ontology_collection is None
        or providers_collection is None
        or domain_documents_collection is None
        or architecture_collection is None
    ):
        add_log("ERROR Atlas connection not configured")
        return False

    started = time.perf_counter()

    try:
        ontology_documents = (
            build_ontology_documents()
        )

        ontology_collection.delete_many({})
        healthcare_collection.delete_many({})
        providers_collection.delete_many({})
        domain_documents_collection.delete_many({})
        architecture_collection.delete_many({})

        ontology_collection.insert_many(
            ontology_documents,
            ordered=False,
        )

        healthcare_collection.insert_many(
            HEALTHCARE_DOCUMENTS,
            ordered=False,
        )

        providers_collection.insert_many(
            PROVIDER_DOCUMENTS,
            ordered=False,
        )

        domain_documents_collection.insert_many(
            DOMAIN_DOCUMENTS,
            ordered=False,
        )

        architecture_collection.insert_many(
            ARCHITECTURE_NODES,
            ordered=False,
        )

        ontology_collection.create_index(
            [("parentId", ASCENDING)]
        )
        ontology_collection.create_index(
            [("name", ASCENDING)]
        )
        ontology_collection.create_index(
            [("code", ASCENDING)]
        )

        healthcare_collection.create_index(
            [("conceptId", ASCENDING)]
        )

        providers_collection.create_index(
            [("specialtyConceptIds", ASCENDING)]
        )
        providers_collection.create_index(
            [("taxEntities.taxId", ASCENDING)]
        )
        providers_collection.create_index(
            [("taxEntities.locations.locationId", ASCENDING)]
        )
        providers_collection.create_index(
            [("taxEntities.locations.address.city", ASCENDING)]
        )
        providers_collection.create_index(
            [("taxEntities.locations.languages", ASCENDING)]
        )
        providers_collection.create_index(
            [("taxEntities.locations.planContracts.planId", ASCENDING)]
        )

        domain_documents_collection.create_index(
            [("architectureNodeIds", ASCENDING)]
        )
        architecture_collection.create_index(
            [("dependsOn", ASCENDING)]
        )

        add_log(
            f"LOAD ontology documents="
            f"{len(ontology_documents)}"
        )
        add_log(
            f"LOAD healthcare documents="
            f"{len(HEALTHCARE_DOCUMENTS)}"
        )

        add_log(
            f"LOAD provider documents="
            f"{len(PROVIDER_DOCUMENTS)}"
        )
        add_log(
            f"LOAD domain documents="
            f"{len(DOMAIN_DOCUMENTS)}"
        )
        add_log(
            f"LOAD architecture nodes="
            f"{len(ARCHITECTURE_NODES)}"
        )

        seed_connected_data()

        create_auto_embedding_index(
            healthcare_collection,
            VECTOR_INDEX_NAME,
        )
        create_auto_embedding_index(
            domain_documents_collection,
            ARCHITECTURE_VECTOR_INDEX_NAME,
        )

        elapsed = time.perf_counter() - started

        st.session_state.last_action = (
            "SEED V4 + GRAPH + TIME SERIES"
        )
        st.session_state.last_latency = elapsed
        st.session_state.semantic_results = []
        st.session_state.matched_concept_id = None
        st.session_state.provider_matches = []
        st.session_state.provider_pipeline = []
        st.session_state.architecture_results = []
        st.session_state.architecture_graph = []

        add_log(
            f"OK seed completed latency={elapsed:.3f}s"
        )

        return True

    except PyMongoError as exc:
        add_log(f"ERROR seed failed: {exc}")
        st.error(f"Seed failed: {exc}")
        return False


def reset_demo():
    if (
        healthcare_collection is None
        or ontology_collection is None
        or providers_collection is None
        or domain_documents_collection is None
        or architecture_collection is None
    ):
        return False

    started = time.perf_counter()

    try:
        ontology_collection.delete_many({})
        healthcare_collection.delete_many({})
        providers_collection.delete_many({})
        domain_documents_collection.delete_many({})
        architecture_collection.delete_many({})
        db[GRAPH_COLLECTION].delete_many({})
        db[FACILITY_COLLECTION].delete_many({})
        if METRICS_COLLECTION in db.list_collection_names():
            db[METRICS_COLLECTION].delete_many({"metadata.demoSource": DEMO_SOURCE})

        elapsed = time.perf_counter() - started

        st.session_state.semantic_results = []
        st.session_state.matched_concept_id = None
        st.session_state.provider_matches = []
        st.session_state.provider_pipeline = []
        st.session_state.architecture_results = []
        st.session_state.architecture_graph = []
        st.session_state.last_action = "RESET DATA"
        st.session_state.last_latency = elapsed

        add_log(
            f"OK reset completed latency={elapsed:.3f}s"
        )

        return True

    except PyMongoError as exc:
        add_log(f"ERROR reset failed: {exc}")
        return False


# ============================================================
# TWO-STEP QUERY PIPELINES
# ============================================================

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


def run_vector_search(query_text):
    pipeline = vector_search_pipeline(
        query_text
    )

    started = time.perf_counter()

    results = list(
        healthcare_collection.aggregate(pipeline)
    )

    elapsed = time.perf_counter() - started

    st.session_state.last_action = (
        "VECTOR SEARCH"
    )
    st.session_state.last_latency = elapsed

    add_log(
        f"VECTOR query={query_text!r}"
    )
    add_log(
        f"VECTOR matches={len(results)} "
        f"latency={elapsed:.3f}s"
    )

    return results


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


def get_ontology_context(concept_id):
    started = time.perf_counter()

    ancestor_results = list(
        ontology_collection.aggregate(
            ancestor_pipeline(concept_id)
        )
    )

    descendant_results = list(
        ontology_collection.aggregate(
            descendant_pipeline(concept_id)
        )
    )

    elapsed = time.perf_counter() - started

    concept = (
        ancestor_results[0]
        if ancestor_results
        else None
    )

    descendants = (
        descendant_results[0].get(
            "descendants",
            [],
        )
        if descendant_results
        else []
    )

    add_log(
        f"GRAPH concept={concept_id} "
        f"latency={elapsed:.3f}s"
    )

    return concept, descendants, elapsed


# ============================================================
# LOCATION-LEVEL PROVIDER SEARCH + COST ESTIMATION
# ============================================================

def get_matchable_concept_ids(concept_id):
    """Include the selected concept and every descendant specialty."""
    results = list(
        ontology_collection.aggregate(
            descendant_pipeline(concept_id)
        )
    )

    descendants = (
        results[0].get("descendants", [])
        if results
        else []
    )

    return [concept_id] + [
        item["_id"]
        for item in descendants
    ]


def provider_location_pipeline(
    concept_ids,
    city,
    language,
    plan_id,
    accepting_only,
):
    location_match = {
        "taxEntities.locations.specialtyConceptIds": {
            "$in": concept_ids,
        },
        "taxEntities.locations.address.city": city,
    }

    if language != "Any":
        location_match[
            "taxEntities.locations.languages"
        ] = language

    if accepting_only:
        location_match[
            "taxEntities.locations.acceptingNewPatients"
        ] = True

    return [
        {
            "$unwind": "$taxEntities",
        },
        {
            "$unwind": "$taxEntities.locations",
        },
        {
            "$match": location_match,
        },
        {
            "$set": {
                "selectedPlan": {
                    "$first": {
                        "$filter": {
                            "input": "$taxEntities.locations.planContracts",
                            "as": "plan",
                            "cond": {
                                "$eq": [
                                    "$$plan.planId",
                                    plan_id,
                                ]
                            },
                        }
                    }
                }
            }
        },
        {
            "$match": {
                "selectedPlan": {
                    "$ne": None,
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "providerId": "$_id",
                "npi": 1,
                "providerName": "$name",
                "credentials": 1,
                "taxId": "$taxEntities.taxId",
                "legalName": "$taxEntities.legalName",
                "location": "$taxEntities.locations",
                "selectedPlan": 1,
            }
        },
        {
            "$sort": {
                "providerName": 1,
                "location.name": 1,
            }
        },
    ]


def find_provider_locations(
    concept_id,
    city,
    language,
    plan_id,
    accepting_only,
):
    concept_ids = get_matchable_concept_ids(
        concept_id
    )

    pipeline = provider_location_pipeline(
        concept_ids,
        city,
        language,
        plan_id,
        accepting_only,
    )

    started = time.perf_counter()

    results = list(
        providers_collection.aggregate(pipeline)
    )

    elapsed = time.perf_counter() - started

    add_log(
        f"LOCATION concept={concept_id} city={city} "
        f"language={language} plan={plan_id} "
        f"matches={len(results)} latency={elapsed:.3f}s"
    )

    return results, pipeline, elapsed


def estimate_patient_cost(
    service,
    deductible_remaining,
    out_of_pocket_remaining,
):
    allowed = float(
        service.get("allowedAmount", 0)
    )
    copay = min(
        float(service.get("copay", 0)),
        allowed,
    )
    remaining = max(
        allowed - copay,
        0,
    )

    deductible = 0.0
    if service.get("deductibleApplies"):
        deductible = min(
            remaining,
            float(deductible_remaining),
        )

    coinsurance_base = max(
        remaining - deductible,
        0,
    )
    coinsurance = round(
        coinsurance_base
        * float(service.get("coinsurance", 0)),
        2,
    )

    estimate_before_oop = round(
        copay + deductible + coinsurance,
        2,
    )

    estimated_responsibility = min(
        estimate_before_oop,
        float(out_of_pocket_remaining),
    )

    return {
        "allowedAmount": allowed,
        "copay": copay,
        "deductibleApplied": deductible,
        "coinsurance": coinsurance,
        "outOfPocketRemaining": float(
            out_of_pocket_remaining
        ),
        "estimatedResponsibility": round(
            estimated_responsibility,
            2,
        ),
    }


# ============================================================
# ARCHITECTURE DOCUMENT SEARCH + KNOWLEDGE GRAPH
# ============================================================

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


def run_architecture_copilot(query_text):
    started = time.perf_counter()

    documents = list(
        domain_documents_collection.aggregate(
            architecture_search_pipeline(
                query_text
            )
        )
    )

    node_ids = sorted(
        {
            node_id
            for document in documents
            for node_id in document.get(
                "architectureNodeIds",
                [],
            )
        }
    )

    graph = (
        list(
            architecture_collection.aggregate(
                architecture_graph_pipeline(
                    node_ids
                )
            )
        )
        if node_ids
        else []
    )

    elapsed = time.perf_counter() - started

    add_log(
        f"ARCH query={query_text!r} docs={len(documents)} "
        f"nodes={len(node_ids)} latency={elapsed:.3f}s"
    )

    return documents, graph, elapsed


def build_architecture_answer(documents, graph):
    if not documents:
        return "No supporting architecture documents were found."

    top_document = documents[0]

    starting_nodes = {
        item["_id"]: item
        for item in graph
    }

    impacted = {}
    dependencies = {}

    for item in graph:
        for node in item.get("downstream", []):
            impacted[node["_id"]] = node
        for node in item.get("upstream", []):
            dependencies[node["_id"]] = node

    source_names = [
        item.get("name", item_id)
        for item_id, item in starting_nodes.items()
    ]
    impacted_names = sorted(
        node.get("name", node_id)
        for node_id, node in impacted.items()
        if node_id not in starting_nodes
    )
    dependency_names = sorted(
        node.get("name", node_id)
        for node_id, node in dependencies.items()
        if node_id not in starting_nodes
    )

    answer_parts = [
        (
            f"The strongest current-state evidence is "
            f"'{top_document.get('title')}' owned by "
            f"{top_document.get('owner')}."
        ),
        top_document.get("searchText", ""),
    ]

    if source_names:
        answer_parts.append(
            "Relevant architecture nodes: "
            + ", ".join(sorted(source_names))
            + "."
        )

    if impacted_names:
        answer_parts.append(
            "Potential downstream impact: "
            + ", ".join(impacted_names)
            + "."
        )

    if dependency_names:
        answer_parts.append(
            "Upstream dependencies: "
            + ", ".join(dependency_names)
            + "."
        )

    return " ".join(answer_parts)


# ============================================================
# DEEP PURPLE CSS
# ============================================================

st.markdown(
    """
<style>
:root {
    --bg: #100719;
    --panel: #1b0d2a;
    --panel2: #27123c;
    --border: #57327c;
    --accent: #a970ff;
    --bright: #c7a4ff;
    --text: #f5efff;
    --muted: #b8a5cf;
    --green: #56f2b3;
    --red: #ff6b9e;
}

header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
#MainMenu,
footer {
    display: none !important;
}

html,
body,
[data-testid="stAppViewContainer"],
.stApp {
    background:
        radial-gradient(
            circle at top right,
            rgba(115, 61, 170, 0.25),
            transparent 32%
        ),
        linear-gradient(
            145deg,
            #0d0614,
            #170923,
            #210e32
        ) !important;
    color: var(--text) !important;
}

[data-testid="stSidebar"] {
    background:
        linear-gradient(
            180deg,
            #170a24,
            #210f34
        ) !important;
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] * {
    color: var(--text);
}

.block-container {
    max-width: 1500px;
    padding-top: 1.3rem;
}

.retro-title {
    padding: 18px 22px;
    margin-bottom: 13px;
    border: 1px solid var(--accent);
    border-left: 7px solid var(--accent);
    background: rgba(72, 31, 108, 0.42);
    color: var(--text);
    font: 700 24px "Courier New", monospace;
    letter-spacing: 1.2px;
}

.section-title {
    margin: 16px 0 10px;
    padding: 8px 12px;
    border-left: 4px solid var(--accent);
    background: rgba(169, 112, 255, 0.09);
    color: var(--bright);
    font: 700 14px "Courier New", monospace;
    letter-spacing: 1px;
}

.status-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
    padding: 11px 14px;
    border: 1px solid var(--border);
    background: rgba(27, 13, 42, 0.88);
    font: 13px "Courier New", monospace;
}

.metric-card {
    min-height: 105px;
    padding: 15px;
    border: 1px solid var(--border);
    border-top: 4px solid var(--accent);
    border-radius: 5px;
    background:
        linear-gradient(
            145deg,
            rgba(39, 18, 60, 0.98),
            rgba(24, 11, 37, 0.98)
        );
}

.metric-label {
    color: var(--muted);
    font: 12px "Courier New", monospace;
}

.metric-value {
    margin-top: 8px;
    color: var(--text);
    font: 700 25px "Courier New", monospace;
}

.path-node {
    padding: 11px 14px;
    border: 1px solid var(--border);
    border-left: 5px solid var(--accent);
    border-radius: 4px;
    background: rgba(38, 17, 58, 0.9);
    color: var(--text);
    font-family: "Courier New", monospace;
}

.path-arrow {
    padding-left: 19px;
    color: var(--accent);
    font-size: 18px;
}

.log-window {
    height: 230px;
    overflow-y: auto;
    padding: 13px;
    border: 1px solid var(--border);
    background: #09040e;
    color: #d9c5f5;
    font: 12px/1.55 "Courier New", monospace;
    white-space: pre-wrap;
}

.connected {
    color: var(--green) !important;
    font-family: "Courier New", monospace;
}

.disconnected {
    color: var(--red) !important;
    font-family: "Courier New", monospace;
}

div.stButton > button {
    min-height: 42px;
    border: 1px solid var(--accent) !important;
    background:
        linear-gradient(
            145deg,
            #3a1b57,
            #251036
        ) !important;
    color: var(--text) !important;
    font-family: "Courier New", monospace;
    font-weight: 700;
}

div.stButton > button:hover {
    border-color: var(--bright) !important;
    background: #51277a !important;
}

div[data-baseweb="input"] > div,
.stTextInput input {
    border-color: var(--border) !important;
    background-color: #180b25 !important;
    color: var(--text) !important;
}

[data-testid="stDataFrame"],
[data-testid="stExpander"] {
    border: 1px solid var(--border);
}

.stTabs [data-baseweb="tab"] {
    color: var(--muted);
}

.stTabs [aria-selected="true"] {
    color: var(--text) !important;
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# STATUS
# ============================================================

atlas_connected, atlas_message = atlas_status()

healthcare_count = collection_count(
    healthcare_collection
)

ontology_count = collection_count(
    ontology_collection
)

provider_count = collection_count(
    providers_collection
)

domain_document_count = collection_count(
    domain_documents_collection
)

architecture_count = collection_count(
    architecture_collection
)

clinical_index_status = (
    get_vector_index_status(
        healthcare_collection,
        VECTOR_INDEX_NAME,
    )
    if atlas_connected
    else {
        "exists": False,
        "ready": False,
        "status": "DISCONNECTED",
    }
)

architecture_index_status = (
    get_vector_index_status(
        domain_documents_collection,
        ARCHITECTURE_VECTOR_INDEX_NAME,
    )
    if atlas_connected
    else {
        "exists": False,
        "ready": False,
        "status": "DISCONNECTED",
    }
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## PROVIDER INTELLIGENCE LAB")
    st.markdown("`app5 / v5`")
    st.markdown("---")

    if atlas_connected:
        st.markdown(
            '<span class="connected">'
            "● ATLAS CONNECTED"
            "</span>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="disconnected">'
            "● ATLAS DISCONNECTED"
            "</span>",
            unsafe_allow_html=True,
        )

    if client is None:
        st.caption(
            "Paste your connection string into the Atlas connection form above."
        )
    elif not atlas_connected:
        st.error(atlas_message)

    st.markdown("---")
    st.markdown("**DEMO CONTROL**")

    if st.button(
        "[S] SEED V4 + GRAPH + TIME SERIES",
        use_container_width=True,
        disabled=not atlas_connected,
    ):
        if seed_demo():
            st.rerun()

    if st.button(
        "[I] REFRESH INDEX STATUS",
        use_container_width=True,
        disabled=not atlas_connected,
    ):
        st.rerun()

    if st.button(
        "[R] RESET DEMO DATA",
        use_container_width=True,
        disabled=not atlas_connected,
    ):
        if reset_demo():
            st.rerun()

    st.markdown("---")
    st.caption(f"Model: {EMBEDDING_MODEL}")
    st.caption(
        f"Clinical: {VECTOR_INDEX_NAME}"
    )
    st.caption(
        f"Status: {clinical_index_status['status']}"
    )
    st.caption(
        f"Architecture: {ARCHITECTURE_VECTOR_INDEX_NAME}"
    )
    st.caption(
        f"Status: {architecture_index_status['status']}"
    )
    st.caption(
        "Index creation and embedding are asynchronous."
    )


# ============================================================
# HEADER
# ============================================================

st.markdown(
    """
<div class="retro-title">
| PROVIDER INTELLIGENCE / VECTOR SEARCH / KNOWLEDGE GRAPH |
</div>
""",
    unsafe_allow_html=True,
)

latency_text = (
    f"{st.session_state.last_latency:.3f}s"
    if st.session_state.last_latency is not None
    else "N/A"
)

st.markdown(
    f"""
<div class="status-bar">
    <span>ATLAS: {"CONNECTED" if atlas_connected else "DISCONNECTED"}</span>
    <span>HEALTHCARE: {healthcare_count}</span>
    <span>CONCEPTS: {ontology_count}</span>
    <span>PROVIDERS: {provider_count}</span>
    <span>DOMAIN DOCS: {domain_document_count}</span>
    <span>CLINICAL INDEX: {html.escape(clinical_index_status["status"])}</span>
    <span>ARCH INDEX: {html.escape(architecture_index_status["status"])}</span>
    <span>LAST LATENCY: {latency_text}</span>
</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# EMPTY STATE
# ============================================================

if (
    healthcare_count == 0
    or ontology_count == 0
    or provider_count == 0
    or domain_document_count == 0
    or architecture_count == 0
):
    st.info(
        "Click [S] SEED V4 + GRAPH + TIME SERIES to create the isolated "
        "V4 collections, connected care graph, native time series, and both automated embedding indexes."
    )

    a, b, c, d = st.columns(4)

    with a:
        st.markdown(
            """
<div class="metric-card">
    <div class="metric-label">STEP 1</div>
    <div class="metric-value">Vector Search</div>
    <div class="metric-label">Understand natural-language intent</div>
</div>
""",
            unsafe_allow_html=True,
        )

    with b:
        st.markdown(
            """
<div class="metric-card">
    <div class="metric-label">STEP 2</div>
    <div class="metric-value">Concept ID</div>
    <div class="metric-label">Connect semantic results to ontology</div>
</div>
""",
            unsafe_allow_html=True,
        )

    with c:
        st.markdown(
            """
<div class="metric-card">
    <div class="metric-label">STEP 3</div>
    <div class="metric-value">$graphLookup</div>
    <div class="metric-label">Traverse deterministic relationships</div>
</div>
""",
            unsafe_allow_html=True,
        )

    with d:
        st.markdown(
            """
<div class="metric-card">
    <div class="metric-label">STEP 4</div>
    <div class="metric-value">Knowledge Graph</div>
    <div class="metric-label">Trace current-state architecture impact</div>
</div>
""",
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="section-title">ACTIVITY LOG</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="log-window">'
        + html.escape(
            "\n".join(st.session_state.logs)
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    render_connected_explorer(preview=True)
    st.stop()


# ============================================================
# DEMO QUERY
# ============================================================

(
    connected_tab,
    demo_tab,
    provider_structure_tab,
    location_tab,
    architecture_tab,
    pipeline_tab,
    data_tab,
) = st.tabs(
    [
        "CONNECTED CARE GRAPH",
        "PATIENT SEARCH",
        "PROVIDER STRUCTURE",
        "LOCATION EXPLORER",
        "ARCHITECTURE COPILOT",
        "PIPELINES",
        "SEEDED DATA",
    ]
)

with connected_tab:
    render_connected_explorer()

with demo_tab:
    st.markdown(
        '<div class="section-title">'
        "NATURAL-LANGUAGE HEALTHCARE SEARCH"
        "</div>",
        unsafe_allow_html=True,
    )

    query_text = st.text_input(
        "Describe the healthcare provider you need",
        value=st.session_state.query_text,
        placeholder=(
            "Example: I need a doctor who performs "
            "heart catheterization"
        ),
    )

    st.session_state.query_text = query_text

    filter_a, filter_b, filter_c, filter_d = st.columns(4)

    with filter_a:
        patient_city = st.selectbox(
            "City",
            ["Chicago", "Evanston", "Oak Brook"],
        )

    with filter_b:
        patient_language = st.selectbox(
            "Spoken language",
            [
                "Spanish",
                "Any",
                "English",
                "Arabic",
                "Hindi",
                "Mandarin",
            ],
        )

    with filter_c:
        selected_plan_id = st.selectbox(
            "Health plan",
            [
                "choice-plus",
                "medicare-advantage",
            ],
            format_func=lambda value: {
                "choice-plus": "Choice Plus PPO",
                "medicare-advantage": "Medicare Advantage",
            }[value],
        )

    with filter_d:
        accepting_only = st.checkbox(
            "Accepting new patients",
            value=True,
        )

    cost_a, cost_b = st.columns(2)

    with cost_a:
        deductible_remaining = st.number_input(
            "Deductible remaining",
            min_value=0.0,
            value=500.0,
            step=50.0,
            format="%.2f",
        )

    with cost_b:
        out_of_pocket_remaining = st.number_input(
            "Out-of-pocket maximum remaining",
            min_value=0.0,
            value=2500.0,
            step=100.0,
            format="%.2f",
        )

    run_search = st.button(
        "RUN VECTOR SEARCH + GRAPH LOOKUP",
        use_container_width=True,
        disabled=not clinical_index_status["ready"],
    )

    if not clinical_index_status["ready"]:
        st.warning(
            "The Automated Embedding index is not queryable yet. "
            "Wait for its status to become READY, then click "
            "[I] REFRESH INDEX STATUS."
        )

    if run_search:
        try:
            with st.spinner(
                "Running semantic search and ontology traversal..."
            ):
                results = run_vector_search(
                    query_text
                )

                st.session_state.semantic_results = (
                    results
                )

                st.session_state.matched_concept_id = (
                    results[0]["conceptId"]
                    if results
                    else None
                )

        except PyMongoError as exc:
            add_log(
                f"ERROR vector search failed: {exc}"
            )
            st.error(
                f"Vector Search failed: {exc}"
            )

    vector_results = (
        st.session_state.semantic_results
    )

    matched_concept_id = (
        st.session_state.matched_concept_id
    )

    if vector_results and matched_concept_id:
        try:
            (
                provider_matches,
                provider_pipeline,
                _,
            ) = find_provider_locations(
                matched_concept_id,
                patient_city,
                patient_language,
                selected_plan_id,
                accepting_only,
            )

            st.session_state.provider_matches = (
                provider_matches
            )
            st.session_state.provider_pipeline = (
                provider_pipeline
            )
        except PyMongoError as exc:
            add_log(
                f"ERROR provider location search failed: {exc}"
            )
            st.session_state.provider_matches = []
            st.error(
                f"Provider location search failed: {exc}"
            )

    if vector_results:
        st.markdown(
            '<div class="section-title">'
            "STEP 1 / VECTOR SEARCH RESULTS"
            "</div>",
            unsafe_allow_html=True,
        )

        result_rows = [
            {
                "Rank": index + 1,
                "Matched intent": item["title"],
                "Concept ID": item["conceptId"],
                "Score": round(
                    item.get("score", 0),
                    4,
                ),
            }
            for index, item in enumerate(
                vector_results
            )
        ]

        st.dataframe(
            pd.DataFrame(result_rows),
            use_container_width=True,
            hide_index=True,
        )

        top_match = vector_results[0]

        st.success(
            f"Top semantic match: {top_match['title']} "
            f"→ {top_match['conceptId']}"
        )

        concept, descendants, graph_latency = (
            get_ontology_context(
                matched_concept_id
            )
        )

        if concept:
            ancestors = sorted(
                concept.get("ancestors", []),
                key=lambda item: item.get(
                    "traversalDepth",
                    0,
                ),
                reverse=True,
            )

            selected_concept = {
                key: value
                for key, value in concept.items()
                if key != "ancestors"
            }

            hierarchy = (
                ancestors
                + [selected_concept]
            )

            st.markdown(
                '<div class="section-title">'
                "STEP 2 / $GRAPHLOOKUP ONTOLOGY PATH"
                "</div>",
                unsafe_allow_html=True,
            )

            left, right = st.columns(
                [1.05, 1],
                gap="large",
            )

            with left:
                for index, node in enumerate(
                    hierarchy
                ):
                    selected = (
                        node.get("_id")
                        == matched_concept_id
                    )

                    marker = (
                        "VECTOR MATCH"
                        if selected
                        else f"LEVEL {index}"
                    )

                    st.markdown(
                        f"""
<div class="path-node">
{html.escape(marker)} ::
{html.escape(node.get("name", ""))}
[{html.escape(node.get("code", ""))}]
</div>
""",
                        unsafe_allow_html=True,
                    )

                    if index < len(hierarchy) - 1:
                        st.markdown(
                            '<div class="path-arrow">↓</div>',
                            unsafe_allow_html=True,
                        )

            with right:
                st.markdown(
                    f"### {concept.get('name')}"
                )
                st.write(
                    concept.get("description")
                )

                st.write(
                    "Synonyms:",
                    ", ".join(
                        concept.get(
                            "synonyms",
                            [],
                        )
                    ),
                )

                st.metric(
                    "Vector similarity",
                    f"{top_match.get('score', 0):.4f}",
                )

                st.metric(
                    "$graphLookup latency",
                    f"{graph_latency * 1000:.2f} ms",
                )

                if descendants:
                    descendant_rows = [
                        {
                            "Name": item.get("name"),
                            "Code": item.get("code"),
                            "Depth": (
                                item.get(
                                    "traversalDepth",
                                    0,
                                )
                                + 1
                            ),
                        }
                        for item in sorted(
                            descendants,
                            key=lambda item: (
                                item.get(
                                    "traversalDepth",
                                    0,
                                ),
                                item.get("name", ""),
                            ),
                        )
                    ]

                    st.markdown(
                        "#### Descendant concepts"
                    )

                    st.dataframe(
                        pd.DataFrame(
                            descendant_rows
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

        provider_matches = (
            st.session_state.provider_matches
        )

        st.markdown(
            '<div class="section-title">'
            "STEP 3 / LOCATION + PLAN MATCHES"
            "</div>",
            unsafe_allow_html=True,
        )

        if provider_matches:
            service_map = {}

            for match in provider_matches:
                for service in match.get(
                    "selectedPlan",
                    {},
                ).get("services", []):
                    service_map[
                        service["serviceCode"]
                    ] = service

            selected_service_code = st.selectbox(
                "Service for cost estimate",
                options=list(service_map),
                format_func=lambda code: (
                    f"{code} — "
                    f"{service_map[code]['label']}"
                ),
            )

            provider_rows = []

            for match in provider_matches:
                location = match["location"]
                plan = match["selectedPlan"]

                selected_service = next(
                    (
                        service
                        for service in plan.get(
                            "services",
                            [],
                        )
                        if service.get(
                            "serviceCode"
                        ) == selected_service_code
                    ),
                    None,
                )

                if not selected_service:
                    continue

                cost = estimate_patient_cost(
                    selected_service,
                    deductible_remaining,
                    out_of_pocket_remaining,
                )

                provider_rows.append(
                    {
                        "Provider": match[
                            "providerName"
                        ],
                        "Tax ID": match["taxId"],
                        "Location": location["name"],
                        "City": location[
                            "address"
                        ]["city"],
                        "New patients": (
                            "Yes"
                            if location.get(
                                "acceptingNewPatients"
                            )
                            else "No"
                        ),
                        "Languages": ", ".join(
                            location.get(
                                "languages",
                                [],
                            )
                        ),
                        "Plan": plan["planName"],
                        "Network": plan[
                            "networkStatus"
                        ],
                        "Allowed": (
                            f"${cost['allowedAmount']:,.2f}"
                        ),
                        "Est. patient cost": (
                            f"${cost['estimatedResponsibility']:,.2f}"
                        ),
                    }
                )

            if provider_rows:
                st.dataframe(
                    pd.DataFrame(provider_rows),
                    use_container_width=True,
                    hide_index=True,
                )

                detail_match = next(
                    match
                    for match in provider_matches
                    if any(
                        service["serviceCode"]
                        == selected_service_code
                        for service in match[
                            "selectedPlan"
                        ]["services"]
                    )
                )
                detail_service = next(
                    service
                    for service in detail_match[
                        "selectedPlan"
                    ]["services"]
                    if service["serviceCode"]
                    == selected_service_code
                )
                detail_cost = estimate_patient_cost(
                    detail_service,
                    deductible_remaining,
                    out_of_pocket_remaining,
                )

                metric_a, metric_b, metric_c, metric_d = (
                    st.columns(4)
                )

                metric_a.metric(
                    "Copay",
                    f"${detail_cost['copay']:,.2f}",
                )
                metric_b.metric(
                    "Deductible applied",
                    f"${detail_cost['deductibleApplied']:,.2f}",
                )
                metric_c.metric(
                    "Coinsurance",
                    f"${detail_cost['coinsurance']:,.2f}",
                )
                metric_d.metric(
                    "Estimated responsibility",
                    f"${detail_cost['estimatedResponsibility']:,.2f}",
                )

                st.caption(
                    "Illustrative pre-service estimate only. Actual "
                    "patient responsibility depends on eligibility, "
                    "authorization, accumulated benefits, claim coding, "
                    "and final adjudication."
                )
            else:
                st.warning(
                    "The matching locations do not price the selected service."
                )
        else:
            st.warning(
                "The specialty was identified, but no location matched all "
                "selected city, language, new-patient, and plan criteria."
            )


# ============================================================
# NESTED PROVIDER STRUCTURE
# ============================================================

with provider_structure_tab:
    st.markdown(
        '<div class="section-title">'
        "ONE PROVIDER / MULTIPLE TAX IDS / MULTIPLE LOCATIONS"
        "</div>",
        unsafe_allow_html=True,
    )

    provider_summaries = list(
        providers_collection.find(
            {},
            {
                "_id": 1,
                "name": 1,
                "npi": 1,
            },
        ).sort("name", ASCENDING)
    )

    selected_provider_id = st.selectbox(
        "Provider",
        options=[
            item["_id"]
            for item in provider_summaries
        ],
        format_func=lambda provider_id: next(
            item["name"]
            for item in provider_summaries
            if item["_id"] == provider_id
        ),
    )

    provider_document = providers_collection.find_one(
        {
            "_id": selected_provider_id,
        }
    )

    tax_entities = provider_document.get(
        "taxEntities",
        [],
    )
    location_total = sum(
        len(entity.get("locations", []))
        for entity in tax_entities
    )
    plan_total = sum(
        len(location.get("planContracts", []))
        for entity in tax_entities
        for location in entity.get("locations", [])
    )

    structure_a, structure_b, structure_c, structure_d = (
        st.columns(4)
    )
    structure_a.metric(
        "Provider",
        provider_document["name"],
    )
    structure_b.metric(
        "Tax IDs",
        len(tax_entities),
    )
    structure_c.metric(
        "Practice locations",
        location_total,
    )
    structure_d.metric(
        "Location plan contracts",
        plan_total,
    )

    relationship_rows = []

    for entity in tax_entities:
        for location in entity.get(
            "locations",
            [],
        ):
            relationship_rows.append(
                {
                    "Provider": provider_document["name"],
                    "Tax ID": entity["taxId"],
                    "Legal entity": entity["legalName"],
                    "Location ID": location["locationId"],
                    "Practice location": location["name"],
                    "City": location["address"]["city"],
                    "New patients": location[
                        "acceptingNewPatients"
                    ],
                    "Languages": ", ".join(
                        location["languages"]
                    ),
                    "Plans": ", ".join(
                        plan["planName"]
                        for plan in location[
                            "planContracts"
                        ]
                    ),
                }
            )

    st.dataframe(
        pd.DataFrame(relationship_rows),
        use_container_width=True,
        hide_index=True,
    )

    st.info(
        "The Tax ID and location relationships remain inside the same "
        "provider document. Location attributes cannot be accidentally "
        "combined with a different Tax ID or practice location."
    )

    with st.expander(
        "View the complete nested BSON document",
        expanded=True,
    ):
        st.json(provider_document)


# ============================================================
# LOCATION EXPLORER
# ============================================================

with location_tab:
    st.markdown(
        '<div class="section-title">'
        "LOCATION-LEVEL ATTRIBUTES + CLINICAL GRAPH"
        "</div>",
        unsafe_allow_html=True,
    )

    flattened_locations = list(
        providers_collection.aggregate(
            [
                {
                    "$unwind": "$taxEntities",
                },
                {
                    "$unwind": "$taxEntities.locations",
                },
                {
                    "$project": {
                        "_id": 0,
                        "providerId": "$_id",
                        "providerName": "$name",
                        "npi": 1,
                        "taxId": "$taxEntities.taxId",
                        "legalName": "$taxEntities.legalName",
                        "location": "$taxEntities.locations",
                    }
                },
                {
                    "$sort": {
                        "providerName": 1,
                        "location.name": 1,
                    }
                },
            ]
        )
    )

    selected_location_id = st.selectbox(
        "Practice location",
        options=[
            item["location"]["locationId"]
            for item in flattened_locations
        ],
        format_func=lambda location_id: next(
            (
                f"{item['providerName']} — "
                f"{item['location']['name']} "
                f"({item['location']['address']['city']})"
            )
            for item in flattened_locations
            if item["location"]["locationId"]
            == location_id
        ),
    )

    selected_location = next(
        item
        for item in flattened_locations
        if item["location"]["locationId"]
        == selected_location_id
    )

    location = selected_location["location"]

    location_a, location_b = st.columns(
        [1, 1.15],
        gap="large",
    )

    with location_a:
        st.markdown(
            f"### {selected_location['providerName']}"
        )
        st.write(
            f"Tax ID: `{selected_location['taxId']}`"
        )
        st.write(
            f"Location: `{location['locationId']}`"
        )
        st.write(
            f"Address: {location['address']['line1']}, "
            f"{location['address']['city']}, "
            f"{location['address']['state']} "
            f"{location['address']['zip']}"
        )
        st.write(
            "Accepting new patients:",
            "Yes"
            if location["acceptingNewPatients"]
            else "No",
        )
        st.write(
            "Languages:",
            ", ".join(location["languages"]),
        )

        hours_rows = [
            {
                "Day": day.title(),
                "Staff hours": hours,
            }
            for day, hours in location[
                "staffHours"
            ].items()
        ]

        st.dataframe(
            pd.DataFrame(hours_rows),
            use_container_width=True,
            hide_index=True,
        )

    with location_b:
        specialty_ids = location.get(
            "specialtyConceptIds",
            [],
        )

        st.markdown(
            "### Location-specific ontology"
        )

        for specialty_id in specialty_ids:
            specialty, _, _ = get_ontology_context(
                specialty_id
            )

            if not specialty:
                continue

            path = sorted(
                specialty.get("ancestors", []),
                key=lambda item: item.get(
                    "traversalDepth",
                    0,
                ),
                reverse=True,
            ) + [specialty]

            st.markdown(
                " → ".join(
                    item["name"]
                    for item in path
                )
            )

        st.markdown(
            "### Plans at this location"
        )

        plan_rows = [
            {
                "Plan": plan["planName"],
                "Network": plan[
                    "networkStatus"
                ],
                "Priced services": len(
                    plan.get("services", [])
                ),
            }
            for plan in location[
                "planContracts"
            ]
        ]

        st.dataframe(
            pd.DataFrame(plan_rows),
            use_container_width=True,
            hide_index=True,
        )

        with st.expander(
            "View exact location subdocument"
        ):
            st.json(location)


# ============================================================
# ARCHITECTURE COPILOT
# ============================================================

with architecture_tab:
    st.markdown(
        '<div class="section-title">'
        "UNSTRUCTURED DOMAIN DOCS + ARCHITECTURE KNOWLEDGE GRAPH"
        "</div>",
        unsafe_allow_html=True,
    )

    st.caption(
        "Atlas-only demo mode: Vector Search retrieves current domain "
        "evidence and $graphLookup resolves dependencies. The resulting "
        "grounding package can be passed directly to an AI agent or LLM."
    )

    architecture_query = st.text_input(
        "Ask about the current-state architecture",
        value=st.session_state.architecture_query,
        key="architecture_query_input",
    )

    st.session_state.architecture_query = (
        architecture_query
    )

    run_architecture = st.button(
        "ASK ARCHITECTURE COPILOT",
        use_container_width=True,
        disabled=not architecture_index_status[
            "ready"
        ],
    )

    if not architecture_index_status["ready"]:
        st.warning(
            "The architecture Automated Embedding index is not queryable "
            "yet. Refresh after Atlas finishes building the index."
        )

    if run_architecture:
        try:
            with st.spinner(
                "Retrieving domain evidence and traversing dependencies..."
            ):
                (
                    architecture_results,
                    architecture_graph,
                    architecture_latency,
                ) = run_architecture_copilot(
                    architecture_query
                )

                st.session_state.architecture_results = (
                    architecture_results
                )
                st.session_state.architecture_graph = (
                    architecture_graph
                )
                st.session_state.last_action = (
                    "ARCHITECTURE COPILOT"
                )
                st.session_state.last_latency = (
                    architecture_latency
                )

        except PyMongoError as exc:
            add_log(
                f"ERROR architecture search failed: {exc}"
            )
            st.error(
                f"Architecture search failed: {exc}"
            )

    architecture_results = (
        st.session_state.architecture_results
    )
    architecture_graph = (
        st.session_state.architecture_graph
    )

    if architecture_results:
        st.markdown(
            '<div class="section-title">'
            "GROUNDED RESPONSE"
            "</div>",
            unsafe_allow_html=True,
        )

        st.success(
            build_architecture_answer(
                architecture_results,
                architecture_graph,
            )
        )

        st.markdown(
            '<div class="section-title">'
            "RETRIEVED CURRENT-STATE EVIDENCE"
            "</div>",
            unsafe_allow_html=True,
        )

        evidence_rows = [
            {
                "Rank": index + 1,
                "Document": document["title"],
                "Type": document[
                    "contentType"
                ],
                "Owner": document["owner"],
                "Updated": document[
                    "lastUpdated"
                ],
                "Score": round(
                    document.get("score", 0),
                    4,
                ),
            }
            for index, document in enumerate(
                architecture_results
            )
        ]

        st.dataframe(
            pd.DataFrame(evidence_rows),
            use_container_width=True,
            hide_index=True,
        )

        graph_rows = []

        for node in architecture_graph:
            graph_rows.append(
                {
                    "Starting node": node["name"],
                    "Owner": node["owner"],
                    "Upstream dependencies": ", ".join(
                        sorted(
                            item["name"]
                            for item in node.get(
                                "upstream",
                                [],
                            )
                        )
                    ) or "None",
                    "Downstream impact": ", ".join(
                        sorted(
                            item["name"]
                            for item in node.get(
                                "downstream",
                                [],
                            )
                        )
                    ) or "None",
                }
            )

        st.markdown(
            '<div class="section-title">'
            "$GRAPHLOOKUP DEPENDENCY TRACE"
            "</div>",
            unsafe_allow_html=True,
        )

        st.dataframe(
            pd.DataFrame(graph_rows),
            use_container_width=True,
            hide_index=True,
        )

        with st.expander(
            "View retrieved passages"
        ):
            for document in architecture_results:
                st.markdown(
                    f"#### {document['title']}"
                )
                st.write(document["searchText"])
                st.caption(
                    f"Owner: {document['owner']} | "
                    f"Last updated: {document['lastUpdated']}"
                )


# ============================================================
# PIPELINE INSPECTION
# ============================================================

with pipeline_tab:
    st.markdown(
        '<div class="section-title">'
        "STEP 1 / AUTOMATED EMBEDDING VECTOR SEARCH"
        "</div>",
        unsafe_allow_html=True,
    )

    st.code(
        json.dumps(
            vector_search_pipeline(
                st.session_state.query_text
            ),
            indent=2,
        ),
        language="json",
    )

    st.markdown(
        '<div class="section-title">'
        "STEP 2 / ONTOLOGY ANCESTOR TRAVERSAL"
        "</div>",
        unsafe_allow_html=True,
    )

    example_concept = (
        matched_concept_id
        or "interventional_cardiology"
    )

    st.code(
        json.dumps(
            ancestor_pipeline(
                example_concept
            ),
            indent=2,
        ),
        language="json",
    )

    st.markdown(
        '<div class="section-title">'
        "STEP 3 / NESTED LOCATION + PLAN FILTER"
        "</div>",
        unsafe_allow_html=True,
    )

    st.code(
        json.dumps(
            st.session_state.provider_pipeline
            or provider_location_pipeline(
                [
                    "interventional_cardiology",
                    "cardiovascular_disease",
                ],
                "Chicago",
                "Spanish",
                "choice-plus",
                True,
            ),
            indent=2,
        ),
        language="json",
    )

    st.markdown(
        '<div class="section-title">'
        "ARCHITECTURE DOCUMENT VECTOR SEARCH"
        "</div>",
        unsafe_allow_html=True,
    )

    st.code(
        json.dumps(
            architecture_search_pipeline(
                st.session_state.architecture_query
            ),
            indent=2,
        ),
        language="json",
    )

    st.markdown(
        '<div class="section-title">'
        "ARCHITECTURE DEPENDENCY $GRAPHLOOKUP"
        "</div>",
        unsafe_allow_html=True,
    )

    st.code(
        json.dumps(
            architecture_graph_pipeline(
                ["provider_directory"]
            ),
            indent=2,
        ),
        language="json",
    )

    st.markdown(
        '<div class="section-title">'
        "AUTOMATED EMBEDDING INDEXES"
        "</div>",
        unsafe_allow_html=True,
    )

    st.code(
        json.dumps(
            [
                {
                    "collection": HEALTHCARE_COLLECTION,
                    "name": VECTOR_INDEX_NAME,
                    "type": "vectorSearch",
                    "definition": {
                        "fields": [
                            {
                                "type": "autoEmbed",
                                "modality": "text",
                                "path": "searchText",
                                "model": EMBEDDING_MODEL,
                            }
                        ]
                    },
                },
                {
                    "collection": DOMAIN_DOCUMENTS_COLLECTION,
                    "name": ARCHITECTURE_VECTOR_INDEX_NAME,
                    "type": "vectorSearch",
                    "definition": {
                        "fields": [
                            {
                                "type": "autoEmbed",
                                "modality": "text",
                                "path": "searchText",
                                "model": EMBEDDING_MODEL,
                            }
                        ]
                    },
                },
            ],
            indent=2,
        ),
        language="json",
    )


# ============================================================
# DATA INSPECTION
# ============================================================

with data_tab:
    st.markdown(
        '<div class="section-title">'
        "HEALTHCARE SEMANTIC DOCUMENTS"
        "</div>",
        unsafe_allow_html=True,
    )

    healthcare_rows = list(
        healthcare_collection.find(
            {},
            {
                "_id": 1,
                "conceptId": 1,
                "title": 1,
                "searchText": 1,
            },
        ).sort("_id", ASCENDING)
    )

    st.dataframe(
        pd.DataFrame(healthcare_rows),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Atlas stores automatically generated embeddings "
        "separately, so no embedding array appears here."
    )

    st.markdown(
        '<div class="section-title">'
        "ONTOLOGY CONCEPT DOCUMENTS"
        "</div>",
        unsafe_allow_html=True,
    )

    ontology_rows = list(
        ontology_collection.find(
            {},
            {
                "_id": 1,
                "name": 1,
                "code": 1,
                "conceptType": 1,
                "parentId": 1,
            },
        ).sort("name", ASCENDING)
    )

    st.dataframe(
        pd.DataFrame(ontology_rows),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown(
        '<div class="section-title">'
        "NESTED PROVIDER DOCUMENTS"
        "</div>",
        unsafe_allow_html=True,
    )

    provider_data_rows = list(
        providers_collection.find(
            {},
            {
                "_id": 1,
                "npi": 1,
                "name": 1,
                "specialtyConceptIds": 1,
                "taxEntities": 1,
            },
        ).sort("name", ASCENDING)
    )

    provider_summary_rows = [
        {
            "Provider": provider["name"],
            "NPI": provider["npi"],
            "Specialty concepts": ", ".join(
                provider["specialtyConceptIds"]
            ),
            "Tax IDs": len(
                provider["taxEntities"]
            ),
            "Locations": sum(
                len(entity.get("locations", []))
                for entity in provider[
                    "taxEntities"
                ]
            ),
        }
        for provider in provider_data_rows
    ]

    st.dataframe(
        pd.DataFrame(provider_summary_rows),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown(
        '<div class="section-title">'
        "UNSTRUCTURED DOMAIN DOCUMENTS"
        "</div>",
        unsafe_allow_html=True,
    )

    domain_rows = list(
        domain_documents_collection.find(
            {},
            {
                "_id": 1,
                "title": 1,
                "contentType": 1,
                "owner": 1,
                "lastUpdated": 1,
                "architectureNodeIds": 1,
            },
        ).sort("title", ASCENDING)
    )

    st.dataframe(
        pd.DataFrame(domain_rows),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown(
        '<div class="section-title">'
        "ARCHITECTURE KNOWLEDGE GRAPH NODES"
        "</div>",
        unsafe_allow_html=True,
    )

    architecture_rows = list(
        architecture_collection.find(
            {},
            {
                "_id": 1,
                "name": 1,
                "nodeType": 1,
                "owner": 1,
                "dependsOn": 1,
            },
        ).sort("name", ASCENDING)
    )

    st.dataframe(
        pd.DataFrame(architecture_rows),
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# ACTIVITY LOG
# ============================================================

st.markdown(
    '<div class="section-title">'
    "ACTIVITY LOG"
    "</div>",
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="log-window">'
    + html.escape(
        "\n".join(st.session_state.logs)
    )
    + "</div>",
    unsafe_allow_html=True,
)

