from __future__ import annotations

from typing import Any

from ..security import sha256_json


class DataspaceProtocolAdapter:
    """Publish a safe Dataspace Protocol 2024-1 catalog projection.

    The IDSA specification describes the interoperable catalog envelope. This
    adapter maps the local connector's already-sanitized metadata to that
    envelope without pretending to be an EDC control plane or data plane.
    """

    code = "IDSA_DATASPACE_PROTOCOL_CATALOG_2024_1"
    version = "2024-1"
    context = "https://w3id.org/dspace/2024/1/context.json"
    participant_id = "urn:hiddenchain:participant:platform"

    @classmethod
    def status(cls) -> dict[str, Any]:
        return {
            "code": cls.code,
            "version": cls.version,
            "context": cls.context,
            "participant_id": cls.participant_id,
            "catalog_projection": "DCAT_DATASET_ODRL_POLICY",
            "raw_data_exposed": False,
        }

    @staticmethod
    def _urn(prefix: str, value: Any) -> str:
        return f"urn:uuid:{sha256_json({'kind': prefix, 'value': value})[:32]}"

    @classmethod
    def _policy(cls, entry: dict[str, Any], policy_id: str) -> dict[str, Any]:
        usage = entry.get("usage") or {}
        allowed_purposes = [str(item) for item in usage.get("allowed_purposes", [])]
        purpose = allowed_purposes[0] if allowed_purposes else "POWER_SETTLEMENT"
        transport = str((entry.get("transport") or {}).get("protocol", "HTTPS"))
        return {
            "@id": policy_id,
            "@type": "odrl:Offer",
            "odrl:assigner": entry.get("owner_did") or cls.participant_id,
            "odrl:permission": [
                {
                    "odrl:action": "odrl:use",
                    "odrl:constraint": [
                        {
                            "odrl:leftOperand": "odrl:purpose",
                            "odrl:operator": "odrl:eq",
                            "odrl:rightOperand": purpose,
                        },
                        {
                            "odrl:leftOperand": "dspace:transportType",
                            "odrl:operator": "odrl:eq",
                            "odrl:rightOperand": transport,
                        },
                    ],
                }
            ],
        }

    @classmethod
    def _dataset(cls, entry: dict[str, Any], service_id: str) -> dict[str, Any]:
        product_id = str(entry["data_product_id"])
        dataset_id = cls._urn("dataset", {"product_id": product_id})
        policy_id = cls._urn("policy", {"product_id": product_id, "policy": entry.get("usage")})
        endpoint = str(entry.get("endpoint") or f"connector://hiddenchain/products/{product_id}")
        return {
            "@id": dataset_id,
            "@type": "dcat:Dataset",
            "dct:title": str(entry.get("label") or product_id),
            "dct:description": [
                {
                    "@value": (
                        f"{entry.get('semantic_ref', 'energy:DataProduct')} metadata-only "
                        "dataset; raw records remain in the provider connector."
                    ),
                    "@language": "en",
                }
            ],
            "dcat:keyword": [
                str(entry.get("asset_type") or "ENERGY_DATA"),
                str(entry.get("semantic_ref") or "energy:DataProduct"),
            ],
            "dcat:conformsTo": "https://w3id.org/dspace/2024/1/",
            "odrl:hasPolicy": [cls._policy(entry, policy_id)],
            "dcat:distribution": [
                {
                    "@type": "dcat:Distribution",
                    "dct:format": {"@id": "dspace:connector"},
                    "dcat:accessService": [
                        {
                            "@id": service_id,
                            "@type": "dcat:DataService",
                            "dcat:endpointURL": endpoint,
                        }
                    ],
                }
            ],
        }

    @classmethod
    def validate(cls, descriptor: dict[str, Any]) -> list[str]:
        """Validate the protocol fields that are stable in the 2024-1 schema."""
        errors: list[str] = []
        if descriptor.get("@context") != cls.context:
            errors.append("@context must be the Dataspace Protocol 2024-1 context")
        if descriptor.get("@type") != "dcat:Catalog":
            errors.append("@type must be dcat:Catalog")
        datasets = descriptor.get("dcat:dataset")
        if not isinstance(datasets, list) or not datasets:
            errors.append("dcat:dataset must contain at least one dataset")
        else:
            for index, dataset in enumerate(datasets):
                if dataset.get("@type") != "dcat:Dataset":
                    errors.append(f"dcat:dataset[{index}] must be dcat:Dataset")
                if not dataset.get("odrl:hasPolicy"):
                    errors.append(f"dcat:dataset[{index}] is missing odrl:hasPolicy")
                if not dataset.get("dcat:distribution"):
                    errors.append(f"dcat:dataset[{index}] is missing dcat:distribution")
        services = descriptor.get("dcat:service")
        if not isinstance(services, list) or not services:
            errors.append("dcat:service must contain at least one data service")
        return errors

    @classmethod
    def build(cls, entries: list[dict[str, Any]]) -> dict[str, Any]:
        service_id = cls._urn("service", {"participant": cls.participant_id})
        descriptor = {
            "@context": cls.context,
            "@id": cls._urn(
                "catalog",
                {
                    "participant": cls.participant_id,
                    "products": sorted(str(item.get("data_product_id")) for item in entries),
                },
            ),
            "@type": "dcat:Catalog",
            "dct:title": "隐链明算能源可信数据空间目录",
            "dct:description": [
                {
                    "@value": "协议目录只发布元数据、用途策略和连接器入口，不发布原始能源记录。",
                    "@language": "zh",
                }
            ],
            "dspace:participantId": cls.participant_id,
            "dcat:service": [
                {
                    "@id": service_id,
                    "@type": "dcat:DataService",
                    "dcat:endpointDescription": "dspace:connector",
                    "dcat:endpointURL": "connector://hiddenchain/dataspace",
                }
            ],
            "dcat:dataset": [cls._dataset(entry, service_id) for entry in entries],
        }
        errors = cls.validate(descriptor)
        return {
            "adapter": cls.code,
            "protocol": "Dataspace Protocol",
            "version": cls.version,
            "catalog_id": descriptor["@id"],
            "dataset_count": len(descriptor["dcat:dataset"]),
            "descriptor_hash": sha256_json(descriptor),
            "schema_validation": {"valid": not errors, "errors": errors},
            "descriptor": descriptor,
            "raw_data_exposed": False,
        }
