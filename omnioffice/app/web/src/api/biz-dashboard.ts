/** 数据大屏 API 客户端。
 *
 * 复用全局 api() 封装（统一错误格式 + 网关前缀 + 登录失效提示）。
 * 身份参数一律不由前端传递，服务端以网关 Header 为准。
 */
import { api, API_BASE } from "./client";

export interface BizCustomer {
  id: number;
  name: string;
  contact: string;
  phone: string;
  address: string;
  industry: string;
  level: string;
  region: string;
  /** 客户来源 code（referral/bid_win/campaign/outreach/channel/weekly/other），空=未指定 */
  source: string;
  /** 来源补充说明（仅 source = other 时有意义） */
  sourceNote: string;
  tags: string[];
  note: string;
  status: string;
  createdAt: string;
}

export interface BizTripStop {
  id: number;
  seq: number;
  name: string;
  lng: number | null;
  lat: number | null;
  arriveDate: string;
  note: string;
}

export interface BizTrip {
  id: number;
  customerId: number | null;
  title: string;
  originName: string;
  originLng: number | null;
  originLat: number | null;
  destName: string;
  destLng: number | null;
  destLat: number | null;
  startDate: string;
  endDate: string;
  transport: string;
  /** 出差事由分类 code */
  reasonCode: string;
  /** 报销状态 code（none/pending/submitted/paid） */
  reimburseStatus: string;
  /** 实际报销金额 */
  reimburseAmount: number;
  /** 关联的周报任务 id（反查「这次出差期间做了哪些工作」） */
  reportTaskIds: number[];
  mileageKm: number;
  costAmount: number;
  status: string;
  note: string;
  stops?: BizTripStop[];
}

/** 出差途经点的**提交形态**：后端 create/update 时整体替换途经点，
 * 因此不接受 id 与 note 这类由服务端管理的字段。 */
export interface BizTripStopInput {
  seq?: number;
  name: string;
  lng: number | null;
  lat: number | null;
  arriveDate?: string;
}

/** 出差记录的**提交形态**（与响应 DTO 区分：不含服务端字段）。 */
export type BizTripInput = Omit<Partial<BizTrip>, "stops"> & {
  stops?: BizTripStopInput[];
};

export interface BizExpense {
  id: number;
  customerId: number | null;
  tripId: number | null;
  kind: string;
  category: string;
  amount: number;
  occurredOn: string;
  note: string;
}

export interface BizTimeEntry {
  id: number;
  customerId: number | null;
  tripId: number | null;
  title: string;
  hours: number;
  taskDate: string;
  note: string;
}

export interface WorkloadBucket {
  key: string;
  label: string;
  hours: number;
  weeklyHours: number;
  manualHours: number;
  count: number;
}

export interface WorkloadByCustomer {
  customerId: number;
  customerName: string;
  hours: number;
  weeklyHours: number;
  manualHours: number;
  count: number;
}

export interface WorkloadOverview {
  granularity: string;
  totalHours: number;
  weeklyHours: number;
  manualHours: number;
  entryCount: number;
  buckets: WorkloadBucket[];
  byCustomer: WorkloadByCustomer[];
}

export interface BizOverview {
  customers: number;
  trips: number;
  expenseRecords: number;
  totalIncome: number;
  totalExpense: number;
  balance: number;
  workload: WorkloadOverview;
  topCustomers: { id: number; name: string; status: string; industry: string }[];
  tripsByMonth: { key: string; label: string; count: number }[];
  customerNames: Record<string, string>;
}

export interface BizCapabilities {
  customerStatus: { value: string; label: string }[];
  /** 客户来源下拉（code + 中文标签） */
  customerSources: { value: string; label: string }[];
  /** 需要额外填写「来源说明」的来源 code */
  customerSourceNeedsNote: string[];
  tripStatus: { value: string; label: string }[];
  /** 出差事由分类下拉 */
  tripReasons: { value: string; label: string }[];
  /** 报销状态下拉 */
  reimburseStatus: { value: string; label: string }[];
  transportModes: { value: string; label: string }[];
  expenseKinds: { value: string; label: string }[];
  expenseCategories: string[];
  shareScopes: { value: string; label: string }[];
  shareMaxDays: number;
  shareDefaultDays: number;
  maxPageSize: number;
}

export interface BizShare {
  id: number;
  title: string;
  scopeKind: string;
  scopeCount: number;
  expiresAt: string;
  revoked: boolean;
  expired: boolean;
  active: boolean;
  viewCount: number;
  createdAt: string;
}

export interface ShareCreated {
  id: number;
  token: string;
  scopeKind: string;
  scopeCount: number;
  expiresAt: string;
  title: string;
}

export const bizApi = {
  capabilities: () => api<BizCapabilities>("/biz-dashboard/capabilities"),
  overview: () => api<BizOverview>("/biz-dashboard/overview"),

  // ---- 客户 ----
  listCustomers: (keyword = "", source = "") => {
    const q = new URLSearchParams();
    if (keyword) q.set("keyword", keyword);
    if (source) q.set("source", source);
    const qs = q.toString();
    return api<{ items: BizCustomer[] }>(`/biz-dashboard/customers${qs ? `?${qs}` : ""}`);
  },
  createCustomer: (body: Partial<BizCustomer>) =>
    api<BizCustomer>("/biz-dashboard/customers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateCustomer: (id: number, body: Partial<BizCustomer>) =>
    api<BizCustomer>(`/biz-dashboard/customers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteCustomer: (id: number) =>
    api<{ ok: boolean }>(`/biz-dashboard/customers/${id}`, { method: "DELETE" }),

  // ---- 出差 ----
  listTrips: (params: { status?: string; customerId?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.customerId) q.set("customer_id", String(params.customerId));
    const s = q.toString();
    return api<{ items: BizTrip[] }>(`/biz-dashboard/trips${s ? `?${s}` : ""}`);
  },
  createTrip: (body: BizTripInput) =>
    api<BizTrip>("/biz-dashboard/trips", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateTrip: (id: number, body: BizTripInput) =>
    api<BizTrip>(`/biz-dashboard/trips/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteTrip: (id: number) =>
    api<{ ok: boolean }>(`/biz-dashboard/trips/${id}`, { method: "DELETE" }),

  // ---- 财务 ----
  listExpenses: (
    params: { kind?: string; customerId?: number; dateFrom?: string; dateTo?: string } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.kind) q.set("kind", params.kind);
    if (params.customerId) q.set("customer_id", String(params.customerId));
    if (params.dateFrom) q.set("date_from", params.dateFrom);
    if (params.dateTo) q.set("date_to", params.dateTo);
    const s = q.toString();
    return api<{ items: BizExpense[] }>(`/biz-dashboard/expenses${s ? `?${s}` : ""}`);
  },
  createExpense: (body: Partial<BizExpense>) =>
    api<BizExpense>("/biz-dashboard/expenses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateExpense: (id: number, body: Partial<BizExpense>) =>
    api<BizExpense>(`/biz-dashboard/expenses/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteExpense: (id: number) =>
    api<{ ok: boolean }>(`/biz-dashboard/expenses/${id}`, { method: "DELETE" }),

  // ---- 工时台账 ----
  listTimeEntries: (customerId?: number) =>
    api<{ items: BizTimeEntry[] }>(
      `/biz-dashboard/time-entries${customerId ? `?customer_id=${customerId}` : ""}`,
    ),
  createTimeEntry: (body: Partial<BizTimeEntry>) =>
    api<BizTimeEntry>("/biz-dashboard/time-entries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateTimeEntry: (id: number, body: Partial<BizTimeEntry>) =>
    api<BizTimeEntry>(`/biz-dashboard/time-entries/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteTimeEntry: (id: number) =>
    api<{ ok: boolean }>(`/biz-dashboard/time-entries/${id}`, { method: "DELETE" }),

  // ---- 工作量 ----
  workload: (granularity = "month") =>
    api<WorkloadOverview>(`/biz-dashboard/workload?granularity=${granularity}`),

  // ---- 地图 ----
  mapKeyStatus: () => api<{ configured: boolean }>("/biz-dashboard/map/key-status"),
  saveMapKey: (key: string) =>
    api<{ ok: boolean; configured: boolean }>("/biz-dashboard/map/key", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }),
  geocode: (address: string, city = "") =>
    api<{ result?: { location?: { lng: number; lat: number } } }>(
      `/biz-dashboard/map/geocode?address=${encodeURIComponent(address)}${
        city ? `&city=${encodeURIComponent(city)}` : ""
      }`,
    ),

  // ---- 分享 ----
  listShares: () => api<{ items: BizShare[] }>("/biz-dashboard/shares"),
  createShare: (body: { scopeKind: string; scopeIds: number[]; title?: string; days?: number }) =>
    api<ShareCreated>("/biz-dashboard/shares", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  revokeShare: (id: number) =>
    api<{ ok: boolean }>(`/biz-dashboard/shares/${id}`, { method: "DELETE" }),
  readShare: (token: string) => api<any>(`/biz-dashboard/shares/public/${token}`),
};

/** 腾讯地图 SDK 的 Key 代理地址（前端只知地址，不知 Key）。
 *
 * 官方「Key 代理」模式：SDK 从官方 CDN 加载且不带 key 参数，
 * 所有业务请求打到 serviceHost，由后端注入托管的 Key。
 */
export const mapServiceHost = `${API_BASE}/biz-dashboard/map/proxy`;
