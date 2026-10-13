# 全能办公室（OmniOffice）飞牛 FPK 应用详细开发计划

> 上游文档：《全能办公室_开发可行性评估与开发计划_V1.0.md》（结论：技术可行，首选飞牛 FPK 路线）
> 需求依据：《全能办公室_需求与技术方案_V10.docx》
> 编制日期：2026-10-11
> 本文范围：FPK 首选路线的执行级开发计划，重点展开 **M0 真机 Spike** 的具体执行步骤与验收标准

---

## 1. 计划概述

### 1.1 总体阶段与排期

| 阶段 | 周期 | 人日 | 关键节点 |
|------|------|------|----------|
| M0 真机 Spike | W1（5 个工作日） | 5 | **MS0：GO / NO-GO 决策** |
| M1 外壳框架 | W1 ~ W2.5 | 10 | MS1 布局与模块机制演示 |
| M2 上传与识别 | W2.5 ~ W4 | 12 | MS2 端到端识别冒烟 |
| M3 校对与编辑 | W4 ~ W5 | 8 | MS3 校对闭环 |
| M4 模板填充与导出 | W4.5 ~ W6.5 | 13 | MS4 双产物导出达标 |
| M5 联调与验收 | W6.5 ~ W7 | 6 | MS5 指标全达标 |
| M6 FPK 封装与真机验收 | W7 ~ W8 | 10 | MS6 交付验收 |
| 缓冲 | W8 尾 | 4 | — |
| **合计** | **8 周** | **≈68 人日** | 1 前端 + 1 后端 |

### 1.2 角色分工

| 角色 | 主责 |
|------|------|
| 后端 ×1 | M0 Spike 主导、IdentityProvider、识别链路、填充引擎、渲染链、FPK 打包 |
| 前端 ×1 | 外壳四层布局、上传/校对/汇总/预览界面、WebSocket、跨分区拖动；M0 期间同步搭建外壳骨架 |
| 需求方 | 提供真机测试 NAS（≥4 核 8GB、x86_64、fnOS ≥ 1.1.3100）、真实截图样本 ≥100 张、VLM API Key、模板文件 |

### 1.3 环境矩阵

| 环境 | 用途 | 载体 |
|------|------|------|
| DEV | 日常开发与单测 | 开发机 Docker Compose（同一套编排，无网关，用 IdentityProvider Mock） |
| DEVICE-DEV | FPK 集成验证 | 测试 NAS + appcenter-cli（手动安装 fpk） |
| DEVICE-REL | 发布前回归 | 测试 NAS + 完整升级流程演练 |

> 原则：**一切集成问题以真机为准**，DEV 环境通过不代表真机通过；每个里程碑在 DEVICE-DEV 复验后才算关闭。

---

## 2. M0 真机 Spike 详细执行方案（W1，GO/NO-GO 决策点）

### 2.1 目标

用最小可行工程在飞牛真机上打通「打包 → 安装 → 网关访问 → 身份鉴权 → WebSocket → 共享目录 → 中文渲染 → 云端识别 → 升级保留 → 资源基线」全链路，把 FPK 路线的全部平台级不确定性在项目第 1 周内暴露并决策。

### 2.2 前置条件与准备清单（D1 上午完成）

| # | 准备项 | 责任方 | 完成标准 |
|---|--------|--------|----------|
| P1 | 测试 NAS 到位：x86_64、≥4 核 8GB、fnOS ≥ 1.1.3100、SSH 开启 | 需求方 | 可 SSH 登录，应用中心可打开 |
| P2 | NAS 上安装 appcenter-cli（飞牛开发者文档提供） | 后端 | `appcenter-cli --help` 可执行 |
| P3 | 开发机安装 fnpack CLI 与 Docker | 后端 | `fnpack --help` 可执行 |
| P4 | 真实模板文件（本周工作总结-46230-46236.xlsx）与 ≥2 张真实任务截图 | 需求方 | 文件可在开发机打开 |
| P5 | VLM API Key（任一 OpenAI 兼容服务）+ 服务 base_url | 需求方 | 开发机 curl 调用成功 |
| P6 | 按文档 8.2 结构创建最小工程骨架（manifest / config / ui / cmd / app/docker） | 后端 | 目录结构与 V10 文档 8.2 一致 |

> 注：fnpack / appcenter-cli 的具体安装方式与子命令参数以《飞牛开发者文档》为准；本文所有命令中 `omnioffice` 为应用名、`${TRIM_APPDEST}` 等变量含义见 V10 文档第八章。

### 2.3 Spike 工程内容（一次构建，逐步验证）

最小 Docker 编排仅含 1 个服务（postgres/redis 在 S8 才加入）：

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    container_name: omnioffice-api
    restart: unless-stopped
    environment:
      - SOCKET_PATH=/host/app.sock
      - DATA_DIR=/data
    volumes:
      - ${TRIM_APPDEST}:/host          # 创建 app.sock 供网关转发
      - ${TRIM_APPDEST}/share:/data    # 共享目录读写
```

Dockerfile.api（S5 阶段追加 LibreOffice 与字体）：

```dockerfile
FROM python:3.12-slim
# S5 追加：LibreOffice + 中文字体 + poppler（PDF转PNG）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-calc fonts-wqy-microhei poppler-utils \
    && rm -rf /var/lib/apt/lists/*
ENV HOME=/tmp
COPY app/server /srv
WORKDIR /srv
CMD ["python", "spike_server.py"]
```

最小 Socket 服务（验证 S2/S3，监听 Unix Socket 返回收到的 Header）：

```python
# spike_server.py —— aiohttp 同时承载 HTTP 与 WebSocket，绑定 /host/app.sock
import os, asyncio
from aiohttp import web, WSMsgType

async def index(request):
    headers = {k: v for k, v in request.headers.items()
               if k.lower().startswith(("x-trim", "x-forward"))}
    return web.json_response({"headers": headers}, status=200)

async def ws(request):
    peer = {k: request.headers.get(k) for k in
            ("X-Trim-Userid", "X-Trim-Username", "X-Trim-Isadmin")}
    wsresp = web.WebSocketResponse(heartbeat=30)
    await wsresp.prepare(request)
    await wsresp.send_json({"event": "connected", "identity": peer})
    async for msg in wsresp:
        if msg.type == WSMsgType.TEXT:
            await wsresp.send_json({"event": "echo", "data": msg.data})
    return wsresp

app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/ws", ws)
web.run_app(app, path=os.environ["SOCKET_PATH"])
```

manifest / privilege / resource / ui 按文档 8.3 ~ 8.6 原样配置（`os_min_version=1.1.3100`、`checkport=false`、run-as=package、data-share 两个目录、iframe 入口 + `gatewaySocket: app.sock`）。

### 2.4 执行排期（D1 ~ D5）

| 日 | 上午 | 下午 |
|----|------|------|
| D1 | 前置条件 P1~P6 核对；工程骨架与本地 build | S1 打包 → 真机安装 → 启停状态验证 |
| D2 | S2 网关身份 Header 验证（管理员/普通账号双角色） | S3 WebSocket 经网关连通与长连接保持 |
| D3 | S4 共享目录声明、读写、可见性、重装保留 | S5 镜像加 LibreOffice/字体，真实模板渲染 PNG |
| D4 | S6 容器出网调用 VLM 识别真实截图 | S7 升级数据保留演练 |
| D5 | S8 四服务全编排资源基线采集 | M0 验证报告签署 + GO/NO-GO 评审会（后端、前端、需求方） |

前端并行项（不占用 Spike 关键路径）：搭外壳工程骨架、四层布局静态原型、IdentityProvider Mock 实现。

### 2.5 S1~S8 逐步执行步骤与验收标准

#### S1 FPK 打包与真机安装（硬性项）

**步骤**
1. `fnpack build` 生成 `omnioffice.fpk`（本地 Docker 环境能构建镜像；NAS 与开发机网络可达或镜像可离线导入，方式以官方文档为准）。
2. NAS 执行 `appcenter-cli install-fpk omnioffice.fpk`。
3. 应用中心观察安装、启动过程与日志；执行停止、再次启动。
4. 桌面点击「全能办公室」入口，确认 iframe 打开。

**验收标准**

| # | 标准 |
|---|------|
| 1.1 | 安装一次成功（最多允许因配置笔误重试，需记录原因） |
| 1.2 | 应用中心状态显示「运行中」；`cmd/main status` 返回 0 |
| 1.3 | 停止后 `app.sock` 被清理、状态返回 3；再启动恢复正常 |
| 1.4 | 桌面 iframe 页面可打开（HTTP 200） |
| 1.5 | 安装/启动/停止全程应用中心日志无 ERROR 级报错 |

**失败处置**：若为配置问题（manifest 字段、Socket 路径、挂载），限期 1 人日内修复重验；若确认为 fnOS 平台级缺陷 → 记录证据（版本号、日志、截图），触发 NO-GO 评估。

#### S2 统一网关身份 Header 验证（硬性项）

**步骤**
1. 部署 spike_server.py（上节），桌面入口打开页面。
2. 页面 JSON 中核对 `X-Trim-Userid / X-Trim-Isadmin / X-Trim-Username`。
3. 分别用**管理员账号**与**普通账号**登录 NAS 后访问，比对两个账号返回值差异。
4. 退出登录后直接访问 `/app/omnioffice`，验证网关拦截行为。

**验收标准**

| # | 标准 |
|---|------|
| 2.1 | 三个 Header 均非空，且与当前登录 NAS 账号一致 |
| 2.2 | 管理员 `X-Trim-Isadmin` 与普通用户取值不同（可区分角色） |
| 2.3 | 未登录访问被网关重定向/拦截，请求不会到达应用容器 |
| 2.4 | 不同账号交替访问，Header 值随账号切换（无串号/缓存） |

#### S3 WebSocket 经网关连通（硬性项）

**步骤**
1. 用浏览器测试页（或 curl 握手）经 `/app/omnioffice/ws` 建立 WebSocket。
2. 发送 ping，验证 echo pong；验证握手请求可读到身份 Header。
3. 保持连接 ≥ 10 分钟，每 30s 发一次心跳，观察是否被网关中断。
4. 断开后重连 3 次，验证可重复建立。

**验收标准**

| # | 标准 |
|---|------|
| 3.1 | WebSocket 成功建立，双向消息收发正常 |
| 3.2 | 握手阶段服务端可读到身份 Header（连接鉴权可行） |
| 3.3 | 30s 心跳下长连接保持 ≥ 10 分钟不中断（记录网关空闲超时阈值） |
| 3.4 | 断线重连稳定（3/3 成功） |

**失败处置**：若网关对 WS 有空闲超时，将前端心跳间隔调低于阈值并记录（影响 M2 进度推送设计）。

#### S4 共享目录（硬性项）

**步骤**
1. `config/resource` 声明 `omnioffice/exports`、`omnioffice/data`（文档 8.5）。
2. 安装后经 spike 服务向 `/data/exports/weekly_report/`、`/data/data/` 写入测试文件。
3. NAS 文件管理器中定位两个共享目录，确认可见、可下载。
4. 卸载应用 → 重新安装，检查目录与文件是否保留。

**验收标准**

| # | 标准 |
|---|------|
| 4.1 | 安装后两个共享目录自动创建，文件管理器可见 |
| 4.2 | 容器内读写成功，宿主机文件管理器所见内容一致 |
| 4.3 | 重装后既有文件保留（目录属应用数据区而非容器可写层） |
| 4.4 | 目录结构支持按模块建子目录（`exports/weekly_report/`） |

#### S5 LibreOffice 中文渲染与区域截图（重要项）

**步骤**
1. 镜像内安装 `libreoffice-calc + fonts-wqy-microhei + poppler-utils`（见 Dockerfile），注意设置可写 HOME。
2. 编写测试脚本：openpyxl 载入真实模板副本 → D 列写入 2 条示例任务（含 D9/D10 拆分场景）→ C 列写日期序列号并保留日期格式 → `soffice --headless --convert-to pdf` → `pdftoppm -png -r 192`。
3. 打开产出 PNG，与在 Excel/WPS 中打开模板的显示效果逐项比对。
4. 记录单份转换耗时（连续 3 次取均值）。

**验收标准**

| # | 标准 |
|---|------|
| 5.1 | 中文全部正常渲染，无方框/乱码（重点：标题行、星期列、任务标题） |
| 5.2 | 合并单元格、边框、字体加粗等样式与 Excel 显示一致 |
| 5.3 | C 列显示为日期格式（如 2026-07-27 或模板原格式），不是纯数字 |
| 5.4 | 单份转换 ≤ 10s（真机基线，超则记入性能风险） |
| 5.5 | 转换过程不污染 xlsx（转换后再读文件，临时打印区域已清除） |

**失败处置**：字体问题 → 更换 `fonts-noto-cjk` 或手工安装字体文件重验；保真问题 → 调整 LibreOffice 转换参数，仍不达标则升级为风险项并评估 T8 口径二（完整表体）简化方案。

#### S6 云端 VLM 出网识别（重要项）

**步骤**
1. 在容器内先验证出网：DNS 解析 + HTTPS 连通到 VLM 服务 base_url（若 NAS 走代理，记录代理配置方式）。
2. 用 Python SDK / curl 以多模态消息发送 1 张真实任务截图，Prompt 固定输出 JSON：`{title, start_at, end_at, status, confidence}`。
3. 连续调用 5 张（含 1 张工单详情类），核对字段值与截图内容。
4. 记录单张耗时与 token 消耗（供 T13 计费归属决策）。

**验收标准**

| # | 标准 |
|---|------|
| 6.1 | 容器内可稳定访问 VLM 服务（5/5 次成功） |
| 6.2 | 返回合法 JSON 且可解析；标题/时间字段与截图内容一致（人工核对） |
| 6.3 | 单张端到端 ≤ 5s（含网络，P5 样本均值） |
| 6.4 | 记录单张成本基线（写入 M0 报告，支撑 T13 决策） |

**失败处置**：出网不通 → 与需求方确认 NAS 网络策略/代理；服务不稳定 → 更换 VLM 供应商重验（Key 已要求可配 base_url）。

#### S7 升级数据保留（硬性项）

**步骤**
1. Compose 加入 postgres（数据卷挂 `${TRIM_PKGVAR}/postgres`，文档 8.7），启动后建测试表并写入数据；共享目录放置文件。
2. 修改 manifest `version`（如 1.0.0 → 1.0.1）→ 重新 build → `appcenter-cli install-fpk` 执行升级安装。
3. 检查：应用自动重启、PG 测试数据仍在、共享目录文件仍在、app.sock 重建。
4. （记录性）执行一次**卸载**（非升级），确认平台对数据目录的处置行为并记入文档。

**验收标准**

| # | 标准 |
|---|------|
| 7.1 | 升级安装成功，四服务（含 PG 后）自动恢复运行 |
| 7.2 | 升级后 PG 数据 100% 保留 |
| 7.3 | 升级后共享目录文件 100% 保留 |
| 7.4 | 升级后桌面入口立即可用（无需手工清理 app.sock） |
| 7.5 | 卸载行为已记录并写入运维手册 |

#### S8 资源基线（重要项）

**步骤**
1. Compose 全量四服务（api / worker / postgres / redis）启动，`restart: unless-stopped`。
2. 静置 15 分钟，`docker stats` 与 fnOS 资源监视器采集各容器内存/CPU 均值与峰值。
3. 模拟一次识别负载（1 张图走 S6 链路），观察 worker 峰值。
4. 模拟一次导出负载（S5 渲染链路），观察 CPU 尖峰与时长。

**验收标准**

| # | 标准 |
|---|------|
| 8.1 | 稳态四容器总内存 ≤ 2GB |
| 8.2 | 15 分钟静置无 OOM、无容器重启循环 |
| 8.3 | 识别/导出负载期间 api 服务仍可响应（无整体假死） |
| 8.4 | 基线数据写入 M0 报告（作为 M5 压测对照基线） |

### 2.6 GO / NO-GO 决策规则

| 分类 | 项目 | 规则 |
|------|------|------|
| 硬性项（任一确认平台级失败即 NO-GO） | S1、S2、S3、S4、S7 | 配置类问题限期 ≤1 人日修复重验；修复后通过仍算 GO；确属平台缺陷（附日志与版本证据）则 NO-GO |
| 重要项（不单独构成 NO-GO） | S5、S6、S8 | 有替代方案（换字体/换供应商/调参数/硬件升级建议），失败时降级处理并记入风险登记册，在 M0 报告中明确补救计划与负责人 |

**NO-GO 时动作**：出具书面证据 → 需求方确认 → 切换备选路线（同一代码库 + 自建登录，改动约 3~5 人日，计划整体顺延 ≤1 周）。

**GO 时动作**：M0 报告归档；风险登记册初始化（含 S5/S6/S8 遗留项）；Spike 工程骨架直接演进为 M1 后端底座（不浪费）。

**M0 输出物**
1. 《M0 真机验证报告》（S1~S8 逐项签署：结果、证据截图/日志、耗时与资源数据）
2. GO / NO-GO 结论（需求方会签）
3. 风险登记册 V1
4. 可演进的 FPK 工程骨架（含验证通过的 Dockerfile、Compose、spike_server）

---

## 3. M1 ~ M6 分阶段详细计划

> 每阶段给出：目标 / 任务分解（BE、FE）/ 关键产物 / 完成定义（DoD）。DEV 环境开发，每阶段末在 DEVICE-DEV 复验。

### M1 外壳框架（W1 ~ W2.5，10 人日）

**目标**：四层布局外壳可运行，模块注册表驱动导航，鉴权抽象就绪。

| 端 | 任务 |
|----|------|
| BE | FastAPI 脚手架 + PostgreSQL 模型基座（Alembic）；`GET /api/modules` 模块注册表；**IdentityProvider 抽象**（GatewayHeaderProvider / MockProvider 双实现 + 单测）；设置 API；审计日志中间件（上传/识别/校对/导出四类事件埋点预留） |
| FE | Vite + React/TS + AntD（或 Vue3 + Element Plus）脚手架；AppShell 四层布局组件（左侧通高竖栏：头像/设置/B 导航；右侧：A 全局栏 + C Tab + D 面板）；模块路由与懒加载；B 层折叠；Tab 状态机（切 B 重置 C/D、切 C 二次确认丢弃编辑态）；状态管理 |

**关键产物**：外壳可演示工程、模块注册表协议（v1 契约）、IdentityProvider 接口。

**DoD / MS1 验收**
- 布局完全符合文档 2.3 六条关键规则（A 层不可变 / B 层为准 / C 默认第一个 Tab / 状态保持 / B 可折叠 / 竖栏通高）。
- 新增一个假模块（仅注册表登记）即可出现在 B 层并切换 C/D，**零包配置改动**。
- IdentityProvider 双实现可配置切换，单测覆盖。
- DEVICE-DEV 真机：以 FPK 形态安装后入口打开、Header 鉴权取到真实用户。

### M2 上传与识别（W2.5 ~ W4，12 人日）

**目标**：三分区上传 → 异步识别 → 结构化落库全链路跑通。

| 端 | 任务 |
|----|------|
| BE | 图片上传 API（批量、类型/大小校验、md5 去重、原图落 `data/`）；Celery 识别任务（并发信号量 4~6、失败重试 3 次、超时熔断）；**VLM 客户端**（OpenAI 兼容协议、base_url/Key 可配、响应 JSON Schema 校验）；**日期归一化模块**（用例表驱动：2026/10/09、10-09、10月9日、周四、Oct 9、261012、跨天继承、缺年份补全，全场景单测）；去重合并（任务编号 / 标题相似+时间窗）；WebSocket 进度推送（复用 M0 S3 结论的心跳参数）；越界周期标记 |
| FE | 任务上传 Tab：三分区并列、拖拽上传、缩略图列表、进度条、失败重试、删除；**已上传记录跨分区拖动**；识别进度实时展示（WS）；识别结果按分区分组预览 |

**关键产物**：识别 Prompt v2（经样本调优）、日期归一化测试用例表、上传组件。

**DoD / MS2 验收**
- 真实截图端到端冒烟：上传 → 识别 → 结果落库可查，进度实时可见。
- 日期归一化单测 100% 通过（覆盖文档 3.5 全部写法）。
- 单张识别 ≤ 5s（DEV 与真机各测）；20 张并发分批无请求丢失。
- 误传分区可拖动改归属，统计数据不受影响（归属与识别解耦）。

### M3 校对与编辑（W4 ~ W5，8 人日）

**目标**：识别结果全量可校、可编辑、可补充。

| 端 | 任务 |
|----|------|
| FE | 识别校对 Tab：分区分组表格、置信度三级样式（≥0.8 正常 / 0.6~0.8 标黄 / <0.6 标红必填）、点击字段弹出原图局部放大对照、行内编辑标题/时间、下拉改归属星期、跨分区移动、删除/手工新增；工作汇总 Tab（四项统计 + 未分类清单归类）；手工补充 Tab（重点问题 19-20 行 / 工作需求 21-22 行文本框）；所有编辑实时刷新右侧预览 |
| BE | `PATCH /api/reports/{id}/tasks/{task_id}`；issues / demands 保存接口；汇总实时计算（分区优先 + 关键词兜底、优先级 培训>售后>售前、手工覆盖锁定）；未分类清单接口；改动审计日志 |

**关键产物**：校对界面、汇总计算模块（含边界情况单测：多关键词命中、未命中、跨分区移动重算）。

**DoD / MS3 验收**
- 文档 3.8 全部校对能力可用，编辑操作 < 500ms 响应并实时反映预览。
- 汇总边界情况单测全过；手工覆盖后自动统计不再刷新该单元格。
- 低置信度必须人工处理后才允许进入导出（流程卡点生效）。

### M4 模板填充与导出（W4.5 ~ W6.5，13 人日，关键路径）

**目标**：双产物导出达标——Excel 保真 + 区域截图保真。

| 端 | 任务 |
|----|------|
| BE | 模板版本管理（入库 + 绑定周报）；锚点配置化（TITLE_A1 / DAY_BLOCKS×7 / SUMMARY / ISSUE / DEMAND / PLAN）；**填充引擎**：0/1/2/3+ 条任务四场景（留空 / 合并写入 / 取消 D 列合并拆两格 / 插行并扩展 B/C/E/F 合并区间 + 后续锚点整体下移 + 复制上行样式）；C 列序列号写入（1899-12-30 基准函数 + 格式保持）；填充前锚点校验（缺失阻断）；**导出编排**：xlsx 落共享目录 + LibreOffice 渲染链（最小外接矩形 → 临时打印区域 → PDF → PNG 192DPI → 清理打印区域，单机并发上限 2）；超宽分页 _p1/_p2；产物记录与下载接口；导出失败保留草稿 |
| FE | 预览与导出 Tab：表格 / PDF / 截图三预览、T8 两口径切换选项、导出按钮、产物列表与下载（Excel+PNG 成对展示） |

**关键产物**：填充引擎 + 单测套件（四场景、序列号、锚点校验、行号重算）、渲染链脚本、T8 双口径实现。

**DoD / MS4 验收**
- 真实模板回测：星期四双任务拆分（D9/D10）、单日 3 条插行、跨月周期、空周期四类场景输出与人工预期一致。
- Excel 用 Excel/WPS 打开：合并单元格、边框、日期格式与原模板一致；C 列为日期序列号非文本。
- 区域截图：中文无方框、≥192DPI、白底、两口径均可用、与 Excel 内容一致。
- 单份导出端到端 ≤ 10s（真机）。

### M5 联调与验收（W6.5 ~ W7，6 人日）

**目标**：真实数据回归 + 指标达标。

**任务**
1. 样本集建设：需求方提供并协助标注 ≥100 张真实截图（覆盖两类截图、各分区、边界日期写法）。
2. 准确率回测脚本：字段级（标题/开始/结束/状态）统计；Prompt 迭代至 ≥95%。
3. 真机压测：20 张 ≤60s、单张 ≤5s、50 并发在线（locust/k6 脚本）、导出并发 2 路排队。
4. 安全测试：越权访问他人周报/产物（改 ID 重放）、路径穿越（`../`）、敏感字段不落库抽查。
5. 缺陷修复与回归。

**DoD / MS5 验收**：评估报告 5.4 节验收标准表全项通过（识别 ≥95%、性能、产物、安全、审计）。

### M6 FPK 封装与真机验收（W7 ~ W8，10 人日）

**目标**：可交付的 FPK 与发布材料。

**任务**
1. `wizard/config`：`llm_api_key` 向导字段（T13），密钥落 `${TRIM_PKGETC}` 权限受限文件，验证不进日志/数据库。
2. `cmd/main` 完善：start/stop/status 全通过，失败信息写 `TRIM_TEMP_LOGFILE`（人为制造失败验证可见性）。
3. 图标资源（ICON.PNG / ICON_256.PNG / ui/images）与 manifest 终检（`os_min_version=1.1.3100`、`ctl_stop=true`、`checkport=false`、desktop_applaunchname 一致）。
4. 升级演练：v1.0.0 → v1.0.1 全流程（S7 结论复验）；卸载重装数据说明核实。
5. 真机回归清单执行（M0 报告全部项 + M1~M5 DoD 在 DEVICE-REL 复验）。
6. 发布材料：.fpk、图标、真实界面截图、应用介绍、运维手册定稿。

**DoD / MS6 验收**：需求方在自有 NAS 上独立完成「安装 → 配置 Key → 上传 → 识别 → 校对 → 导出 → 文件管理器取用」全流程无协助通过；升级数据保留复核通过。

---

## 4. 工程保障机制

| 机制 | 内容 |
|------|------|
| 契约先行 | M1 末冻结 API 契约 v1（OpenAPI），FE/BE 按契约并行，变更走评审 |
| 联调节奏 | 每周五固定半日联调 + 风险同步会；里程碑演示需需求方参加 |
| 真机管理 | 测试 NAS 由需求方提供并开放 SSH；Spike 后每阶段末真机复验，避免问题堆积到 M6 |
| 代码质量 | 关键模块互审（填充引擎、鉴权、日期归一化）；单测强制（归一化、汇总边界、拆行四场景、序列号） |
| 风险登记册 | M0 初始化，每周更新；R1~R10 见评估报告 3.7，S5/S6/S8 遗留项自动并入 |
| 敏感数据红线 | 电话/地址不提取不落库；原图加密存储；日志脱敏抽查纳入每阶段 DoD |

---

## 5. 交付物清单（与里程碑对应）

| 交付物 | 产出节点 |
|--------|----------|
| M0 真机验证报告 + GO/NO-GO 会签 + 风险登记册 V1 | MS0 |
| API 契约 v1（OpenAPI） | MS1 |
| 识别准确率回测报告（≥100 张样本） | MS5 |
| 性能压测报告（真机） | MS5 |
| omnioffice.fpk（含版本号）+ 源码仓库 + 模板锚点配置 | MS6 |
| 部署运维手册（含卸载数据说明、Key 配置、升级流程） | MS6 |
| 发布材料（图标、截图、应用介绍） | MS6 |
| 真机回归清单签署记录（M0 + M6 两轮） | MS6 |
