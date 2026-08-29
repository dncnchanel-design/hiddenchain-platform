import { ApiError, api, post, type ApiCommandOptions } from "../../api";

export type CapabilityEnvelope = {
  capability_state?: string;
  source_of_truth?: string;
  allowed_actions?: string[];
  [key: string]: unknown;
};

export type TrustedMenu = {
  code: string;
  path: string;
  title: string;
  roles: string[];
};

export type TrustedContext = CapabilityEnvelope & {
  actor: {
    user_id: string;
    username: string;
    display_name: string;
    role_code: string;
    role_label: string;
    permissions?: string[];
    is_org_owner?: boolean;
  };
  current_subject: {
    org_id: string;
    org_type?: string | null;
    org_name?: string | null;
    energy_domain?: string | null;
    status: string;
  };
  identity_ref: {
    did?: string | null;
    credential_status: string;
    capability_state?: string;
    source_of_truth?: string;
  };
  role_capabilities: Record<string, unknown>;
  visible_menus: TrustedMenu[];
  environment: {
    name: string;
    fixture_seed: boolean;
    capability_state?: string;
    source_of_truth?: string;
  };
  capabilities: Record<string, CapabilityEnvelope>;
};

export type TtcPhaseProgressEstimate = {
  value: number;
  source: string;
  label: string;
};

export type WorkbenchPayload = CapabilityEnvelope & {
  kpis: {
    visible_assets: number;
    visible_tasks: number;
    usage_requests: number;
    active_usage_requests: number;
    inbound_usage_requests: number;
    outbound_usage_requests: number;
    compute_jobs: number;
    audit_reports: number;
  };
  recent_assets: Array<{
    asset_id: string;
    asset_code: string;
    asset_name: string;
    asset_type: string;
    owner_org_id: string;
    owner_org_name?: string | null;
    source_capability?: string;
  } & CapabilityEnvelope>;
  recent_tasks: Array<{
    task_id: string;
    task_name: string;
    status: string;
    ttc_state?: string;
    current_attempt?: number;
    updated_at?: string | null;
    phase_progress_estimate?: TtcPhaseProgressEstimate;
  } & CapabilityEnvelope>;
  recent_usage_requests: UsageRequestSummary[];
  recent_compute_jobs: Array<Record<string, unknown> & CapabilityEnvelope>;
  recent_audit_reports: Array<Record<string, unknown> & CapabilityEnvelope>;
  quick_actions: string[];
  quick_action_items: WorkbenchQuickAction[];
  empty_state: boolean;
};

export type WorkbenchQuickAction = CapabilityEnvelope & {
  code: string;
  label: string;
  path: string;
  allowed: boolean;
  disabled_reason?: string | null;
  entity_id?: string | null;
};

export type TrustedNotification = CapabilityEnvelope & {
  notification_id: string;
  user_id: string;
  org_id: string;
  type?: string;
  notification_type: string;
  title: string;
  body: string;
  entity_type?: string | null;
  entity_id?: string | null;
  severity: string;
  dedupe_key: string;
  read_at?: string | null;
  created_at: string;
};

export type NotificationListPayload = CapabilityEnvelope & {
  items: TrustedNotification[];
  total: number;
  unread_count: number;
  page: number;
  page_size: number;
  empty_state: boolean;
  allowed_actions?: string[];
};

export type NotificationMarkAllPayload = CapabilityEnvelope & {
  updated_count: number;
  unread_count: number;
  allowed_actions?: string[];
};

export type TrustedHelpEntry = CapabilityEnvelope & {
  id: string;
  title: string;
  body: string;
  related_paths: string[];
  allowed_actions: string[];
};

export type TrustedHelpPayload = CapabilityEnvelope & {
  view: string;
  version: string;
  title: string;
  summary: string;
  entries: TrustedHelpEntry[];
  role_code: string;
  role_capabilities: Record<string, unknown>;
};

export type IdentityPayload = CapabilityEnvelope & {
  subject: {
    org_id: string;
    org_type?: string | null;
    org_name?: string | null;
    credit_code?: string | null;
    status: string;
  };
  actor: {
    user_id: string;
    display_name: string;
    role_code: string;
  };
  did: {
    did_id?: string | null;
    credential_status: string;
    public_key_fingerprint?: string | null;
    chain_address?: string | null;
    credential_type?: string[] | null;
    issuer?: string | null;
    issued_at?: string | null;
    expires_at?: string | null;
    verification?: Record<string, unknown> | null;
  } & CapabilityEnvelope;
  connector: {
    code: string;
    protocol_version: string;
    source_count: number;
    source_capabilities: string[];
    readiness: string;
    external_edc_runtime: string;
  } & CapabilityEnvelope;
  capability_matrix: Record<string, CapabilityEnvelope>;
};

export type IdentityDirectoryItem = CapabilityEnvelope & {
  org_id: string;
  org_type?: string | null;
  org_name?: string | null;
  energy_domain?: string | null;
  status: string;
  did_id: string;
  credential_status: string;
  public_key_fingerprint?: string | null;
  chain_address?: string | null;
  credential_type: string[];
  issuer?: string | null;
  issued_at?: string | null;
  expires_at?: string | null;
  member_count: number;
};

export type IdentityDirectoryPayload = CapabilityEnvelope & {
  items: IdentityDirectoryItem[];
  total: number;
  verified_count: number;
  energy_domains: string[];
  empty_state: boolean;
};

export type DidDocumentPayload = CapabilityEnvelope & {
  did_id: string;
  subject: {
    org_id: string;
    org_name?: string | null;
    org_type?: string | null;
    energy_domain?: string | null;
  };
  credential_status: string;
  public_key_fingerprint?: string | null;
  document: Record<string, unknown>;
  verification: Record<string, unknown>;
};

export type CatalogAsset = CapabilityEnvelope & {
  asset_id: string;
  asset_code: string;
  asset_name: string;
  asset_type: string;
  classification: string;
  sensitivity_level: string;
  status: string;
  domain?: string | null;
  metadata?: Record<string, unknown>;
  provider: { org_id: string; org_name?: string | null };
  latest_version?: {
    version_id: string;
    version_no: number;
    schema_version: string;
    data_hash: string;
    record_count?: number | null;
    status: string;
  } | null;
  actions: {
    can_request_usage: boolean;
    can_review_inbound: boolean;
    can_view_passport: boolean;
  };
  source: {
    source_id?: string | null;
    connector_type?: string | null;
    capability_label: string;
    status: string;
  };
};

export type CatalogPayload = CapabilityEnvelope & {
  items: CatalogAsset[];
  total: number;
  page: number;
  page_size: number;
  filters: {
    query?: string | null;
    asset_type?: string | null;
    domain?: string | null;
    sensitivity_level?: string | null;
    provider_org_id?: string | null;
  };
  empty_state: boolean;
};

export type AssetVersion = {
  version_id: string;
  version_no: number;
  schema_version: string;
  data_hash: string;
  commitment?: string | null;
  record_count?: number | null;
  immutable_hash: string;
  status: string;
  passport?: {
    passport_id: string;
    passport_version: number;
    owner_did: string;
    provenance?: Record<string, unknown>;
    classification?: Record<string, unknown>;
    permitted_use?: Record<string, unknown>;
    policy_refs: string[];
    evidence_refs: string[];
    passport_hash: string;
    status: string;
  } | null;
  quality?: {
    quality_id: string;
    profile_version: string;
    metrics: Record<string, unknown>;
    decision: string;
    quality_hash: string;
    evidence_refs: string[];
    evaluated_at?: string | null;
  } | null;
};

export type AssetDetailPayload = CapabilityEnvelope & {
  asset: {
    asset_id: string;
    asset_code: string;
    asset_name: string;
    asset_type: string;
    classification: string;
    sensitivity_level: string;
    status: string;
    domain?: string | null;
    metadata?: Record<string, unknown>;
    provider: { org_id: string; org_name?: string | null };
  };
  versions: AssetVersion[];
  current_version_id?: string | null;
  usage_rules?: Record<string, unknown> | null;
  duration_policy?: UsageDurationPolicy | null;
  policy_refs: string[];
  evidence_summary: {
    passport_evidence_refs: string[];
    active_agreement_count: number;
    contract_count: number;
  } & CapabilityEnvelope;
  usage_requests: UsageRequestSummary[];
  actions: {
    can_request_usage: boolean;
    can_review_inbound: boolean;
    can_revoke_provider_authorization: boolean;
    can_view_audit: boolean;
  };
  source: {
    source_id?: string | null;
    source_code?: string | null;
    security_domain?: string | null;
    connector_type?: string | null;
    capability_label: string;
    status: string;
  };
};

export type UsageDurationPolicy = {
  policy_version: string;
  source: string;
  source_ref: string;
  min_days: number;
  max_days: number;
  default_days: number;
  is_default: boolean;
};

export type UsageRequest = CapabilityEnvelope & {
  request_id: string;
  asset: {
    asset_id: string;
    asset_code?: string | null;
    asset_name?: string | null;
    asset_type?: string | null;
    classification?: string | null;
    sensitivity_level?: string | null;
    version_id?: string | null;
    version_no?: number | null;
    data_hash?: string | null;
  };
  applicant: { user_id: string; org_id: string; org_name: string; did: string };
  provider: { org_id: string; org_name: string; did: string };
  purpose: string;
  usage_mode: string;
  requested_scope: Record<string, unknown>;
  requested_fields: string[];
  terms: Record<string, unknown>;
  duration_days: number;
  duration_policy?: UsageDurationPolicy | null;
  expires_at: string;
  status: string;
  decision_reason?: string | null;
  revocation_reason?: string | null;
  reviewer_user_id?: string | null;
  reviewer_did?: string | null;
  decision_hash?: string | null;
  contract_id?: string | null;
  agreement_id?: string | null;
  state_version: number;
  submitted_at: string;
  reviewed_at?: string | null;
  decided_at?: string | null;
  revoked_at?: string | null;
  capability?: {
    decision?: string;
    signature?: string;
    external_anchor?: string;
  };
  actions: string[];
};

export type UsageRequestSummary = CapabilityEnvelope & {
  request_id: string;
  status: string;
  purpose: string;
  usage_mode: string;
  applicant_org_id: string;
  applicant_org_name?: string | null;
  provider_org_id: string;
  provider_org_name?: string | null;
  expires_at?: string | null;
  contract_id?: string | null;
  agreement_id?: string | null;
  state_version: number;
};

export type UsageRequestList = {
  items: UsageRequest[];
  total: number;
  page: number;
  page_size: number;
  inbox?: boolean;
  mine?: boolean;
};

export type QueryIntent = {
  question: string;
  energy_domain?: string | null;
  energy_domain_name?: string | null;
  resource?: string | null;
  function: string;
  function_name: string;
  start_date?: string | null;
  end_date?: string | null;
  region?: string | null;
  requires_authorization: boolean;
  requires_confirmation: boolean;
  ready: boolean;
  provider?: "deepseek" | "manual_rules";
  model?: string | null;
  request_id?: string | null;
  duration_ms?: number | null;
  notice: string;
};

export type PrototypeHeaderPayload = {
  title: string;
  identity: { name: string; role: string; did: string };
  stats: Array<{ key: string; label: string; value: number | string }>;
};

export type PrototypeDashboardPayload = {
  kpis: { resources: number; rules: number; identities: number; blocks: number; today_queries: number };
  map: { days: string[]; series: Record<string, number[]>; city_days?: Record<string, number[]> };
  metric: {
    title: string;
    label: string;
    value: number | null;
    unit: string;
    status: "available" | "not_configured" | "unavailable";
    status_label: string;
    source: string;
    latest_date: string | null;
    record_count: number;
    aggregation: string;
    trend: Array<{ date: string; value: number }>;
    message: string;
    raw_records_returned: boolean;
    privacy_verification?: Record<string, unknown>;
  };
  audit: PrototypeAuditRecord[];
  action_counts: Record<string, number>;
  connectors: Array<{ name: string; status: string }>;
  timeline: PrototypeAuditRecord[];
  chain: { ok: boolean; message: string };
  latest_usage: boolean;
  data_mode: "demo" | "subject_connector" | "live";
  view: {
    kind: "enterprise" | "exchange" | "regulator";
    role_code: string;
    energy_domain: string;
    energy_label: string;
    scope_label: string;
    title: string;
    subtitle: string;
    visualization: "regional_map" | "subject_trend";
    visual_title: string;
    visual_subtitle: string;
    visual_value_label: string;
    visual_value_unit: string;
    focus_title: string;
    kpis: Array<{ label: string; value: number | string; meta: string }>;
    primary_action: { label: string; path: string };
    data_scope: string;
    projection: string;
  };
  data_notice: string;
};

export type PrototypeQueryPayload = {
  question: string;
  plan: Array<{ stage: string; status: string }>;
  identity?: { name: string; did: string };
  decision: { action: string; label: string; reason: string };
  result: { value: number; record_count: number; resource: string; function: string; trend?: Array<{ label: string; value: number }> } | null;
  resource_name?: string;
  function_name?: string;
  audit_id?: string | null;
  raw_data_returned: boolean;
};

export type ConnectorEnergyDomain = "electricity" | "coal" | "heat" | "gas" | "oil";
export type ConnectorClassification = "L1" | "L2" | "L3";

export type ConnectorCatalogResource = {
  resource_id: string;
  resource_name: string;
  unit: string;
  schema_version: string;
  required_columns: string[];
  optional_columns: string[];
  current_version: number | null;
  record_count: number | null;
  status: string;
};

export type ConnectorCatalogPayload = {
  connector: {
    connector_id: string;
    organization_id: string;
    organization_name: string;
    energy_domain: ConnectorEnergyDomain;
    endpoint: string;
    status: string;
    capability_state: string;
  };
  resources: ConnectorCatalogResource[];
  upload_contract: {
    mode: string;
    file_format: "csv";
    max_bytes: number;
    ticket_lifetime_seconds: number;
  };
};

export type ConnectorTicket = {
  claims: {
    iss: "hiddenchain-platform";
    jti: string;
    subject_user_id: string;
    organization_id: string;
    connector_id: string;
    energy_domain: ConnectorEnergyDomain;
    resource_id: string;
    resource_name: string;
    classification: ConnectorClassification;
    schema_version: "connector-csv-v1";
    file_format: "csv";
    max_bytes: number;
    purpose: "LOCAL_DATASET_INGEST";
    issued_at: number;
    expires_at: number;
  };
  signature: string;
  public_key: string;
  algorithm: "Ed25519";
};

export type ConnectorTicketPayload = {
  ticket: ConnectorTicket;
  upload_url: string;
  receipt_lookup_url: string;
  connector: {
    connector_id: string;
    organization_id: string;
    energy_domain: ConnectorEnergyDomain;
  };
};

export type ConnectorSignedReceipt = {
  receipt_id: string;
  ticket_id: string;
  connector_id: string;
  organization_id: string;
  energy_domain: string;
  resource_id: string;
  resource_name: string;
  version: number;
  schema_version: string;
  schema_hash: string;
  content_hash: string;
  record_count: number;
  byte_size: number;
  local_ref: string;
  audit_sequence: number;
  audit_hash: string;
  issued_at: string;
  signature: string;
  public_key: string;
  signature_algorithm: "Ed25519";
  signature_valid: true;
};

export type ConnectorReceiptPayload = {
  ticket_id: string;
  status: string;
  receipt_id: string | null;
  connector_id?: string;
  organization_id?: string;
  energy_domain?: string;
  resource_id?: string;
  resource_name?: string;
  registered_at?: string;
  asset?: { asset_id: string; asset_version_id: string; version: number };
  raw_data_centrally_stored: false;
  idempotent_replay?: boolean;
};

export type PrototypePolicyRule = { role: string; purposes: string[]; action: string; fields: string[]; min_granularity?: string | null; delay_hours?: number | null; rule_id?: string };
export type PrototypePolicyResource = { id: string; name: string; level: string; connector: string; default_action: string; dynamic?: boolean; asset_id?: string; owner_org_id?: string; rules: PrototypePolicyRule[] };
export type PrototypePolicyPayload = { matrix: PrototypePolicyResource[]; applications: Array<{ ts: string; resource_id: string; resource_name: string; applicant_role: string; applicant_did: string; purpose: string; status: string }> };

export type PrototypeAuditRecord = { id: string; ts: string; action: string; action_name: string; subject: string; resource: string; target_type: string; target_id: string; result: string; trace_id: string };
export type PrototypeAuditBlock = { id: string; height: number; hash: string; tx_hash: string; status: string; created_at: string };
export type PrototypeTamperEvent = { event_id: string; active: boolean; actor_name: string; actor_user_id: string | null; actor_org_id: string | null; occurred_at: string; trace_id: string; target_type: string; target_id: string; block: PrototypeAuditBlock | null; note: string };
export type PrototypeAuditPayload = { records: PrototypeAuditRecord[]; blocks: PrototypeAuditBlock[]; metrics: { total: number; denied: number; controlled: number; blocks: number }; chain: { ok: boolean; message: string }; tamper: PrototypeTamperEvent | null };

export type QueryConfirmation = {
  confirmed: boolean;
  confirmation_token: string;
  notice: string;
};

export type AccessRule = CapabilityEnvelope & {
  rule_id: string;
  owner_org_id: string;
  rule_code: string;
  version_no: number;
  version: string;
  energy_domain?: string | null;
  asset_id?: string | null;
  resource_id: string;
  function_code: string;
  mode: "AUTO_CALL" | "ENTERPRISE_APPROVAL" | "FORBIDDEN" | string;
  scope: Record<string, unknown>;
  limits: Record<string, unknown>;
  status: string;
  rule_hash: string;
  approved_by_user_id?: string | null;
  approved_at?: string | null;
  revoked_at?: string | null;
  raw_data_export: false;
};

export type AccessRuleListPayload = CapabilityEnvelope & {
  items: AccessRule[];
  metadata_only: boolean;
  raw_data_exposed: false;
};

export type ControlledQueryResult = {
  task_id: string;
  job_id?: string | null;
  request_item_id?: string;
  authorization_scope: string;
  generated_at: string;
  result: number | string | Record<string, number | string>;
  unit: string;
  record_count?: number;
  trend?: Array<{ date: string; value: number }>;
  resource_name: string;
  function_name: string;
  digital_signature: string;
  audit_recorded: boolean;
  raw_records_returned: boolean;
  capability: string;
  privacy_verification?: {
    mode?: string;
    status?: string;
    issuer?: string;
    boundary?: string;
    request_hash?: string;
    result_hash?: string;
    result_scope?: string;
    raw_records_returned?: boolean;
    raw_data_exported?: boolean;
  };
  connector_audit?: {
    status?: string;
    pointer_verified?: boolean;
    event_hash_verified?: boolean;
    verification_scope?: "SINGLE_SIGNED_EVENT_POINTER" | string;
    sequence?: number;
    previous_hash?: string;
    audit_hash?: string;
  };
  idempotent_replay?: boolean;
};

export type TrustedQueryTaskStatus = "QUEUED" | "RUNNING" | "PENDING_RETRY" | "SUCCEEDED" | "FAILED";

export type TrustedQueryTask = {
  task_id: string;
  status: TrustedQueryTaskStatus;
  status_url: string;
  result_url: string | null;
  attempt: number;
  max_attempts: number;
  failure_code: string | null;
  failure_summary: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  idempotent_replay: boolean;
};

const TRUSTED_QUERY_TASK_STATUSES = new Set<TrustedQueryTaskStatus>([
  "QUEUED",
  "RUNNING",
  "PENDING_RETRY",
  "SUCCEEDED",
  "FAILED",
]);

function trustedQueryTaskPayload(value: unknown): TrustedQueryTask {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError("可信查询任务状态响应格式无效", 502, undefined, { code: "TRUSTED_QUERY_TASK_INVALID" });
  }
  const task = value as Record<string, unknown>;
  const status = task.status;
  const nullableStrings = ["failure_code", "failure_summary", "created_at", "started_at", "completed_at"];
  const valid = typeof task.task_id === "string"
    && task.task_id.length > 0
    && typeof status === "string"
    && TRUSTED_QUERY_TASK_STATUSES.has(status as TrustedQueryTaskStatus)
    && typeof task.status_url === "string"
    && task.status_url.length > 0
    && (task.result_url === null || typeof task.result_url === "string")
    && typeof task.attempt === "number"
    && Number.isInteger(task.attempt)
    && task.attempt >= 0
    && typeof task.max_attempts === "number"
    && Number.isInteger(task.max_attempts)
    && task.max_attempts > 0
    && nullableStrings.every((field) => task[field] === null || typeof task[field] === "string")
    && typeof task.idempotent_replay === "boolean"
    && (status === "SUCCEEDED" ? typeof task.result_url === "string" && task.result_url.length > 0 : task.result_url === null);
  if (!valid) {
    throw new ApiError("可信查询任务状态响应格式无效", 502, undefined, { code: "TRUSTED_QUERY_TASK_INVALID" });
  }
  return task as TrustedQueryTask;
}

export type OrganizationRef = {
  org_id: string;
  org_name?: string | null;
  org_type?: string | null;
  status?: string | null;
} | null;

export type ContractListItem = CapabilityEnvelope & {
  contract_id: string;
  provider: OrganizationRef;
  consumer: OrganizationRef;
  purpose: string;
  status: string;
  agreement_state?: string | null;
  valid_from?: string | null;
  expires_at?: string | null;
  latest_event_version: number;
};

export type ContractListPayload = CapabilityEnvelope & {
  items: ContractListItem[];
  total: number;
  page: number;
  page_size: number;
  empty_state: boolean;
};

export type ContractEvent = CapabilityEnvelope & {
  event_id: string;
  contract_id: string;
  agreement_id: string;
  actor: OrganizationRef;
  actor_user_id?: string | null;
  actor_did?: string | null;
  event_type: string;
  message: string;
  terms: Record<string, unknown>;
  attachment_metadata: Array<Record<string, unknown>>;
  from_state: string;
  to_state: string;
  state_version: number;
  event_hash: string;
  created_at?: string | null;
};

export type ContractDetailPayload = CapabilityEnvelope & {
  contract: {
    contract_id: string;
    task_id?: string | null;
    provider: OrganizationRef;
    consumer: OrganizationRef;
    purpose: string;
    terms: Record<string, unknown>;
    policy_hash?: string | null;
    data_refs: Array<Record<string, unknown>>;
    status: string;
    valid_from?: string | null;
    expires_at?: string | null;
  };
  agreement: {
    agreement_id: string;
    provider_did?: string | null;
    consumer_did?: string | null;
    protocol_version?: string | null;
    state: string;
    requested_purpose?: string | null;
    algorithm_code?: string | null;
    data_product_ids: string[];
    offered_policy_hash?: string | null;
    negotiated_policy_hash?: string | null;
    valid_from?: string | null;
    expires_at?: string | null;
    max_uses?: number | null;
    use_count?: number | null;
    decision?: Record<string, unknown> | null;
    last_receipt?: Record<string, unknown> | null;
  } | null;
  events: ContractEvent[];
  timeline: Array<{
    event_id: string;
    event_type: string;
    from_state: string;
    to_state: string;
    state_version: number;
    created_at?: string | null;
  }>;
};

export type ContractEventInput = {
  message: string;
  terms?: Record<string, unknown>;
  attachments?: Array<Record<string, unknown>>;
};

export type TtcParticipant = {
  participant_id: string;
  org_id: string;
  organization: OrganizationRef;
  role_in_task: string;
  data_status: string;
  confirm_status: string;
};

export type TtcAttempt = {
  attempt_id: string;
  task_id: string;
  capsule_id?: string | null;
  attempt_no: number;
  current_state: string;
  status: string;
  trace_id?: string | null;
  failure_code?: string | null;
  failure_detail?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
};

export type TtcTransition = {
  transition_id: string;
  attempt_id?: string | null;
  task_id: string;
  sequence_no: number;
  from_state: string;
  to_state: string;
  actor_did?: string | null;
  agent_did?: string | null;
  trigger_code: string;
  reason: string;
  trace_id?: string | null;
  transition_hash: string;
  occurred_at?: string | null;
};

export type TtcSnapshot = {
  snapshot_id: string;
  attempt_id?: string | null;
  snapshot_version: number;
  rule_id?: string | null;
  rule_version?: string | null;
  rule_hash?: string | null;
  policy_refs: string[];
  contract_refs: string[];
  data_refs: string[];
  algorithm_code?: string | null;
  algorithm_version?: string | null;
  algorithm_hash?: string | null;
  snapshot_hash: string;
  frozen_by_did?: string | null;
  trace_id?: string | null;
  frozen_at?: string | null;
};

export type TtcDetailPayload = CapabilityEnvelope & {
  task: {
    task_id: string;
    task_name: string;
    capsule_id?: string | null;
    status: string;
    ttc_state: string;
    current_attempt?: number | null;
    state_version: number;
    current_stage?: string | null;
    phase_progress_estimate?: TtcPhaseProgressEstimate;
    execution_snapshot_id?: string | null;
    execution_snapshot_hash?: string | null;
    last_transition_at?: string | null;
  };
  participants: TtcParticipant[];
  attempts: TtcAttempt[];
  transitions: TtcTransition[];
  snapshots: TtcSnapshot[];
};

export type TtcEvent = CapabilityEnvelope & {
  event_id: string;
  kind: string;
  occurred_at?: string | null;
  state?: string | null;
  details: Record<string, unknown>;
};

export type TtcEventsPayload = CapabilityEnvelope & {
  task_id: string;
  items: TtcEvent[];
  cursor?: string | null;
  next_cursor?: string | null;
  has_more: boolean;
  limit: number;
};

export type TtcTransitionResult = CapabilityEnvelope & {
  task_id: string;
  ttc_state: string;
  state_version: number;
  transition: TtcTransition;
  idempotent_replay: boolean;
};

export type ComputationJob = {
  job_id: string;
  task_id: string;
  task_name?: string | null;
  task_kind?: "SETTLEMENT" | "TRUSTED_QUERY" | string;
  algorithm_code: string;
  adapter_code?: string | null;
  status: string;
  progress: number;
  duration_ms?: number | null;
  input_hashes: string[];
  output_hash?: string | null;
  result?: Record<string, unknown> | null;
  privacy_guarantees: Record<string, unknown>;
  logs: string[];
  attempt_id?: string | null;
  execution_snapshot_id?: string | null;
  state_version: number;
};

export type ComputationDetailPayload = CapabilityEnvelope & {
  job: ComputationJob;
  participants: Array<{ org_id: string; organization: OrganizationRef; role_in_task: string; data_status: string }>;
  attempt: TtcAttempt | null;
  snapshot: { snapshot_id: string; snapshot_hash?: string | null; rule_hash?: string | null; algorithm_hash?: string | null } | null;
  receipts: Array<{ evidence_id: string; stage: string; biz_type: string; biz_id: string; evidence_hash: string; chain_code?: string | null; status: string; tx_hash?: string | null; block_height?: number | null }>;
  external_execution: {
    capability_state: string;
    source_of_truth: string;
    adapter_code?: string | null;
    tee_attestation?: string | null;
    cross_domain_participants: string[];
  };
  action_reasons?: Record<string, string>;
};

export type ComputationEvent = CapabilityEnvelope & {
  sequence_no: number;
  kind: string;
  detail: string;
};

export type ComputationEventsPayload = CapabilityEnvelope & {
  job_id: string;
  items: ComputationEvent[];
  cursor?: string | null;
  next_cursor?: string | null;
  has_more: boolean;
  limit: number;
};

export type ComputationListPayload = CapabilityEnvelope & {
  items: ComputationJob[];
  total: number;
  page: number;
  page_size: number;
  empty_state: boolean;
};

export type ResultListItem = CapabilityEnvelope & {
  result_id: string;
  task_id: string;
  attempt_id?: string | null;
  org_id?: string | null;
  result_scope?: string | null;
  result_hash?: string | null;
  confirm_status: string;
};

export type ResultListPayload = CapabilityEnvelope & {
  items: ResultListItem[];
  total: number;
  page: number;
  page_size: number;
  empty_state: boolean;
};

export type ResultEvidence = {
  evidence_id: string;
  stage?: string | null;
  biz_type?: string | null;
  biz_id?: string | null;
  evidence_hash?: string | null;
  tx_hash?: string | null;
  block_height?: number | null;
  chain_code?: string | null;
  status?: string | null;
  verification_status?: "MATCHED" | "MISMATCH" | string | null;
  external_receipt_verified?: boolean;
  external_publication?: boolean;
};

export type ResultSignature = {
  signature_id: string;
  signer_org_id?: string | null;
  signer_did?: string | null;
  target_type?: string | null;
  target_hash?: string | null;
  verify_status?: string | null;
  created_at?: string | null;
};

export type ResultDetailPayload = CapabilityEnvelope & {
  result: {
    result_id: string;
    task_id: string;
    attempt_id?: string | null;
    org_id?: string | null;
    result_scope?: string | null;
    result?: Record<string, unknown> | null;
    result_hash?: string | null;
    confirm_status: string;
    created_at?: string | null;
  };
  task: { task_id?: string | null; ttc_state?: string | null; state_version?: number | null };
  signatures: ResultSignature[];
  evidence: ResultEvidence[];
  formal_evidence: Array<{
    batch_id: string;
    batch_type?: string | null;
    merkle_root?: string | null;
    leaf_count?: number | null;
    status?: string | null;
    items: Array<Record<string, unknown>>;
    outbox: Array<Record<string, unknown>>;
    anchors: Array<{
      anchor_id: string;
      adapter_code?: string | null;
      capability_label?: string | null;
      network_code?: string | null;
      anchor_payload_hash?: string | null;
      transaction_hash?: string | null;
      block_height?: number | null;
      status?: string | null;
      external_receipt_verified?: boolean;
      external_publication?: boolean;
      anchored_at?: string | null;
    }>;
  }>;
};

export type ResultCommandPayload = CapabilityEnvelope & {
  result?: ResultDetailPayload["result"];
  result_id?: string;
  confirm_status?: string;
  idempotent_replay?: boolean;
};

export type AuditRecord = CapabilityEnvelope & {
  record_type: "AUDIT_LOG" | "AUDIT_REPORT" | string;
  record_id: string;
  occurred_at?: string | null;
  action_code?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  result?: string | null;
  actor_org_id?: string | null;
  details?: Record<string, unknown> | null;
};

export type AuditListPayload = CapabilityEnvelope & {
  items: AuditRecord[];
  reports: AuditRecord[];
  total: number;
  page: number;
  page_size: number;
  empty_state: boolean;
};

export type AuditTaskPayload = CapabilityEnvelope & {
  task: {
    task_id: string;
    task_name?: string | null;
    ttc_state?: string | null;
    status?: string | null;
    state_version?: number | null;
  };
  audit_chain: AuditRecord[];
  transitions: Array<Record<string, unknown>>;
  reports: Array<Record<string, unknown>>;
  evidence: ResultEvidence[];
  execution_receipts: Array<{
    receipt_id: string;
    provider_org_id?: string | null;
    request_hash?: string | null;
    result_hash?: string | null;
    node_code?: string | null;
    status?: string | null;
    executed_at?: string | null;
    audit_sequence?: number | null;
    previous_audit_hash?: string | null;
    connector_audit_hash?: string | null;
    audit_event_verified?: boolean;
  }>;
};

export type AssistantSession = CapabilityEnvelope & {
  session_id: string;
  user_id: string;
  org_id: string;
  page_path?: string | null;
  entity_type?: string | null;
  entity_id?: string | null;
  status: string;
  state_version: number;
  last_message_at?: string | null;
  idempotent_replay?: boolean;
};

export type AssistantMessage = CapabilityEnvelope & {
  message_id: string;
  session_id: string;
  plan_id?: string | null;
  sequence_no: number;
  role: "USER" | "ASSISTANT" | string;
  content: string;
  intent_code?: string | null;
  status: string;
  created_at?: string | null;
  idempotent_replay?: boolean;
};

export type AssistantPlanStep = CapabilityEnvelope & {
  step_id: string;
  plan_id: string;
  sequence_no: number;
  action_code: string;
  tool_code?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  mode: "READ" | "WRITE" | "BLOCKED" | string;
  status: string;
  state_version: number;
  request_id?: string | null;
  invocation_id?: string | null;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error_code?: string | null;
};

export type AssistantPlan = CapabilityEnvelope & {
  plan_id: string;
  session_id: string;
  trigger_message_id?: string | null;
  intent_code: string;
  status: string;
  state_version: number;
  plan?: Record<string, unknown>;
  plan_hash?: string | null;
  steps: AssistantPlanStep[];
  idempotent_replay?: boolean;
};

export type AssistantSessionPayload = {
  session: AssistantSession;
  message?: AssistantMessage | null;
  assistant_message?: AssistantMessage | null;
  plan?: AssistantPlan | null;
};

export type AssistantMessagesPayload = CapabilityEnvelope & {
  session: AssistantSession;
  items: AssistantMessage[];
  total: number;
};

export type AssistantPlansPayload = CapabilityEnvelope & {
  session: AssistantSession;
  items: AssistantPlan[];
  total: number;
};

export type AssistantTool = CapabilityEnvelope & {
  tool_code: string;
  tool_name: string;
  service_code: string;
  assistant_actions: string[];
  enabled: boolean;
};

export type AssistantToolsPayload = CapabilityEnvelope & {
  items: AssistantTool[];
  total: number;
};

function queryString(params: Record<string, string | number | boolean | null | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export function loadTrustedContext(signal?: AbortSignal) {
  return api<TrustedContext>("/trust-space/context", { signal, cacheTtlMs: 2_000 });
}

export function loadWorkbench(signal?: AbortSignal) {
  return api<WorkbenchPayload>("/trust-space/workbench", { signal, cacheTtlMs: 2_000 });
}

export function loadNotifications(params: { page?: number; pageSize?: number } = {}, signal?: AbortSignal) {
  return api<NotificationListPayload>(`/trust-space/notifications${queryString({ page: params.page ?? 1, page_size: params.pageSize ?? 20 })}`, { signal, cache: "no-store", retry: 0 });
}

export function markNotificationRead(notificationId: string, options: ApiCommandOptions = {}) {
  return post<TrustedNotification>(`/trust-space/notifications/${encodeURIComponent(notificationId)}/read`, {}, options);
}

export function markAllNotificationsRead(options: ApiCommandOptions = {}) {
  return post<NotificationMarkAllPayload>("/trust-space/notifications/read-all", {}, options);
}

export function loadTrustedHelp(view: string, signal?: AbortSignal) {
  return api<TrustedHelpPayload>(`/trust-space/help${queryString({ view })}`, { signal, cacheTtlMs: 5_000, retry: 0 });
}

export function loadIdentity(signal?: AbortSignal) {
  return api<IdentityPayload>("/trust-space/identity", { signal, cacheTtlMs: 2_000 });
}

export function loadIdentityDirectory(signal?: AbortSignal) {
  return api<IdentityDirectoryPayload>("/trust-space/identities", { signal, cacheTtlMs: 2_000 });
}

export function loadDidDocument(didId: string, signal?: AbortSignal) {
  return api<DidDocumentPayload>(`/trust-space/identity/${encodeURIComponent(didId)}/document`, { signal, cacheTtlMs: 5_000 });
}

export function loadCatalog(
  params: {
    query?: string;
    assetType?: string;
    domain?: string;
    sensitivityLevel?: string;
    providerOrgId?: string;
    page?: number;
    pageSize?: number;
  },
  signal?: AbortSignal,
) {
  return api<CatalogPayload>(`/trust-space/catalog${queryString({
    q: params.query,
    asset_type: params.assetType,
    domain: params.domain,
    sensitivity_level: params.sensitivityLevel,
    provider_org_id: params.providerOrgId,
    page: params.page ?? 1,
    page_size: params.pageSize ?? 12,
  })}`, { signal, cacheTtlMs: 1_500 });
}

export function loadAsset(assetId: string, signal?: AbortSignal) {
  return api<AssetDetailPayload>(`/trust-space/assets/${encodeURIComponent(assetId)}`, { signal, cacheTtlMs: 2_000 });
}

export function createUsageRequest(
  body: {
    asset_id: string;
    asset_version_id?: string;
    purpose: string;
    usage_mode: string;
    requested_scope: Record<string, unknown>;
    requested_fields: string[];
    duration_days: number;
    terms: Record<string, unknown>;
  },
  options: ApiCommandOptions,
) {
  return post<UsageRequest>("/data/access-requests", body, options);
}

export function loadUsageRequests(
  params: { page?: number; pageSize?: number; status?: string; inbox?: boolean; mine?: boolean },
  signal?: AbortSignal,
) {
  return api<UsageRequestList>(`/data/access-requests${queryString({
    page: params.page ?? 1,
    page_size: params.pageSize ?? 20,
    status: params.status,
    inbox: params.inbox ? true : undefined,
    mine: params.mine ? true : undefined,
  })}`, { signal, cacheTtlMs: 1_500 });
}

export function loadUsageRequest(requestId: string, signal?: AbortSignal) {
  return api<UsageRequest>(`/data/access-requests/${encodeURIComponent(requestId)}`, { signal, cacheTtlMs: 1_500 });
}

export function loadAccessRules(params: { ownerOrgId?: string } = {}, signal?: AbortSignal) {
  return api<AccessRuleListPayload>(`/data/access-rules${queryString({ owner_org_id: params.ownerOrgId })}`, { signal, cacheTtlMs: 1_500 });
}

export function createAccessRule(
  body: {
    rule_code: string;
    energy_domain?: string;
    asset_id?: string;
    resource_id: string;
    function_code: string;
    mode: "AUTO_CALL" | "ENTERPRISE_APPROVAL" | "FORBIDDEN";
    scope?: Record<string, unknown>;
    limits?: Record<string, unknown>;
  },
  options: ApiCommandOptions,
) {
  return post<AccessRule>("/data/access-rules", body, options);
}

export function revokeAccessRule(ruleId: string, options: ApiCommandOptions) {
  return post<AccessRule>(`/data/access-rules/${encodeURIComponent(ruleId)}/revoke`, {}, options);
}

export function parseTrustedQuery(question: string) {
  return post<QueryIntent>("/trust-space/query/parse", { question });
}

export function loadPrototypeHeader(signal?: AbortSignal) {
  return api<PrototypeHeaderPayload>("/prototype/header", { signal, cacheTtlMs: 2_000 });
}

export function loadPrototypeDashboard(signal?: AbortSignal) {
  return api<PrototypeDashboardPayload>("/prototype/dashboard", { signal, cacheTtlMs: 1_500 });
}

export function askPrototypeQuery(text: string, options: ApiCommandOptions = {}) {
  return post<PrototypeQueryPayload>("/prototype/query", { text }, options);
}

export function loadConnectorCatalog(signal?: AbortSignal) {
  return api<ConnectorCatalogPayload>("/trust-space/connectors/catalog", { signal, cache: "no-store" });
}

export function issueConnectorUploadTicket(
  resourceId: string,
  classification: ConnectorClassification,
  options: ApiCommandOptions = {},
) {
  return post<ConnectorTicketPayload>("/trust-space/connectors/tickets", {
    resource_id: resourceId,
    classification,
  }, options);
}

export function registerConnectorReceipt(receipt: ConnectorSignedReceipt, options: ApiCommandOptions = {}) {
  return post<ConnectorReceiptPayload>("/trust-space/connectors/receipts", receipt, options);
}

export function loadConnectorReceipt(ticketId: string, signal?: AbortSignal) {
  return api<ConnectorReceiptPayload>(`/trust-space/connectors/receipts/${encodeURIComponent(ticketId)}`, {
    signal,
    cache: "no-store",
  });
}

const CONNECTOR_DIRECT_TIMEOUT_MS = 60_000;

function connectorEndpoint(value: string): string {
  try {
    const url = new URL(value);
    if ((url.protocol !== "https:" && url.protocol !== "http:") || url.username || url.password) throw new Error("unsafe URL");
    return url.toString();
  } catch {
    throw new ApiError("企业连接器地址配置无效，请联系管理员", 503, undefined, { code: "CONNECTOR_ENDPOINT_INVALID" });
  }
}

function isAbortError(reason: unknown): boolean {
  return reason instanceof Error && reason.name === "AbortError";
}

function connectorHttpError(status: number, operation: "upload" | "lookup"): ApiError {
  if (operation === "lookup" && status === 404) {
    return new ApiError("连接器尚未生成该票据的签名回执，请稍后再试；请勿重复上传", 404, undefined, { code: "CONNECTOR_RECEIPT_PENDING" });
  }
  if (operation === "lookup" && (status === 400 || status === 422)) {
    return new ApiError("签名回执补查凭证未通过连接器校验，请刷新目录后重试", status, undefined, { code: "CONNECTOR_TICKET_INVALID" });
  }
  if (status === 400 || status === 413 || status === 422) {
    return new ApiError("CSV 未通过企业连接器校验，请核对列名、格式和数据内容", status, undefined, { code: "CONNECTOR_VALIDATION" });
  }
  if (status === 401 || status === 403 || status === 410) {
    return new ApiError("一次性上传凭证无效、已过期或不属于当前连接器，请重新获取", status, undefined, { code: "CONNECTOR_TICKET_INVALID" });
  }
  if (status === 409) {
    return new ApiError("该一次性上传凭证可能已使用，请先恢复签名回执；请勿重复上传", status, undefined, { code: "CONNECTOR_TICKET_USED" });
  }
  if (status >= 500) {
    return new ApiError("企业连接器暂时离线或不可用，请稍后重试", status, undefined, { code: "CONNECTOR_UNAVAILABLE" });
  }
  return new ApiError("企业连接器拒绝了本次请求，请刷新目录后重试", status, undefined, { code: "CONNECTOR_REQUEST_REJECTED" });
}

function isConnectorSignedReceipt(value: unknown): value is ConnectorSignedReceipt {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const receipt = value as Record<string, unknown>;
  const stringFields = [
    "receipt_id", "ticket_id", "connector_id", "organization_id", "energy_domain", "resource_id",
    "resource_name", "schema_version", "schema_hash", "content_hash", "local_ref", "audit_hash",
    "issued_at", "signature", "public_key",
  ];
  return stringFields.every((field) => typeof receipt[field] === "string" && receipt[field] !== "")
    && ["version", "record_count", "byte_size", "audit_sequence"].every((field) => typeof receipt[field] === "number")
    && receipt.signature_algorithm === "Ed25519"
    && receipt.signature_valid === true;
}

async function directConnectorReceipt(
  urlValue: string,
  init: RequestInit,
  operation: "upload" | "lookup",
  expectedStatus: number,
  signal?: AbortSignal,
): Promise<ConnectorSignedReceipt> {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, CONNECTOR_DIRECT_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", abortFromCaller, { once: true });
  try {
    const response = await fetch(connectorEndpoint(urlValue), {
      ...init,
      signal: controller.signal,
      credentials: "omit",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
    if (response.status !== expectedStatus) throw connectorHttpError(response.status, operation);
    if (!response.headers.get("Content-Type")?.toLowerCase().includes("application/json")) {
      throw new ApiError("企业连接器返回格式无效，未登记任何中央元数据", 502, undefined, { code: "CONNECTOR_INVALID_RESPONSE" });
    }
    let value: unknown;
    try {
      value = await response.json();
    } catch {
      throw new ApiError("企业连接器返回格式无效，未登记任何中央元数据", 502, undefined, { code: "CONNECTOR_INVALID_RESPONSE" });
    }
    if (!isConnectorSignedReceipt(value)) {
      throw new ApiError("企业连接器返回的签名回执不完整，未登记任何中央元数据", 502, undefined, { code: "CONNECTOR_INVALID_RECEIPT" });
    }
    return value;
  } catch (reason) {
    if (reason instanceof ApiError) throw reason;
    if (isAbortError(reason)) {
      if (timedOut) throw new ApiError("企业连接器响应超时，请稍后恢复签名回执；请勿重复上传", 408, undefined, { code: "CONNECTOR_TIMEOUT" });
      throw reason;
    }
    if (reason instanceof TypeError) {
      throw new ApiError("浏览器无法直连企业连接器，请确认连接器在线且已允许当前站点跨域访问", 503, undefined, { code: "CONNECTOR_NETWORK_OR_CORS" });
    }
    throw new ApiError("企业连接器请求失败，请稍后重试", 503, undefined, { code: "CONNECTOR_UNAVAILABLE" });
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener("abort", abortFromCaller);
  }
}

export function uploadConnectorCsv(
  uploadUrl: string,
  ticket: ConnectorTicket,
  file: File,
  signal?: AbortSignal,
) {
  const form = new FormData();
  form.append("ticket", JSON.stringify(ticket));
  form.append("file", file);
  return directConnectorReceipt(uploadUrl, { method: "POST", body: form }, "upload", 201, signal);
}

export function lookupConnectorReceipt(
  receiptLookupUrl: string,
  ticket: ConnectorTicket,
  signal?: AbortSignal,
) {
  return directConnectorReceipt(receiptLookupUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ticket),
  }, "lookup", 200, signal);
}

export function loadPrototypePolicy(signal?: AbortSignal) {
  return api<PrototypePolicyPayload>("/prototype/policy", { signal, cacheTtlMs: 1_500 });
}

export function addPrototypePolicyRule(body: { resource_id: string; role: string; purpose?: string; action: string }, options: ApiCommandOptions = {}) {
  return post<{ rule_id: string; evidence_id: string }>("/prototype/policy/rules", body, options);
}

export function deletePrototypePolicyRule(resourceId: string, role: string, options: ApiCommandOptions = {}) {
  return api<{ rule_id: string; evidence_id: string }>(`/prototype/policy/rules${queryString({ resource_id: resourceId, role })}`, { ...options, method: "DELETE" });
}

export function loadPrototypeAudit(limit = 20, signal?: AbortSignal) {
  return api<PrototypeAuditPayload>(`/prototype/audit${queryString({ limit })}`, { signal, cacheTtlMs: 1_000 });
}

export function verifyPrototypeAudit(options: ApiCommandOptions = {}) {
  return post<{ ok: boolean; message: string; checked: number }>("/prototype/audit/verify", {}, options);
}

export function tamperPrototypeAudit(options: ApiCommandOptions = {}) {
  return post<{ ok: boolean; event_id: string; affected_block: number | null; message: string }>("/prototype/audit/tamper", {}, options);
}

export function restorePrototypeAudit(options: ApiCommandOptions = {}) {
  return post<{ ok: boolean; message: string }>("/prototype/audit/restore", {}, options);
}

export function confirmTrustedQuery(body: {
  authorization_id?: string;
  provider_org_id?: string;
  energy_domain: string;
  resource: string;
  function: string;
  start_date: string;
  end_date: string;
  region?: string;
  decimals: number;
}, signal?: AbortSignal) {
  return post<QueryConfirmation>("/trust-space/query/confirm", body, { signal });
}

export function executeTrustedQuery(body: {
  authorization_id?: string;
  provider_org_id?: string;
  energy_domain: string;
  resource: string;
  function: string;
  start_date: string;
  end_date: string;
  region?: string;
  hour?: number;
  threshold?: number;
  group_by?: string;
  decimals: number;
  confirmation_token: string;
}, idempotencyKey: string, signal?: AbortSignal) {
  return post<unknown>("/trust-space/query/execute", body, {
    idempotencyKey,
    signal,
    timeoutMs: 20_000,
  }).then(trustedQueryTaskPayload);
}

export function loadTrustedQueryTask(taskId: string, signal?: AbortSignal) {
  return api<unknown>(`/trust-space/query/tasks/${encodeURIComponent(taskId)}`, {
    signal,
    cache: "no-store",
    retry: 0,
  }).then(trustedQueryTaskPayload);
}

export function loadTrustedQueryResult(taskId: string, signal?: AbortSignal) {
  return api<ControlledQueryResult>(`/trust-space/query/tasks/${encodeURIComponent(taskId)}/result`, {
    signal,
    cache: "no-store",
    retry: 0,
  });
}

export type UsageRequestAction = "review" | "approve" | "reject" | "withdraw" | "revoke";

export function transitionUsageRequest(
  requestId: string,
  action: UsageRequestAction,
  reason: string,
  options: ApiCommandOptions,
) {
  const body = action === "review" ? { note: reason } : { reason };
  return post<UsageRequest>(
    `/data/access-requests/${encodeURIComponent(requestId)}/${action}`,
    body,
    options,
  );
}

export function loadContracts(params: { page?: number; pageSize?: number; state?: string }, signal?: AbortSignal) {
  return api<ContractListPayload>(`/trust-space/contracts${queryString({ page: params.page ?? 1, page_size: params.pageSize ?? 20, state: params.state })}`, { signal, cacheTtlMs: 1_500 });
}

export function loadContract(contractId: string, signal?: AbortSignal) {
  return api<ContractDetailPayload>(`/trust-space/contracts/${encodeURIComponent(contractId)}`, { signal, cacheTtlMs: 1_500 });
}

export type ContractAction = "comment" | "counter" | "accept" | "reject";

export function postContractAction(contractId: string, action: ContractAction, body: ContractEventInput, options: ApiCommandOptions) {
  if (action === "comment") {
    return post<ContractEvent>(`/trust-space/contracts/${encodeURIComponent(contractId)}/events`, { event_type: "COMMENT", ...body }, options);
  }
  return post<ContractEvent>(`/trust-space/contracts/${encodeURIComponent(contractId)}/${action}`, body, options);
}

export function loadTtc(taskId: string, signal?: AbortSignal) {
  return api<TtcDetailPayload>(`/trust-space/ttc/${encodeURIComponent(taskId)}`, { signal, cacheTtlMs: 1_500 });
}

export type TtcListItem = CapabilityEnvelope & {
  task_id: string;
  task_name: string;
  capsule_id?: string | null;
  status: string;
  ttc_state: string;
  current_stage?: string | null;
  current_attempt?: number | null;
  state_version: number;
  updated_at?: string | null;
  phase_progress_estimate?: TtcPhaseProgressEstimate;
};

export type TtcListPayload = CapabilityEnvelope & {
  items: TtcListItem[];
  total: number;
  page: number;
  page_size: number;
  status?: string | null;
  empty_state: boolean;
};

export function loadTtcList(params: { page?: number; pageSize?: number; status?: string }, signal?: AbortSignal) {
  return api<TtcListPayload>(`/trust-space/ttc${queryString({ page: params.page ?? 1, page_size: params.pageSize ?? 12, status: params.status })}`, { signal, cacheTtlMs: 1_000 });
}

export function loadTtcEvents(taskId: string, params: { cursor?: string; limit?: number }, signal?: AbortSignal) {
  return api<TtcEventsPayload>(`/trust-space/ttc/${encodeURIComponent(taskId)}/events${queryString({ cursor: params.cursor, limit: params.limit ?? 50 })}`, { signal, cache: "no-store", retry: 0 });
}

export function transitionTtc(taskId: string, body: { to_state: string; trigger: string; reason: string; attempt_id?: string; agent_did?: string; trace_id?: string }, options: ApiCommandOptions) {
  return post<TtcTransitionResult>(`/trust-space/ttc/${encodeURIComponent(taskId)}/transitions`, body, options);
}

export function loadComputations(params: { page?: number; pageSize?: number; status?: string }, signal?: AbortSignal) {
  return api<ComputationListPayload>(`/trust-space/computations${queryString({ page: params.page ?? 1, page_size: params.pageSize ?? 20, status: params.status })}`, { signal, cacheTtlMs: 1_500 });
}

export function loadComputation(jobId: string, signal?: AbortSignal) {
  return api<ComputationDetailPayload>(`/trust-space/computations/${encodeURIComponent(jobId)}`, { signal, cacheTtlMs: 1_500 });
}

export function loadComputationEvents(jobId: string, params: { cursor?: string; limit?: number }, signal?: AbortSignal) {
  return api<ComputationEventsPayload>(`/trust-space/computations/${encodeURIComponent(jobId)}/events${queryString({ cursor: params.cursor, limit: params.limit ?? 50 })}`, { signal, cache: "no-store", retry: 0 });
}

export type ComputationAction = "cancel" | "retry";

export function controlComputation(
  jobId: string,
  action: ComputationAction,
  reason: string,
  options: ApiCommandOptions,
) {
  return post<ComputationDetailPayload & { action: ComputationAction; action_reason: string; idempotent_replay: boolean }>(
    `/trust-space/computations/${encodeURIComponent(jobId)}/${action}`,
    { reason },
    options,
  );
}

export function loadResults(params: { page?: number; pageSize?: number; taskId?: string }, signal?: AbortSignal) {
  return api<ResultListPayload>(`/trust-space/results${queryString({ page: params.page ?? 1, page_size: params.pageSize ?? 20, task_id: params.taskId })}`, { signal, cacheTtlMs: 1_500 });
}

export function loadResult(resultId: string, signal?: AbortSignal) {
  return api<ResultDetailPayload>(`/trust-space/results/${encodeURIComponent(resultId)}`, { signal, cacheTtlMs: 1_500 });
}

export function confirmResult(resultId: string, body: { decision: "APPROVE" | "REJECT"; opinion: string }, options: ApiCommandOptions) {
  return post<ResultCommandPayload>(`/trust-space/results/${encodeURIComponent(resultId)}/confirm`, body, options);
}

export function verifyEvidence(evidenceId: string, signal?: AbortSignal) {
  return api<CapabilityEnvelope & { matched?: boolean; evidence_id?: string; expected_hash?: string; actual_hash?: string; external_receipt_verified?: boolean }>(`/trust-space/evidence/${encodeURIComponent(evidenceId)}/verify`, { signal, cache: "no-store", retry: 0 });
}

export function loadAudit(params: { page?: number; pageSize?: number }, signal?: AbortSignal) {
  return api<AuditListPayload>(`/trust-space/audit${queryString({ page: params.page ?? 1, page_size: params.pageSize ?? 50 })}`, { signal, cacheTtlMs: 1_500 });
}

export function loadAuditTask(taskId: string, signal?: AbortSignal) {
  return api<AuditTaskPayload>(`/trust-space/audit/tasks/${encodeURIComponent(taskId)}`, { signal, cacheTtlMs: 1_500 });
}

const TRUSTED_API_BASE = import.meta.env.VITE_API_BASE || "/api";

export async function downloadAudit(format: "json" | "csv", signal?: AbortSignal) {
  const token = sessionStorage.getItem("hiddenchain_token");
  const response = await fetch(`${TRUSTED_API_BASE}/trust-space/audit/export?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    signal,
  });
  if (!response.ok) {
    let message = "审计导出失败，请稍后重试";
    try {
      const body = await response.json() as { detail?: string | { message?: string } };
      const detail = body.detail;
      if (typeof detail === "string") message = detail;
      else if (detail?.message) message = detail.message;
    } catch {
      // Preserve the safe local fallback when the server did not return JSON.
    }
    throw new ApiError(message, response.status);
  }
  const disposition = response.headers.get("content-disposition") || "";
  const encodedFilename = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const filename = encodedFilename
    ? decodeURIComponent(encodedFilename)
    : disposition.match(/filename=([^;]+)/i)?.[1]?.replace(/["']/g, "") || `审计记录.${format}`;
  return { blob: await response.blob(), filename, contentType: response.headers.get("content-type") || "" };
}

export function createAssistantSession(
  body: { page_path?: string; entity_type?: string; entity_id?: string },
  options: ApiCommandOptions,
) {
  return post<AssistantSession>("/trust-space/assistant/sessions", body, options);
}

export function resumeAssistantSession(sessionId: string, options: ApiCommandOptions) {
  return post<AssistantSession>(`/trust-space/assistant/sessions/${encodeURIComponent(sessionId)}/resume`, {}, options);
}

export function loadAssistantMessages(sessionId: string, signal?: AbortSignal) {
  return api<AssistantMessagesPayload>(`/trust-space/assistant/sessions/${encodeURIComponent(sessionId)}/messages`, { signal, cache: "no-store", retry: 2 });
}

export function loadAssistantPlans(sessionId: string, signal?: AbortSignal) {
  return api<AssistantPlansPayload>(`/trust-space/assistant/sessions/${encodeURIComponent(sessionId)}/plans`, { signal, cache: "no-store", retry: 2 });
}

export function postAssistantMessage(
  sessionId: string,
  content: string,
  options: ApiCommandOptions,
) {
  return post<AssistantSessionPayload>(`/trust-space/assistant/sessions/${encodeURIComponent(sessionId)}/messages`, { content }, options);
}

export function loadAssistantTools(signal?: AbortSignal) {
  return api<AssistantToolsPayload>("/trust-space/assistant/tools", { signal, cacheTtlMs: 2_000, retry: 2 });
}

export function loadAssistantPlan(sessionId: string, planId: string, signal?: AbortSignal) {
  return api<{ session: AssistantSession; plan: AssistantPlan }>(`/trust-space/assistant/sessions/${encodeURIComponent(sessionId)}/plans/${encodeURIComponent(planId)}`, { signal, cache: "no-store", retry: 0 });
}

export type AssistantPlanAction = "execute" | "cancel" | "retry";

export function runAssistantPlanAction(
  sessionId: string,
  planId: string,
  action: AssistantPlanAction,
  options: ApiCommandOptions,
  stepId?: string,
) {
  const body = action === "execute" ? { step_id: stepId } : {};
  return post<{ session: AssistantSession; plan: AssistantPlan }>(
    `/trust-space/assistant/sessions/${encodeURIComponent(sessionId)}/plans/${encodeURIComponent(planId)}/${action}`,
    body,
    options,
  );
}
