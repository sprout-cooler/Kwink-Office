import { API_BASE, gatewayPrefix, ApiError, api } from "./client";

export type PartitionId = "offline_done" | "online_done" | "plan";

export interface PartitionStat {
  id: PartitionId;
  label: string;
  total: number;
  pending: number;
  processing: number;
  done: number;
  failed: number;
}

export interface ScreenshotItem {
  id: number;
  partition: PartitionId;
  partitionLabel: string;
  filename: string;
  size: number;
  md5: string;
  recognizeStatus: "pending" | "processing" | "done" | "failed";
  recognizeError: string;
  createdAt: string | null;
  taskCount: number;
  /** DB 记录在但原图文件已丢失（历史升级遗留），需清理重传 */
  fileMissing?: boolean;
}

export interface UploadResult {
  accepted: ScreenshotItem[];
  duplicates: string[];
  rejected: { filename: string; reason: string }[];
}

export type ConfidenceLevel = "normal" | "warning" | "danger";

export type StatCategory =
  | "training"
  | "offline_service"
  | "presale"
  | "online_service"
  | "plan"
  | "offline"
  | "unclassified";

export interface TaskItemDto {
  id: number;
  screenshotId: number;
  /** 来自哪张截图（手工新增为空） */
  filename: string;
  partition: PartitionId;
  partitionLabel: string;
  title: string;
  startAt: string;
  endAt: string;
  weekday: number;
  rawStatus: string;
  confidence: number;
  /** ≥0.8 正常 / 0.6~0.8 标黄 / <0.6 标红 */
  confidenceLevel: ConfidenceLevel;
  statCategory: StatCategory | string;
  /** 低置信度任务是否已人工确认（确认后方可导出） */
  reviewed: boolean;
  /** 是否为手工新增任务 */
  manual: boolean;
  outOfPeriod: boolean;
  warnings: string[];
  parseError: string;
  /** AI 从原图抄下来的原文，供人工对照 */
  rawStart: string;
  rawEnd: string;
}

/** 统计分类的中文标签（前端下拉与汇总页共用） */
export const STAT_CATEGORY_LABELS: Record<string, string> = {
  training: "培训",
  offline_service: "线下售后",
  presale: "售前",
  online_service: "线上售后",
  plan: "下周计划",
  unclassified: "未分类",
};

/** 可手工指派的分类（不含 online_service/plan —— 那两项由分区决定） */
export const ASSIGNABLE_CATEGORIES = [
  "training",
  "offline_service",
  "presale",
  "unclassified",
] as const;

export interface SummaryItem {
  category: string;
  label: string;
  count: number;
}

export interface SummaryData {
  items: SummaryItem[];
  counts: Record<string, number>;
  offlineTotal: number;
  planTotal: number;
  total: number;
  unclassifiedIds: number[];
  unclassifiedItems: TaskItemDto[];
  /** 企微一周小结：工作会话次数（线上售后数量的真实口径），未识别为 null */
  wechatSessions: number | null;
  wechatMinutes: number | null;
  wechatLatestTime: string;
  wechatPeriodText: string;
  /** ai = 识别值；manual = 人工修正值 */
  wechatSource: "" | "ai" | "manual";
}

export interface WechatSummary {
  sessions: number | null;
  minutes: number | null;
  latestTime: string;
  periodText: string;
  source: "" | "ai" | "manual";
}

export interface ManualData {
  issues: string;
  demands: string;
}

export interface ReadinessItem {
  code: string;
  label: string;
  count: number;
  hint: string;
}

export interface ExportReadiness {
  ready: boolean;
  /** 阻断项：非空即不可导出 */
  reasons: ReadinessItem[];
  /** 非阻断提示：告知去向（如无时间条目只计入汇总数量），不拦住导出 */
  notices?: ReadinessItem[];
  unclassified: number;
  taskCount: number;
}

/** 时间是否必填 —— 与后端 constants.time_required 保持一致。
 *  线上售后按周汇总会话量、下周计划尚未发生，两者截图上本就没有逐条时刻。
 *  白名单从严：只有显式列出的分区才免时间要求，将来新增分区默认仍需填时间。 */
export const TIME_REQUIRED_PARTITIONS = ["offline_done"] as const;
const KNOWN_PARTITIONS = ["offline_done", "online_done", "plan"] as const;

export function isTimeRequired(partition: string): boolean {
  if ((KNOWN_PARTITIONS as readonly string[]).includes(partition)) {
    return (TIME_REQUIRED_PARTITIONS as readonly string[]).includes(partition);
  }
  return true;
}

/* ---- 模板版本与导出（M4） ---- */

export interface TemplateItem {
  id: number;
  filename: string;
  version: number;
  size: number;
  anchorOk: boolean;
  note: string;
  createdAt: string | null;
  /** 最近一次变更时间（回滚等操作会写入） */
  updatedAt?: string | null;
  /** 是否为当前批次绑定的模板版本 */
  bound?: boolean;
}

/** 模板版本差异项 */
export interface TemplateDiffItem {
  sheet: string;
  cell: string;
  kind: "changed" | "added" | "removed" | "sheet_added" | "sheet_removed";
  left: string;
  right: string;
}

export interface TemplateDiff {
  base: TemplateItem;
  target: TemplateItem;
  changes: TemplateDiffItem[];
  total: number;
  truncated: boolean;
  limit: number;
}

/** 导出历史条目（比本批次产物列表多了模板版本与周期信息） */
export interface ExportHistoryItem extends ArtifactItem {
  templateId: number | null;
  templateVersion: number | null;
  templateFilename: string;
  reportId: number | null;
  periodStart: string;
  xlsxSize: number;
  pngCount: number;
  updatedAt: string | null;
}

export interface ArtifactItem {
  id: number;
  name: string;
  scope: string;
  dpi: number;
  taskCount: number;
  status: "ok" | "partial" | "failed";
  error: string;
  xlsx: string;
  xlsxExists: boolean;
  pngs: string[];
  createdAt: string | null;
}

export interface ExportOutcome {
  artifactId: number;
  name: string;
  xlsx: string;
  pngs: string[];
  scope: string;
  status: "ok" | "partial" | "failed";
  error: string;
}

/** 产物下载 URL（浏览器直接开，Cookie 会话自动带） */
export function artifactUrl(id: number, kind: "xlsx" | "png", index = 0): string {
  const base = `${gatewayPrefix()}/api/weekly-report/artifacts/${id}/file/${kind}`;
  return kind === "png" && index > 0 ? `${base}?index=${index}` : base;
}

export interface RecognizeStatus {
  configured: boolean;
  providers: { id: string; label: string; baseUrl: string; models: string[] }[];
  counts: { pending: number; processing: number; done: number; failed: number };
  total: number;
}

/** 原图 URL（<img src> 用，请求经网关自动带 Cookie 会话） */
export function screenshotRawUrl(id: number): string {
  return `${gatewayPrefix()}/api/weekly-report/screenshots/${id}/raw`;
}

/** 识别进度 WebSocket URL（跟随页面同源，经网关转发） */
export function recognizeEventsUrl(): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${gatewayPrefix()}/api/weekly-report/recognize/events`;
}

export const weeklyApi = {
  async state(): Promise<{ periodStart: string; partitions: PartitionStat[]; templateId: number | null }> {
    const res = await fetch(`${API_BASE}/weekly-report/state`, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new ApiError("HTTP_ERROR", `批次概览失败（HTTP ${res.status}）`, res.status);
    return res.json();
  },

  async list(partition?: PartitionId): Promise<ScreenshotItem[]> {
    const qs = partition ? `?partition=${partition}` : "";
    const res = await fetch(`${API_BASE}/weekly-report/screenshots${qs}`);
    if (!res.ok) throw new ApiError("HTTP_ERROR", `列表加载失败（HTTP ${res.status}）`, res.status);
    const data = await res.json();
    return data.items;
  },

  async tasks(partition?: PartitionId): Promise<TaskItemDto[]> {
    const qs = partition ? `?partition=${partition}` : "";
    const res = await fetch(`${API_BASE}/weekly-report/tasks${qs}`);
    if (!res.ok) throw new ApiError("HTTP_ERROR", `任务列表失败（HTTP ${res.status}）`, res.status);
    const data = await res.json();
    return data.items;
  },

  async recognizeStatus(): Promise<RecognizeStatus> {
    const res = await fetch(`${API_BASE}/weekly-report/recognize/status`);
    if (!res.ok) throw new ApiError("HTTP_ERROR", `识别状态失败（HTTP ${res.status}）`, res.status);
    return res.json();
  },

  async recognize(ids?: number[]): Promise<{ enqueued: number; pending: number }> {
    const res = await fetch(`${API_BASE}/weekly-report/recognize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ids && ids.length ? { ids } : {}),
    });
    if (!res.ok) throw new ApiError("HTTP_ERROR", `触发识别失败（HTTP ${res.status}）`, res.status);
    return res.json();
  },

  async recognizeRetryFailed(): Promise<{ enqueued: number }> {
    const res = await fetch(`${API_BASE}/weekly-report/recognize/retry-failed`, { method: "POST" });
    if (!res.ok) throw new ApiError("HTTP_ERROR", `重试失败（HTTP ${res.status}）`, res.status);
    return res.json();
  },

  /** 上传（XHR：fetch 无法获取上传进度） */
  upload(
    partition: PartitionId,
    files: File[],
    onProgress?: (percent: number) => void,
  ): Promise<UploadResult> {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("partition", partition);
      for (const f of files) form.append("files", f);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/weekly-report/screenshots`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        try {
          const body = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) resolve(body);
          else reject(new ApiError(body?.detail?.error ?? "HTTP_ERROR", body?.detail?.message ?? `上传失败（HTTP ${xhr.status}）`, xhr.status));
        } catch {
          reject(new ApiError("BAD_RESPONSE", "上传返回了非 JSON 内容，可能登录已失效——请刷新页面重新登录飞牛账号", xhr.status));
        }
      };
      xhr.onerror = () => reject(new ApiError("NETWORK", "网络不可达：请确认应用已启动后重试"));
      xhr.send(form);
    });
  },

  async move(id: number, partition: PartitionId): Promise<ScreenshotItem> {
    const res = await fetch(`${API_BASE}/weekly-report/screenshots/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ partition }),
    });
    if (!res.ok) throw new ApiError("HTTP_ERROR", `移动失败（HTTP ${res.status}）`, res.status);
    return res.json();
  },

  async remove(id: number): Promise<void> {
    const res = await fetch(`${API_BASE}/weekly-report/screenshots/${id}`, { method: "DELETE" });
    if (!res.ok) throw new ApiError("HTTP_ERROR", `删除失败（HTTP ${res.status}）`, res.status);
  },

  /** 一键清除原图已丢失的截图记录（历史升级遗留），返回清除条数 */
  async purgeMissing(): Promise<{ removed: number; ids: number[] }> {
    const res = await fetch(`${API_BASE}/weekly-report/screenshots/purge-missing`, { method: "POST" });
    if (!res.ok) throw new ApiError("HTTP_ERROR", `清理失效记录失败（HTTP ${res.status}）`, res.status);
    return res.json();
  },

  // ---------------------------------------------------- 校对与编辑（M3）

  /** 行内编辑。时间字段传**原始文本**（如「周四 10:00」），服务端统一归一化 */
  async patchTask(id: number, patch: Partial<TaskItemDto> & { startTime?: string; endTime?: string }): Promise<TaskItemDto> {
    const res = await api<{ item: TaskItemDto }>(`/weekly-report/tasks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    return res.item;
  },

  /** 手工新增任务 */
  async createTask(body: { title: string; partition: PartitionId; startTime?: string; endTime?: string }): Promise<TaskItemDto> {
    const res = await api<{ item: TaskItemDto }>("/weekly-report/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.item;
  },

  async removeTask(id: number): Promise<void> {
    await api(`/weekly-report/tasks/${id}`, { method: "DELETE" });
  },

  /** 跨截图纠错：任务挂到另一张截图下 */
  async moveTaskToShot(taskId: number, screenshotId: number): Promise<TaskItemDto> {
    const res = await api<{ item: TaskItemDto }>(`/weekly-report/tasks/${taskId}/move-to-shot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ screenshotId }),
    });
    return res.item;
  },

  // ---------------------------------------------------- 工作汇总 / 手工补充

  async summary(): Promise<SummaryData> {
    return api<SummaryData>("/weekly-report/summary");
  },

  async getManual(): Promise<ManualData> {
    const res = await api<{ items: ManualData }>("/weekly-report/manual");
    return res.items;
  },

  async saveManual(body: Partial<ManualData>): Promise<ManualData> {
    const res = await api<{ items: ManualData }>("/weekly-report/manual", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.items;
  },

  /** 企微一周小结指标（线上售后数量 = 企微会话量） */
  async getWechatSummary(): Promise<WechatSummary> {
    const res = await api<{ item: WechatSummary }>("/weekly-report/wechat-summary");
    return res.item;
  },

  /** 人工修正企微会话量 */
  async saveWechatSessions(sessions: number): Promise<WechatSummary> {
    const res = await api<{ item: WechatSummary }>("/weekly-report/wechat-summary", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessions }),
    });
    return res.item;
  },

  /** 导出前卡点检查（低置信度未确认 / 时间解析失败 / 越界未确认） */
  async exportReadiness(): Promise<ExportReadiness> {
    return api<ExportReadiness>("/weekly-report/export-readiness");
  },

  // ---------------------------------------------- 模板版本与导出（M4）

  async templates(): Promise<TemplateItem[]> {
    const r = await api<{ items: TemplateItem[] }>("/weekly-report/templates");
    return r.items;
  },

  /** 上传模板（结构校验在后端做，不符会 400） */
  async uploadTemplate(file: File, note = ""): Promise<{ template: TemplateItem; duplicated: boolean }> {
    const form = new FormData();
    form.append("file", file);
    form.append("note", note);
    const res = await fetch(`${API_BASE}/weekly-report/templates`, { method: "POST", body: form });
    if (!res.ok) {
      let msg = `模板上传失败（HTTP ${res.status}）`;
      try {
        const b = await res.json();
        msg = b?.detail?.message ?? msg;
      } catch {
        /* 保持默认文案 */
      }
      throw new ApiError("UPLOAD_FAILED", msg, res.status);
    }
    return res.json();
  },

  async bindTemplate(templateId: number): Promise<{ template: TemplateItem }> {
    return api("/weekly-report/templates/bind", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ templateId }),
    });
  },

  async removeTemplate(id: number): Promise<void> {
    await api(`/weekly-report/templates/${id}`, { method: "DELETE" });
  },

  /* ---- 模板版本：差异对比与回滚 ---- */

  /** 对比两个版本；base=参照版（通常是旧的），target=对比版（通常是新的） */
  async diffTemplates(baseId: number, targetId: number): Promise<TemplateDiff> {
    return api<TemplateDiff>(`/weekly-report/templates/${baseId}/diff/${targetId}`);
  },

  /** 回滚到指定版本：从旧版派生一个新版本并绑定到当前批次，历史版本全部保留 */
  async rollbackTemplate(
    id: number,
    note = "",
  ): Promise<{ template: TemplateItem; sourceVersion: number; bound: boolean }> {
    return api(`/weekly-report/templates/${id}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
  },

  /* ---- 导出历史（跨批次） ---- */

  async exportHistory(opts?: {
    q?: string;
    templateId?: number | null;
    limit?: number;
  }): Promise<ExportHistoryItem[]> {
    const p = new URLSearchParams();
    if (opts?.q) p.set("q", opts.q);
    if (opts?.templateId) p.set("templateId", String(opts.templateId));
    p.set("limit", String(opts?.limit ?? 200));
    const r = await api<{ items: ExportHistoryItem[] }>(`/weekly-report/export-history?${p}`);
    return r.items;
  },

  async renameArtifact(id: number, name: string): Promise<{ item: ExportHistoryItem; filesRenamed: boolean }> {
    return api(`/weekly-report/artifacts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  },

  async deleteArtifact(id: number): Promise<{ ok: boolean; filesRemoved: number; dirRemoved: boolean }> {
    return api(`/weekly-report/artifacts/${id}`, { method: "DELETE" });
  },

  async runExport(opts: { scope: "content" | "full"; dpi: number; renderPng: boolean }): Promise<ExportOutcome> {
    return api<ExportOutcome>("/weekly-report/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opts),
    });
  },

  async artifacts(): Promise<ArtifactItem[]> {
    const r = await api<{ items: ArtifactItem[] }>("/weekly-report/artifacts");
    return r.items;
  },
};
