from __future__ import annotations

from typing import Any


# This is a deliberately small, offline profile of the stable catalog fields
# in the IDSA Dataspace Protocol 2024-1 catalog schema.  It keeps validation
# deterministic and permits the platform's documented dspace:transportType
# extension without fetching schemas or contexts from the network.
DATASPACE_CATALOG_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2019-09/schema",
    "type": "object",
    "required": ["@context", "@type", "dcat:dataset", "dcat:service"],
    "properties": {
        "@context": {
            "type": "string",
            "const": "https://w3id.org/dspace/2024/1/context.json",
        },
        "@id": {"type": "string"},
        "@type": {"type": "string", "const": "dcat:Catalog"},
        "dct:title": {"type": "string"},
        "dct:description": {"$ref": "#/$defs/multilanguage"},
        "dspace:participantId": {"type": "string"},
        "dcat:dataset": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/dataset"},
        },
        "dcat:service": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/data_service"},
        },
    },
    "$defs": {
        "multilanguage": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["@value", "@language"],
                "properties": {
                    "@value": {"type": "string"},
                    "@language": {"type": "string"},
                },
            },
        },
        "dataset": {
            "type": "object",
            "required": [
                "@id",
                "@type",
                "dct:title",
                "odrl:hasPolicy",
                "dcat:distribution",
            ],
            "properties": {
                "@id": {"type": "string"},
                "@type": {"type": "string", "const": "dcat:Dataset"},
                "dct:title": {"type": "string"},
                "dct:description": {"$ref": "#/$defs/multilanguage"},
                "dcat:keyword": {"type": "array", "items": {"type": "string"}},
                "dct:conformsTo": {"type": "string"},
                "odrl:hasPolicy": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/offer"},
                },
                "dcat:distribution": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/distribution"},
                },
            },
        },
        "offer": {
            "type": "object",
            "required": ["@id", "@type", "odrl:assigner", "odrl:permission"],
            "properties": {
                "@id": {"type": "string"},
                "@type": {"type": "string", "const": "odrl:Offer"},
                "odrl:assigner": {"type": "string"},
                "odrl:permission": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/permission"},
                },
            },
        },
        "permission": {
            "type": "object",
            "required": ["odrl:action", "odrl:constraint"],
            "properties": {
                "odrl:action": {"type": "string", "const": "odrl:use"},
                "odrl:constraint": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/constraint"},
                },
            },
        },
        "constraint": {
            "type": "object",
            "required": [
                "odrl:leftOperand",
                "odrl:operator",
                "odrl:rightOperand",
            ],
            "properties": {
                "odrl:leftOperand": {
                    "type": "string",
                    "enum": ["odrl:purpose", "dspace:transportType"],
                },
                "odrl:operator": {"type": "string", "const": "odrl:eq"},
                "odrl:rightOperand": {"type": "string"},
            },
        },
        "distribution": {
            "type": "object",
            "required": ["@type", "dct:format", "dcat:accessService"],
            "properties": {
                "@type": {"type": "string", "const": "dcat:Distribution"},
                "dct:format": {
                    "type": "object",
                    "required": ["@id"],
                    "properties": {"@id": {"type": "string"}},
                },
                "dcat:accessService": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/data_service"},
                },
            },
        },
        "data_service": {
            "type": "object",
            "required": ["@id", "@type", "dcat:endpointURL"],
            "properties": {
                "@id": {"type": "string"},
                "@type": {"type": "string", "const": "dcat:DataService"},
                "dcat:endpointDescription": {"type": "string"},
                "dcat:endpointURL": {"type": "string"},
            },
        },
    },
}
