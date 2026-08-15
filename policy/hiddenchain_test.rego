package hiddenchain

import rego.v1

test_valid_contract_is_allowed if {
	decision := data.hiddenchain.decision with input as {
		"contract_status": "ACTIVE",
		"contract_purpose": "POWER_SETTLEMENT",
		"requested_purpose": "POWER_SETTLEMENT",
		"expected_capsule_id": "capsule-1",
		"capsule_id": "capsule-1",
		"expected_consumer_did": "did:hiddenchain:org:retailer",
		"consumer_did": "did:hiddenchain:org:retailer",
		"algorithm_code": "SETTLEMENT_MPC_V1",
		"allowed_algorithms": ["SETTLEMENT_MPC_V1"],
		"expected_execution_environment": "AUTHORIZED_COMPUTE_SANDBOX",
		"execution_environment": "AUTHORIZED_COMPUTE_SANDBOX",
		"expected_output_mode": "AGGREGATE_ONLY",
		"output_mode": "AGGREGATE_ONLY",
		"raw_data_export": false,
		"contract_raw_data_export": false,
		"valid_from_epoch": 100,
		"now_epoch": 200,
		"expires_at_epoch": 300,
		"agreement_state": "ACTIVE",
		"max_uses": 2,
		"use_count": 0,
		"obligations": ["LOG_USAGE"],
	}
	decision.allow
	decision.reasons == []
}

test_raw_export_is_denied if {
	decision := data.hiddenchain.decision with input as {
		"contract_status": "ACTIVE",
		"contract_purpose": "POWER_SETTLEMENT",
		"requested_purpose": "POWER_SETTLEMENT",
		"expected_capsule_id": "capsule-1",
		"capsule_id": "capsule-1",
		"algorithm_code": "SETTLEMENT_MPC_V1",
		"allowed_algorithms": ["SETTLEMENT_MPC_V1"],
		"raw_data_export": true,
		"contract_raw_data_export": false,
		"now_epoch": 200,
		"expires_at_epoch": 300,
		"agreement_state": "ACTIVE",
		"max_uses": 2,
		"use_count": 0,
		"obligations": [],
	}
	not decision.allow
	decision.reasons == ["RAW_DATA_EXPORT_NOT_ALLOWED"]
}

test_use_limit_is_denied if {
	decision := data.hiddenchain.decision with input as {
		"contract_status": "ACTIVE",
		"contract_purpose": "POWER_SETTLEMENT",
		"requested_purpose": "POWER_SETTLEMENT",
		"expected_capsule_id": "capsule-1",
		"capsule_id": "capsule-1",
		"algorithm_code": "SETTLEMENT_MPC_V1",
		"allowed_algorithms": ["SETTLEMENT_MPC_V1"],
		"raw_data_export": false,
		"contract_raw_data_export": false,
		"now_epoch": 200,
		"expires_at_epoch": 300,
		"agreement_state": "ACTIVE",
		"max_uses": 2,
		"use_count": 2,
		"obligations": [],
	}
	not decision.allow
	decision.reasons == ["USE_LIMIT_REACHED"]
}
