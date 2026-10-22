import { api, post, type ApiCommandOptions } from "../../api";

export type ElectricityField = { key: string; label: string; unit: string; min: string; max: string };
export type ElectricitySource = { title: string; reference: string; url: string; scope: string };
export type ElectricityScenario = { id: string; title: string; scope: string; example: string; fields: ElectricityField[]; formulas: string[] };
export type ElectricityCatalog = { version: string; sources: ElectricitySource[]; scenarios: ElectricityScenario[] };
export type ElectricityStep = { key: string; label: string; expression: string; value: string; unit: string };
export type ElectricityRecord = {
  id: string;
  session_id: string;
  status: "AWAITING_CONFIRMATION" | "SUCCEEDED";
  state_version: number;
  created_at: string;
  question: string;
  scenario: string;
  title: string;
  scope: string;
  parameters: Record<string, string>;
  origins: Record<string, string>;
  missing: string[];
  warnings: string[];
  saved: boolean;
  rule_version: string;
  sources: ElectricitySource[];
  formulas: string[];
  result: null | { steps: ElectricityStep[]; summary: ElectricityStep[]; checks: string[]; policy_check: string; input_source: string; result_hash: string };
};

const BASE = "/trust-space/assistant/electricity";

export function formatElectricityValue(value: string) {
  const [integer, fraction = ""] = value.split(".");
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const trimmed = fraction.replace(/0+$/, "");
  return trimmed ? `${grouped}.${trimmed}` : grouped;
}

export const loadElectricityCatalog = () => api<ElectricityCatalog>(`${BASE}/catalog`);
export const loadElectricityHistory = (sessionId: string) => api<{ items: ElectricityRecord[] }>(`${BASE}/sessions/${encodeURIComponent(sessionId)}`, { cacheTtlMs: 0 });
export const loadElectricityCases = () => api<{ items: ElectricityRecord[] }>(`${BASE}/cases`, { cacheTtlMs: 0 });
export const prepareElectricityCalculation = (body: { session_id: string; question: string; scenario?: string; based_on?: string }, options: ApiCommandOptions) => post<ElectricityRecord>(`${BASE}/prepare`, body, options);
export const calculateElectricity = (record: ElectricityRecord, parameters: Record<string, string>) => post<ElectricityRecord>(`${BASE}/${encodeURIComponent(record.id)}/calculate`, { parameters, confirmed: true, state_version: record.state_version });
export const saveElectricityCase = (id: string) => post<ElectricityRecord>(`${BASE}/${encodeURIComponent(id)}/save`, {});
