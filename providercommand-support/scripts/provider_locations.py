"""Location-scoped provider filtering and illustrative cost math extracted from app5.py."""
if __package__:
    from ._common import database, output, parser, run
    from .demo_config import PROVIDERS_COLLECTION
else:
    from _common import database, output, parser, run
    from demo_config import PROVIDERS_COLLECTION


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

def main():
    cli = parser(__doc__)
    cli.add_argument('--concept', action='append', help='Resolved ontology concept ID. Repeat to include descendants.')
    cli.add_argument('--city', default='Chicago')
    cli.add_argument('--language', default='Any')
    cli.add_argument('--plan', default='choice-plus')
    cli.add_argument('--accepting-only', action='store_true')
    cli.add_argument('--explain', action='store_true', help='Print the pipeline without connecting.')
    args = cli.parse_args()
    pipeline = provider_location_pipeline(args.concept or ['interventional_cardiology'],
                                          args.city, args.language, args.plan, args.accepting_only)
    if args.explain:
        output(pipeline)
        return 0
    with database(args) as db:
        rows = list(db[PROVIDERS_COLLECTION].aggregate(pipeline, maxTimeMS=args.timeout_ms))
        output({'matches': rows})


if __name__ == '__main__':
    raise SystemExit(run(main))
