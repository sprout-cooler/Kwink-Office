/** 数据大屏 API 客户端。
 *
 * 复用全局 api() 封装（统一错误格式 + 网关前缀 + 登录失效提示）。
 * 身份参数一律不由前端传递，服务端以网关 Header 为准。
 */
import { api, API_BASE, downloadFile } from "./client";

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
  /** v1.0.32 账单导入字段：手录流水这几项全为空 */
  platform: string;
  orderNo: string;
  /** 交易方：与当前账户相对的一方（我付钱→收款方，我收钱→付款方）。
   *  与 customerId（关联客户档案）是两个概念，可各自独立有值。 */
  counterparty: string;
  txnType: string;
  /** 支付方式：钱走的渠道（零钱 / 余额宝 / 银行卡），与 platform（账单来源）不同 */
  paymentMethod: string;
  importBatchId: number | null;
}

// ---------------------------------------------------------------- 收支趋势

export interface ExpenseTrendBucket {
  /** month 时是 YYYY-MM，day 时是 YYYY-MM-DD */
  key: string;
  label: string;
  income: number;
  expense: number;
  net: number;
}

export interface ExpenseTrend {
  granularity: "month" | "day";
  buckets: ExpenseTrendBucket[];
}

// ---------------------------------------------------------------- 账单导入

/** 账单解析出的每一行（预览用）。status: ok 可导入 / duplicate 重复 / skipped 不纳入 / failed 格式错 */
export interface BillRow {
  line: number;
  status: "ok" | "duplicate" | "skipped" | "failed";
  reason: string;
  txnTime: string;
  txnType: string;
  counterparty: string;
  amount: number | null;
  direction: string;
  orderNo: string;
  note: string;
  dedupeKey: string;
  /** 账单原始的「付款方」「收款方」两列（银行流水常见）。
   *  交易方由这两列按收支方向推导，回传原始值供预览核对。 */
  payer?: string;
  payee?: string;
}

export interface BillPreview {
  encoding: string;
  platform: string;
  headerLine: number;
  header: string[];
  /** 标准字段 -> 命中的表头列名 */
  mapping: Record<string, string>;
  summary: { total: number; ok: number; duplicate: number; skipped: number; failed: number };
  amountTotal: number;
  rows: BillRow[];
  batchId?: number | null;
  imported?: number;
}

export interface BillImportBatch {
  id: number;
  fileName: string;
  platform: string;
  encoding: string;
  totalRows: number;
  importedRows: number;
  duplicateRows: number;
  failedRows: number;
  amountTotal: number;
  createdAt: string;
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
  /** 需要显式勾选记录的类别（工作量是聚合口径，不在此列） */
  shareIdScopes: string[];
  shareMaxDays: number;
  shareDefaultDays: number;
  sharePassMinLen: number;
  sharePassMaxLen: number;
  billPlatforms: { value: string; label: string }[];
  billEncodings: string[];
  billMaxRows: number;
  billMaxBytes: number;
  maxPageSize: number;
}

export interface BizShare {
  id: number;
  title: string;
  scopeKind: string;
  /** v1.0.32：各类别分别包含多少条，如 { expense: 3, customer: 2, workload: 0 } */
  scopes: Record<string, number>;
  scopeCount: number;
  /** 是否设置了访问口令 */
  hasPass: boolean;
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
  scopes: Record<string, number[]>;
  scopeCount: number;
  hasPass: boolean;
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
    params: {
      kind?: string;
      customerId?: number;
      dateFrom?: string;
      dateTo?: string;
      /** 交易方关键字（模糊匹配，同时会匹配关联客户名以兼容历史数据） */
      counterparty?: string;
      /** 支付方式（精确匹配，如「零钱」「招商银行(1234)」） */
      paymentMethod?: string;
    } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.kind) q.set("kind", params.kind);
    if (params.customerId) q.set("customer_id", String(params.customerId));
    if (params.dateFrom) q.set("date_from", params.dateFrom);
    if (params.dateTo) q.set("date_to", params.dateTo);
    if (params.counterparty) q.set("counterparty", params.counterparty);
    if (params.paymentMethod) q.set("payment_method", params.paymentMethod);
    const s = q.toString();
    return api<{ items: BizExpense[] }>(`/biz-dashboard/expenses${s ? `?${s}` : ""}`);
  },
  /** 已用过的支付方式全集（筛选下拉用，不受当前筛选影响） */
  listPaymentMethods: () => api<{ items: string[] }>("/biz-dashboard/expenses/payment-methods"),
  /** 收支趋势：按日/月聚合后的收入、支出与净额 */
  expenseTrend: (params: { granularity?: "month" | "day"; dateFrom?: string; dateTo?: string } = {}) => {
    const q = new URLSearchParams();
    q.set("granularity", params.granularity ?? "month");
    if (params.dateFrom) q.set("date_from", params.dateFrom);
    if (params.dateTo) q.set("date_to", params.dateTo);
    return api<ExpenseTrend>(`/biz-dashboard/expenses/trend?${q.toString()}`);
  },
  /** 导出 XLSX。筛选参数与列表同源，保证「看到什么就导出什么」 */
  exportExpenses: (
    params: {
      kind?: string;
      customerId?: number;
      dateFrom?: string;
      dateTo?: string;
      counterparty?: string;
      paymentMethod?: string;
    } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.kind) q.set("kind", params.kind);
    if (params.customerId) q.set("customer_id", String(params.customerId));
    if (params.dateFrom) q.set("date_from", params.dateFrom);
    if (params.dateTo) q.set("date_to", params.dateTo);
    if (params.counterparty) q.set("counterparty", params.counterparty);
    if (params.paymentMethod) q.set("payment_method", params.paymentMethod);
    const s = q.toString();
    return downloadFile(`/biz-dashboard/expenses/export${s ? `?${s}` : ""}`, "财务流水.xlsx");
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

  // ---- 账单导入（v1.0.32）----
  // 预览与正式导入都**重新上传原始文件**：后端重新解析，
  // 不接受前端回传的解析结果（否则前端可篡改某行状态把坏数据塞进来）。
  previewBillImport: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api<BillPreview>("/biz-dashboard/expenses/import/preview", {
      method: "POST",
      body: fd,
    });
  },
  commitBillImport: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api<BillPreview>("/biz-dashboard/expenses/import/commit", {
      method: "POST",
      body: fd,
    });
  },
  listBillImports: () => api<{ items: BillImportBatch[] }>("/biz-dashboard/expenses/imports"),
  deleteBillImport: (id: number) =>
    api<{ id: number; removed: number }>(`/biz-dashboard/expenses/imports/${id}`, {
      method: "DELETE",
    }),

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
  /** v1.0.32：多类分享。scopes 里每类独立开关；workload 用空数组表示「包含工作量统计」 */
  createShare: (body: {
    scopes: Record<string, number[]>;
    title?: string;
    days?: number;
    passcode?: string;
  }) =>
    api<ShareCreated>("/biz-dashboard/shares", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  revokeShare: (id: number) =>
    api<{ ok: boolean }>(`/biz-dashboard/shares/${id}`, { method: "DELETE" }),
  readShare: (token: string, passcode = "") =>
    api<any>(
      `/biz-dashboard/shares/public/${token}${passcode ? `?passcode=${encodeURIComponent(passcode)}` : ""}`,
    ),
};

/** 腾讯地图 SDK 的 Key 代理地址（前端只知地址，不知 Key）。
 *
 * 官方「Key 代理」模式：SDK 从官方 CDN 加载且不带 key 参数，
 * 所有业务请求打到 serviceHost，由后端注入托管的 Key。
 */
export const mapServiceHost = `${API_BASE}/biz-dashboard/map/proxy`;
