export type SettlementPeriod = { periodStart: string; periodEnd: string };
type CatalogEntry = {
  asset_type?: string;
  owner_org_id?: string;
  trade_batch_no?: string;
  commitment_confirmed?: boolean;
  period_start?: unknown;
  period_end?: unknown;
  quality?: { validation_status?: string; period?: unknown; period_start?: unknown; period_end?: unknown };
};

const DAY_MS = 86_400_000;

function validDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value;
}

export function parseSettlementPeriod(value: unknown): SettlementPeriod | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (/^\d{4}-\d{2}$/.test(text)) {
    const first = `${text}-01`;
    if (!validDay(first)) return null;
    const end = new Date(`${first}T00:00:00Z`);
    end.setUTCMonth(end.getUTCMonth() + 1);
    end.setUTCDate(0);
    return { periodStart: first, periodEnd: end.toISOString().slice(0, 10) };
  }
  const [start, end = start, ...rest] = text.split("/");
  if (rest.length || !validDay(start) || !validDay(end) || start > end) return null;
  return { periodStart: start, periodEnd: end };
}

export function settlementDateCount(periodStart: string, periodEnd: string): number {
  const period = parseSettlementPeriod(`${periodStart}/${periodEnd}`);
  return period ? (Date.parse(`${periodEnd}T00:00:00Z`) - Date.parse(`${periodStart}T00:00:00Z`)) / DAY_MS + 1 : 0;
}

export function catalogSettlementPeriod(entry: CatalogEntry): SettlementPeriod | null {
  const declared = entry.quality?.period;
  const parsed = declared === undefined || declared === null ? null : parseSettlementPeriod(declared);
  const start = entry.period_start ?? entry.quality?.period_start;
  const end = entry.period_end ?? entry.quality?.period_end;
  if ((start === undefined || start === null) && (end === undefined || end === null)) return parsed;
  const fields = typeof start === "string" && typeof end === "string" ? parseSettlementPeriod(`${start}/${end}`) : null;
  if (!fields || (declared !== undefined && declared !== null && (!parsed || parsed.periodStart !== fields.periodStart || parsed.periodEnd !== fields.periodEnd))) return null;
  return fields;
}

export function findSettlementData<T extends CatalogEntry>(entries: T[], assetType: string, ownerId: string, batch: string, periodStart: string, periodEnd: string): T | undefined {
  return entries.find((entry) => {
    const period = catalogSettlementPeriod(entry);
    return entry.asset_type === assetType && entry.owner_org_id === ownerId && entry.trade_batch_no === batch.trim()
      && entry.quality?.validation_status === "PASSED" && period?.periodStart === periodStart && period.periodEnd === periodEnd;
  });
}

export function findReadySettlementTemplate<T extends CatalogEntry>(entries: T[], generatorIds: string[], retailerIds: string[]) {
  for (const generation of entries) {
    const period = catalogSettlementPeriod(generation);
    const batch = generation.trade_batch_no;
    const generatorId = generation.owner_org_id;
    if (!period || !batch || !generatorId || !generatorIds.includes(generatorId) || generation.asset_type !== "GENERATION_DATA" || !generation.commitment_confirmed) continue;
    if (findSettlementData(entries, "GENERATION_DATA", generatorId, batch, period.periodStart, period.periodEnd) !== generation) continue;
    for (const retailerId of retailerIds) {
      const retail = findSettlementData(entries, "RETAIL_DATA", retailerId, batch, period.periodStart, period.periodEnd);
      if (retail?.commitment_confirmed) return { ...period, batch, generatorId, retailerId };
    }
  }
  return null;
}
