from __future__ import annotations

from pathlib import Path

import pytest

pyshacl = pytest.importorskip("pyshacl")
from pyshacl import validate
from rdflib import BNode, Graph, Literal, Namespace, RDF, URIRef

from app.services.dataspace import DataspaceProtocolAdapter


DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
DSPACE = Namespace("https://w3id.org/dspace/2024/1/")
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
SHAPES = Path(__file__).parent / "fixtures" / "dataspace_catalog.shacl.ttl"


def _term(value: str) -> URIRef:
    if value.startswith(("urn:", "did:")) or "://" in value:
        return URIRef(value)
    prefix, local = value.split(":", 1)
    namespaces = {"dcat": DCAT, "dct": DCT, "dspace": DSPACE, "odrl": ODRL}
    if prefix not in namespaces:
        return URIRef(value)
    return namespaces[prefix][local]


def _descriptor_graph(descriptor: dict) -> Graph:
    graph = Graph()
    catalog = URIRef(descriptor["@id"])
    graph.add((catalog, RDF.type, _term(descriptor["@type"])))

    for service in descriptor["dcat:service"]:
        service_ref = URIRef(service["@id"])
        graph.add((service_ref, RDF.type, _term(service["@type"])))
        graph.add((service_ref, DCAT.endpointURL, Literal(service["dcat:endpointURL"])))
        graph.add((catalog, DCAT.service, service_ref))

    for dataset in descriptor["dcat:dataset"]:
        dataset_ref = URIRef(dataset["@id"])
        graph.add((dataset_ref, RDF.type, _term(dataset["@type"])))
        graph.add((dataset_ref, DCT.title, Literal(dataset["dct:title"])))
        graph.add((catalog, DCAT.dataset, dataset_ref))

        for policy in dataset["odrl:hasPolicy"]:
            policy_ref = URIRef(policy["@id"])
            graph.add((policy_ref, RDF.type, _term(policy["@type"])))
            graph.add((policy_ref, ODRL.assigner, _term(policy["odrl:assigner"])))
            graph.add((dataset_ref, ODRL.hasPolicy, policy_ref))
            for permission in policy["odrl:permission"]:
                permission_ref = BNode()
                graph.add((permission_ref, ODRL.action, _term(permission["odrl:action"])))
                graph.add((policy_ref, ODRL.permission, permission_ref))
                for constraint in permission["odrl:constraint"]:
                    constraint_ref = BNode()
                    graph.add((permission_ref, ODRL.constraint, constraint_ref))
                    graph.add(
                        (constraint_ref, ODRL.leftOperand, _term(constraint["odrl:leftOperand"]))
                    )
                    graph.add(
                        (constraint_ref, ODRL.operator, _term(constraint["odrl:operator"]))
                    )
                    graph.add(
                        (constraint_ref, ODRL.rightOperand, Literal(constraint["odrl:rightOperand"]))
                    )

        for distribution in dataset["dcat:distribution"]:
            distribution_ref = BNode()
            graph.add((distribution_ref, RDF.type, _term(distribution["@type"])))
            graph.add((dataset_ref, DCAT.distribution, distribution_ref))
            for access_service in distribution["dcat:accessService"]:
                graph.add((distribution_ref, DCAT.accessService, URIRef(access_service["@id"])))

    return graph


def _sample_descriptor() -> dict:
    return DataspaceProtocolAdapter.build(
        [
            {
                "data_product_id": "DP-shacl-test",
                "label": "SHACL metadata test",
                "asset_type": "GENERATION_DATA",
                "semantic_ref": "energy:GenerationMeasurement",
                "owner_did": "did:hiddenchain:org:test",
                "usage": {"allowed_purposes": ["POWER_SETTLEMENT"]},
                "transport": {"protocol": "HTTPS"},
            }
        ]
    )["descriptor"]


def _validate(descriptor: dict) -> tuple[bool, str]:
    shapes_graph = Graph().parse(SHAPES, format="turtle")
    conforms, _, report_text = validate(
        _descriptor_graph(descriptor),
        shacl_graph=shapes_graph,
        inference="none",
        abort_on_first=False,
        meta_shacl=True,
    )
    return conforms, str(report_text)


def test_dataspace_descriptor_conforms_to_local_shacl_profile():
    conforms, report = _validate(_sample_descriptor())

    assert conforms, report


def test_dataspace_shacl_profile_rejects_missing_policy():
    descriptor = _sample_descriptor()
    descriptor["dcat:dataset"][0]["odrl:hasPolicy"] = []

    conforms, report = _validate(descriptor)

    assert not conforms
    assert "odrl:hasPolicy" in report
