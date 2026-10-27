/** API 客户端：内置平台强约束（避坑指南 §1.1 规则 4 / 案例 3）。
 *
 * 1. 先读文本再 JSON.parse：2xx 但 body 是 HTML（如被网关重定向到登录页）→
 *    抛带指引的 BAD_RESPONSE，永远不允许把 null 当数据返回；
 * 2. API 基础路径取自当前页面路径中的网关前缀，杜绝「去斜杠拼接丢斜杠」类问题；
 * 3. 身份相关参数一律不由前端传递，服务端以网关 Header 为准。
 */
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number = 0,
  ) {
    super(message);
  }
}

/** 网关前缀：真机形如 /app/omnioffice；本地开发为空串 */
export function gatewayPrefix(): string {
  const m = window.location.pathname.match(/^(\/app\/[^/]+)/);
  return m ? m[1] : "";
}

export const API_BASE = `${gatewayPrefix()}/api`;

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const sep = path.startsWith("/") ? "" : "/";
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${sep}${path}`, {
      headers: { Accept: "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError("NETWORK", "网络不可达：请确认应用已启动后重试");
  }
  const text = await res.text();
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new ApiError(
      "BAD_RESPONSE",
      `服务返回了非 JSON 内容（HTTP ${res.status}），可能登录已失效——请刷新页面重新登录飞牛账号`,
      res.status,
    );
  }
  if (!res.ok) {
    // 错误体有两种形态，必须都兼容：
    //   ① FastAPI 的 HTTPException(detail={...}) → 响应体是 {"detail": {"error","message"}}
    //   ② 直接返回 {"error","message"} 的业务错误体
    // 只读顶层字段会让 ① 的可行动提示（如「腾讯地图配额已用尽，换 Key / 提额 / 等次日重置」）
    // 全部丢失，用户只能看到无信息量的「请求失败（HTTP 429）」。
    const raw = data as { error?: string; message?: string; detail?: unknown };
    const detail =
      raw?.detail && typeof raw.detail === "object"
        ? (raw.detail as { error?: string; message?: string })
        : undefined;
    throw new ApiError(
      detail?.error ?? raw?.error ?? "HTTP_ERROR",
      detail?.message ?? raw?.message ?? `请求失败（HTTP ${res.status}）`,
      res.status,
    );
  }
  return data as T;
}

/** 下载二进制文件（导出用）。
 *
 * 不能复用 api()：它会 `JSON.parse` 响应体，遇到 xlsx 二进制直接抛
 * BAD_RESPONSE。文件下载单独走 blob + a[download]，且不经过 JSON 解析。
 */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const sep = path.startsWith("/") ? "" : "/";
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${sep}${path}`, { headers: { Accept: "*/*" } });
  } catch {
    throw new ApiError("NETWORK", "网络不可达：请确认应用已启动后重试");
  }
  if (!res.ok) {
    // 错误体是 JSON，这里单独解析，把后端的可行动提示透给用户
    let msg = `导出失败（HTTP ${res.status}）`;
    try {
      const body = (await res.json()) as { detail?: { message?: string }; message?: string };
      msg = body?.detail?.message ?? body?.message ?? msg;
    } catch {
      /* 非 JSON 错误体就用默认文案 */
    }
    throw new ApiError("HTTP_ERROR", msg, res.status);
  }
  // 文件名优先取响应头的 Content-Disposition（后端已做 RFC 5987 编码）
  const disp = res.headers.get("Content-Disposition") ?? "";
  const m = disp.match(/filename\*=UTF-8''([^;]+)/i);
  const name = m ? decodeURIComponent(m[1]) : fallbackName;

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
