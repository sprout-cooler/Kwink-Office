/** 图片处理 API：与后端 image_tool 模块一一对应。
 *
 * 设计约定：
 * - 格式下拉 / 质量滑块 / 拼接方式全部由 GET /capabilities 驱动，
 *   后端新增格式时前端零改动（单一事实来源在 constants.py）；
 * - 错误统一走 client.ts 的 ApiError，detail.error 是稳定错误码，
 *   前端可据此分支（如 AI_NOT_CONFIGURED → 引导去设置页）。
 */
import { API_BASE, gatewayPrefix, api } from "./client";

export interface FormatOption {
  id: string;
  label: string;
  mime: string;
  alpha: boolean;
}

export interface Capabilities {
  inputFormats: FormatOption[];
  outputFormats: FormatOption[];
  quality: { min: number; max: number; default: number };
  stitchModes: { id: string; label: string }[];
  transformOps: { id: string; label: string }[];
  watermarkPositions: string[];
  limits: {
    maxPixels: number;
    maxEdge: number;
    maxOutputEdge: number;
    gridMax: number;
    targetSizeMin: number;
  };
}

export type AssetKind = "original" | "convert" | "stitch" | "compress" | "transform";

export interface ImageAssetDto {
  id: number;
  kind: AssetKind;
  filename: string;
  size: number;
  md5: string;
  width: number;
  height: number;
  contentType: string;
  sourceId: number;
  meta: Record<string, unknown>;
  createdAt: string | null;
  /** 记录在但文件已丢失 */
  fileMissing: boolean;
}

export interface OcrBlock {
  text: string;
  /** 归一化位置，千分比（左上 [0,0]，右下 [1000,1000]） */
  box: [number, number, number, number];
  confidence: number;
}

export interface OcrResult {
  text: string;
  blocks: OcrBlock[];
  meta: { model: string; blockCount: number; charCount: number };
  assetId: number;
}

export interface UploadResult {
  accepted: ImageAssetDto[];
  duplicates: string[];
  rejected: { filename: string; reason: string }[];
}

/** 图片文件回显 / 下载 URL（浏览器直接 <img src>，不走 fetch） */
export function assetFileUrl(id: number, download = false): string {
  const base = `${gatewayPrefix()}/api/image-tool/images/${id}/file`;
  return download ? `${base}?download=true` : base;
}

export const imageApi = {
  capabilities: () => api<Capabilities>("/image-tool/capabilities"),

  list: (kind?: AssetKind) =>
    api<{ items: ImageAssetDto[] }>(`/image-tool/images${kind ? `?kind=${kind}` : ""}`),

  upload(files: File[]): Promise<UploadResult> {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return api<UploadResult>("/image-tool/images", { method: "POST", body: fd });
  },

  convert: (id: number, body: { targetFormat: string; quality?: number; dropExif?: boolean }) =>
    api<ImageAssetDto>(`/image-tool/images/${id}/convert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  compress: (
    id: number,
    body: { quality?: number; targetBytes?: number; targetFormat?: string; keepFormat?: boolean },
  ) =>
    api<ImageAssetDto>(`/image-tool/images/${id}/compress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  transform: (id: number, body: Record<string, unknown>) =>
    api<ImageAssetDto>(`/image-tool/images/${id}/transform`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  stitch: (body: {
    assetIds: number[];
    mode: string;
    gap?: number;
    background?: string;
    columns?: number;
    uniform?: boolean;
    targetFormat?: string;
    quality?: number;
  }) =>
    api<ImageAssetDto>("/image-tool/stitch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  ocr: (id: number) => api<OcrResult>(`/image-tool/images/${id}/ocr`, { method: "POST" }),

  remove: (id: number) =>
    api<{ ok: boolean; id: number; fileDeleted: boolean }>(`/image-tool/images/${id}`, {
      method: "DELETE",
    }),
};

/** 体积可读化（B → KB/MB），与周报模块的展示口径一致。 */
export function humanSize(bytes: number): string {
  if (!bytes || bytes < 0) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export { API_BASE };
