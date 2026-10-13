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
    const body = data as { error?: string; message?: string };
    throw new ApiError(body?.error ?? "HTTP_ERROR", body?.message ?? `请求失败（HTTP ${res.status}）`, res.status);
  }
  return data as T;
}
