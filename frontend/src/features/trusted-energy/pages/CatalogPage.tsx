import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Database, Search, SlidersHorizontal, UserRound } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { loadCatalog, type CatalogAsset } from "../trusted-space-api";
import { ASSET_TYPE_LABELS, DOMAIN_LABELS, labelForCode } from "../../../types";
import { routeForView } from "../types";
import { Badge, Button, Card, CardContent, Input, RemoteState, Select, StatusBadge } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { useRemote } from "../../../hooks";
import { sensitivityLabel } from "../trusted-space-labels";

const PAGE_SIZE = 12;

function filterValues(items: CatalogAsset[], value: string | null, field: "asset_type" | "domain") {
  const values = items.map((item) => field === "asset_type" ? item.asset_type : item.domain || "");
  if (value) values.push(value);
  return Array.from(new Set(values.filter(Boolean))).sort((left, right) => left.localeCompare(right, "zh-CN"));
}

export function CatalogPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchText = searchParams.get("q") || "";
  const type = searchParams.get("asset_type") || "";
  const domain = searchParams.get("domain") || "";
  const level = searchParams.get("sensitivity_level") || "";
  const focusSearch = searchParams.get("focus") === "search";
  const page = Math.max(1, Number(searchParams.get("page") || "1") || 1);
  const [debouncedQuery, setDebouncedQuery] = useState(searchText.trim());
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedQuery(searchText.trim()), 250);
    return () => window.clearTimeout(timeout);
  }, [searchText]);

  useEffect(() => {
    if (!focusSearch) return undefined;
    const frame = window.requestAnimationFrame(() => searchInputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [focusSearch]);

  const remote = useRemote(
    (signal) => loadCatalog({
      query: debouncedQuery || undefined,
      assetType: type || undefined,
      domain: domain || undefined,
      sensitivityLevel: level || undefined,
      page,
      pageSize: PAGE_SIZE,
    }, signal),
    [debouncedQuery, type, domain, level, page],
  );
  const payload = remote.data;
  const items = useMemo(() => payload?.items ?? [], [payload]);
  const typeOptions = useMemo(() => filterValues(items, type, "asset_type"), [items, type]);
  const domainOptions = useMemo(() => filterValues(items, domain, "domain"), [items, domain]);

  function updateFilter(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.set("page", "1");
    setSearchParams(next);
  }

  function clearFilters() {
    setSearchParams(new URLSearchParams());
  }

  const canGoPrevious = page > 1;
  const canGoNext = Boolean(payload && page * payload.page_size < payload.total);

  return <PageFrame title="数据目录" description="发现可申请的数据资产，先确认用途、敏感等级和可用方式。" action={<Badge tone="info"><SlidersHorizontal size={14} />筛选自动保存</Badge>}>
    <Card className="trusted-filter-card"><CardContent>
      <div className="trusted-filter-row">
        <label className="trusted-search-field"><Search size={16} /><Input ref={searchInputRef} value={searchText} onChange={(event) => updateFilter("q", event.target.value)} placeholder="搜索资产名称、提供方、标识…" aria-label="搜索数据资产" /></label>
        <Select value={type} onChange={(event) => updateFilter("asset_type", event.target.value)} options={[{ value: "", label: "全部类型" }, ...typeOptions.map((item) => ({ value: item, label: ASSET_TYPE_LABELS[item] || labelForCode(item) }))]} />
        <Select value={domain} onChange={(event) => updateFilter("domain", event.target.value)} options={[{ value: "", label: "全部领域" }, ...domainOptions.map((item) => ({ value: item, label: DOMAIN_LABELS[item] || labelForCode(item) }))]} />
        <Select value={level} onChange={(event) => updateFilter("sensitivity_level", event.target.value)} options={[{ value: "", label: "全部等级" }, { value: "L1", label: `${sensitivityLabel("L1")}（公开）` }, { value: "L2", label: `${sensitivityLabel("L2")}（内部）` }, { value: "L3", label: `${sensitivityLabel("L3")}（敏感）` }, { value: "L4", label: `${sensitivityLabel("L4")}（高敏）` }]} />
        <Button variant="ghost" size="icon" aria-label="清空筛选" title="清空筛选" onClick={clearFilters}><SlidersHorizontal size={15} /></Button>
      </div>
      <div className="trusted-filter-summary"><span><Database size={13} />共 {payload?.total ?? 0} 项资产</span><span>跨能源可发现目录元数据，使用仍需提供方授权</span><Badge tone={payload?.capability_state === "LOCAL_REAL" ? "success" : "warning"}>{payload?.source_of_truth ? labelForCode(payload.source_of_truth) : "正在读取真实目录"}</Badge></div>
    </CardContent></Card>

    {remote.loading && !payload && <RemoteState loading />}
    {remote.error && !payload && <RemoteState error={remote.error} onRetry={() => void remote.reload()} />}
    {payload && !items.length && <RemoteState empty emptyLabel="当前范围暂无匹配的数据资产" />}
    {payload && items.length > 0 && <>
      <div className="trusted-catalog-list">{items.map((asset) => <CatalogAssetRow key={asset.asset_id} asset={asset} onOpen={() => navigate(routeForView("asset", asset.asset_id))} onApply={() => navigate(routeForView("apply", asset.asset_id))} />)}</div>
      <div className="trusted-step-footer" aria-label="数据目录分页"><span>第 {page} 页 · 共 {payload.total} 项</span><div><Button variant="secondary" size="sm" disabled={!canGoPrevious || remote.loading} onClick={() => updateFilter("page", String(page - 1))}>上一页</Button><Button variant="secondary" size="sm" disabled={!canGoNext || remote.loading} onClick={() => updateFilter("page", String(page + 1))}>下一页</Button></div></div>
    </>}
    {payload && remote.refreshing && <div className="trusted-inline-status" role="status">正在刷新目录…</div>}
  </PageFrame>;
}

function CatalogAssetRow({ asset, onOpen, onApply }: { asset: CatalogAsset; onOpen: () => void; onApply: () => void }) {
  const providerName = asset.provider.org_name || asset.provider.org_id;
  const version = asset.latest_version;
  const assetName = asset.asset_name?.trim() || "未命名数据资源";
  return <Card className="trusted-asset-row"><CardContent><div className="trusted-asset-main"><span className="trusted-asset-icon"><Database size={18} /></span><div><div className="trusted-asset-title"><h2>{assetName}</h2><Badge tone={asset.sensitivity_level === "L4" ? "danger" : asset.sensitivity_level === "L3" ? "warning" : "neutral"}>{sensitivityLabel(asset.sensitivity_level)}</Badge><StatusBadge value={asset.status} /></div><p>{DOMAIN_LABELS[asset.domain || ""] || "未标注能源范围"}{assetName === "未命名数据资源" ? "，请由提供企业补充中文名称" : ""}</p><div className="trusted-asset-meta"><span><UserRound size={13} />{providerName}</span><span>{ASSET_TYPE_LABELS[asset.asset_type] || "数据资源"} · {labelForCode(asset.source.capability_label)}</span><span>{version ? `第 ${version.version_no} 版` : "未发布"}</span></div></div></div><div className="trusted-asset-stats"><div><small>目录记录数</small><strong>{version?.record_count ?? "暂无"}</strong></div><div><small>数据状态</small><strong>{labelForCode(version?.status)}</strong></div><div><small>连接状态</small><strong>{labelForCode(asset.source.status)}</strong></div><div className="trusted-asset-actions"><Button variant="secondary" size="sm" onClick={onOpen}>查看详情 <ArrowUpRight size={13} /></Button>{asset.actions.can_request_usage ? <Button variant="primary" size="sm" onClick={onApply}>申请授权</Button> : <Button variant="secondary" size="sm" disabled title="当前账号不能申请该数据资源">申请授权</Button>}</div></div></CardContent></Card>;
}
