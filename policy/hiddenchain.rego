package hiddenchain

import rego.v1

reasons contains "CONTRACT_NOT_ACTIVE" if input.contract_status != "ACTIVE"

reasons contains "PURPOSE_MISMATCH" if input.contract_purpose != input.requested_purpose

reasons contains "CAPSULE_MISMATCH" if input.expected_capsule_id != input.capsule_id

reasons contains "CONSUMER_MISMATCH" if {
	input.expected_consumer_did != null
	input.consumer_did != null
	input.expected_consumer_did != input.consumer_did
}

reasons contains "ALGORITHM_NOT_ALLOWED" if not allowed_algorithm

allowed_algorithm if input.algorithm_code in input.allowed_algorithms

reasons contains "EXECUTION_ENVIRONMENT_NOT_ALLOWED" if {
	input.expected_execution_environment != null
	input.execution_environment != input.expected_execution_environment
}

reasons contains "OUTPUT_MODE_NOT_ALLOWED" if {
	input.expected_output_mode != null
	input.output_mode != input.expected_output_mode
}

reasons contains "RAW_DATA_EXPORT_NOT_ALLOWED" if {
	input.raw_data_export
}

reasons contains "RAW_DATA_EXPORT_NOT_ALLOWED" if {
	input.contract_raw_data_export != false
}

reasons contains "CONTRACT_NOT_YET_VALID" if {
	input.valid_from_epoch != null
	input.now_epoch < input.valid_from_epoch
}

reasons contains "CONTRACT_EXPIRED" if {
	input.expires_at_epoch != null
	input.now_epoch >= input.expires_at_epoch
}

reasons contains "AGREEMENT_NOT_ACTIVE" if {
	input.agreement_state != null
	input.agreement_state != "NEGOTIATED"
	input.agreement_state != "ACTIVE"
}

reasons contains "USE_LIMIT_REACHED" if {
	input.max_uses != null
	input.use_count >= input.max_uses
}

decision := {
	"allow": count(reasons) == 0,
	"reasons": sort([reason | reason := reasons[_]]),
	"obligations": input.obligations,
}
