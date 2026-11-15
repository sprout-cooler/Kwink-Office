# 本地大模型 · PC 端部署指引

> 适用对象：KwinkOffice（全能办公室）v1.0.41+，软件运行在同局域网 NAS（`192.168.31.204`），
> 模型推理跑在 Windows PC（`192.168.31.182`）。
>
> 本指引只讲**怎么在 PC 上把模型服务跑起来**；软件侧怎么填地址见
> [`本地大模型-软件接入指引.md`](本地大模型-软件接入指引.md)。

> ## ✅ 本机当前状态（2026-11-15 已由我完成的部分）
>
> | 项 | 状态 |
> |---|---|
> | Ollama **0.40.16** 安装到 `E:\Ollama` | ✅ 已完成（Inno Setup `/DIR`，静默安装） |
> | 模型目录 `OLLAMA_MODELS=E:\Ollama\models` | ✅ 已设，**以后拉模型不会占 C 盘** |
> | `OLLAMA_HOST=0.0.0.0:11434` / `OLLAMA_ORIGINS=*` / `OLLAMA_KEEP_ALIVE=-1` | ✅ 已设为用户级环境变量 |
> | 服务监听 `0.0.0.0:11434`、局域网 IP 可访问 | ✅ 已验证 |
> | CUDA 识别 RTX 4060 Laptop（8 GiB，可用 6.9 GiB） | ✅ 已验证 |
> | **模型** | ⏸ **按你要求未下载**（硬盘空间紧）；`ollama list` 为空 |
> | 防火墙限定来源仅 NAS | ⚠️ **未建成**（需管理员权限），但 NAS → PC 实测 HTTP 200 已通 |
>
> 所以你接下来只需做两件事：**① 挑时间拉一个视觉模型**（§3 第 3 步）、
> **② 可选：用管理员 PowerShell 补一条防火墙规则**（§4.2）。
>
> ⚠️ 服务是我用 `ollama serve` 在后台命令行启动的，**关掉那个终端/会话就停了**。
> 要长期常驻，请用下面的「开机自启」方案（§5 末尾）。

---

## 0. 先看清可行性结论（重要，别跳过）

**结论：可行，而且软件侧代码零改动。** 依据是本项目的协议级冒烟（真实代码 + 假 OpenAI 兼容端点）：

| 验证项 | 结果 |
|---|---|
| `POST {base_url}/chat/completions` | ✅ 路径对得上 |
| `Authorization: Bearer <任意 Key>` | ✅ 本地服务忽略 Key，但**必须非空** |
| `content: [{type:text}, {type:image_url}]` + base64 图片 | ✅ 周报截图就是这么发的 |
| `response_format: {type: json_object}` | ✅ 已在请求里；端点不支持时代码会自动降级重试 |
| 设置页「测试连接」 | ✅ 通过 |

⚠️ **但有一个硬性前提：必须是「视觉模型（VLM）」，不是普通文本模型。**

周报模块的 AI 用途是**截图 → 结构化 JSON**（识别工单标题、起止时间、状态、客户名、企微一周小结指标），
请求里带的是图片。所以 `deepseek-r1`、`qwen3:8b`、Llama 这类**纯文本模型完全不能用**，
填上去会返回空结果或报 400。必须选支持图像输入的多模态模型。

⚠️ **另一个要如实说明的取舍**：你现在的云端模型是 `qwen3.8-flash`（大参数视觉旗舰）。
本机 GPU 是 RTX 4060 Laptop **8 GB 显存**，只能跑 7B 级量化 VLM。
**中文截图密集表格、手写体、模糊图、跨天时间的识别准确率会明显低于云端** ——
尤其你刚修复过「跨天工单」场景，小模型对「11月2日 10:30 → 11月3日 12:19」这类
时间区间的语义判断更容易出错。建议先小批量试用，校对页逐条确认，别直接全量切换。

⚠️ **可靠性架构变化**：NAS 是 7×24，PC 不是。**PC 关机 / 休眠 / Ollama 退出 = 周报识别全挂**。
建议把本地模型作为「可切换的第二配置」，云端保留为兜底（软件支持按模块独立配置，见接入指引）。

---

## 1. 硬件核对（已实测本机）

| 项 | 实测值 | 结论 |
|---|---|---|
| GPU | NVIDIA GeForce RTX 4060 Laptop，**8188 MiB (8 GB)** | 可跑 7B 级 VLM 量化版 |
| 驱动 | 610.60 | 支持 CUDA，够用 |
| 内存 | 63.7 GB | 远够 |
| CPU | i7-13650HX | 够用 |
| 局域网 IP | `192.168.31.182`（WLANX） | 与 NAS `192.168.31.204` 同网段 ✅ |
| Ollama | 未安装 | 需安装 |
| Docker Desktop | 未就绪（本次不依赖它） | 用 Ollama 原生安装即可 |

> 若 IP 变了（DHCP 重新分配），软件里填的地址会失效。建议在路由器给 PC 绑定静态 IP / DHCP 保留。

---

## 2. 选哪个模型

必须同时满足：**支持图像输入** + **能稳定输出 JSON**。按 8 GB 显存排序：

| 模型（Ollama tag） | 下载体积 | 显存占用 | 中文截图 | 建议 |
|---|---|---|---|---|
| `qwen2.5vl:7b` | ~6.0 GB | ~6–7 GB | 较好 | **首选**，中文 OCR 与结构输出相对最稳 |
| `qwen3-vl:8b`（若可用） | ~6.5 GB | ~7 GB | 较好 | 次选，注意 8B 在 8G 显存上可能需降量化 |
| `gemma3:4b` | ~3.3 GB | ~4 GB | 一般 | 显存吃紧时用，中文工单识别偏弱 |
| `llava:7b` / `llava-llama3` | ~4.7 GB | ~5 GB | 偏弱 | 仅作协议验证，不建议生产 |
| `minicpm-v` | ~5 GB | ~5 GB | 中等 | 备选 |

❌ **不要选**：`deepseek-r1:*`、`qwen3:*`（纯文本）、`llama3.2:*`（纯文本）、`nomic-embed-text`（向量模型）。

> 模型名必须和 `ollama list` 显示的**完全一致**（含 `:7b` 这样的 tag）。软件里填错会返回 404。

---

## 3. 安装 Ollama（Windows）

1. 到 <https://ollama.com/download> 下载 Windows 安装包，默认安装。
2. 安装完成后托盘会有 Ollama 图标。验证：
   ```powershell
   ollama --version
   ```
3. 拉取视觉模型（首次约 6 GB，视网速可能十几分钟）：
   ```powershell
   ollama pull qwen2.5vl:7b
   ```
4. 确认模型在列表里：
   ```powershell
   ollama list
   ```
5. 本机自测（先别管局域网）：
   ```powershell
   curl http://127.0.0.1:11434/v1/chat/completions `
     -H "Content-Type: application/json" `
     -d '{\"model\":\"qwen2.5vl:7b\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":20}'
   ```
   返回含 `choices[0].message.content` 的 JSON 即成功。

---

## 4. 让 NAS 能访问（三个必做，缺一不可）

Ollama **默认只监听 127.0.0.1**，NAS 容器访问不到。必须做三件事：

### 4.1 绑定所有网卡

PowerShell（用户级环境变量，永久生效）：
```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_ORIGINS", "*", "User")
```
然后**彻底退出托盘 Ollama 再重新打开**（只关窗口不算，环境变量不会重读）。

验证监听地址：
```powershell
netstat -an | findstr 11434
# 应看到  0.0.0.0:11434 ... LISTENING
# 若仍是 127.0.0.1:11434 → 环境变量没生效，重开 Ollama
```

### 4.2 防火墙放行（建议只放行给 NAS）

管理员 PowerShell：
```powershell
New-NetFirewallRule -DisplayName "Ollama LAN (NAS only)" `
  -Direction Inbound -Protocol TCP -LocalPort 11434 -Action Allow `
  -Profile Private `
  -RemoteAddress 192.168.31.204
```
> 用 `-RemoteAddress` 限定只允许 NAS 访问，比全放行安全。
> 若你的网络是「公用网络」配置档，把 `-Profile Private` 改成 `-Profile Any`。

⚠️ **安全提醒**：Ollama 本身**没有鉴权**。一旦 `0.0.0.0` 暴露，局域网内任何设备都能调用你的 GPU、
读取提示词内容。务必用防火墙限定来源 IP；不要在公网/访客网络这么开。

### 4.3 确认跨机可达

在 **PC 上**先用局域网 IP 自测：
```powershell
curl http://192.168.31.182:11434/api/tags
```
应返回模型列表 JSON。

再从 **NAS 侧**测（这一步属于真机验证，按约定由你执行）：
```bash
# SSH 到 NAS 后执行
curl -s --max-time 10 http://192.168.31.182:11434/api/tags
```
> ⚠️ 更严格的验证是**从容器内部**测，因为请求实际由 `omnioffice-api` 容器发出：
> ```bash
> docker exec -it omnioffice-api python -c "
> import urllib.request
> print(urllib.request.urlopen('http://192.168.31.182:11434/api/tags', timeout=10).read()[:200])
> "
> ```
> 项目 compose 用的是默认 bridge 网络（未设 `network_mode: host`），容器出站到同网段 IP 通常可达；
> 若不通，优先查 PC 防火墙与 OLLAMA_HOST，而不是改 compose。

---

## 5. 让模型常驻，避免首次超时

软件里识别请求超时是 **60 秒**（`vlm.py` 的 `TIMEOUT_S`）。本地模型**首次加载**可能超过 60 秒，
导致第一批截图识别失败。两个办法：

**办法 A（推荐）：预热 + 常驻**
```powershell
# 让模型常驻内存，不因空闲被卸载
ollama run qwen2.5vl:7b "用一句话介绍你自己"
```
然后设置环境变量让 Ollama 永不卸载模型：
```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "-1", "User")
```
重启 Ollama 生效。

**办法 B：开机自动预热**
把下面内容存成 `预热模型.ps1`，放进
`shell:startup` 目录（Win+R 输入 `shell:startup`）：
```powershell
Start-Process "ollama" -ArgumentList "run","qwen2.5vl:7b","hello" -WindowStyle Hidden
```

> 若仍然超时，需要软件侧把 60 秒调大 —— 这需要改代码发版，见接入指引第 6 节。

---

## 6. 让服务常驻（本机当前是临时后台进程）

⚠️ 本次安装时我用 `ollama serve` 在后台起了服务，**会话结束就会停**。要长期可用，二选一：

**方案 A：让 Ollama 托盘程序随开机自启（最简单）**
```
Win+R 输入  shell:startup  回车
把 E:\Ollama\ollama app.exe 的快捷方式放进去
```
托盘程序会读取已设好的用户级环境变量（`OLLAMA_HOST` / `OLLAMA_MODELS` 等），
启动即监听 `0.0.0.0:11434`，无需手动 `serve`。

**方案 B：注册成 Windows 服务（无 GUI、更稳）**
用 `nssm` 或任务计划程序把 `E:\Ollama\ollama.exe serve` 注册为开机任务，
并给它配好同样的四个环境变量。

> 另外建议：电源设置里把工作时段改为「不休眠」，否则 PC 睡眠后 NAS 侧识别会失败。

---

## 7. 验收清单（部署完成后逐条打勾）

- [x] `ollama --version` 有输出（0.40.16）
- [ ] `ollama list` 能看到 `qwen2.5vl:7b` ← **只剩这一步，等你挑时间拉**
- [x] `netstat -an | findstr 11434` 显示 `0.0.0.0:11434 LISTENING`
- [ ] 防火墙规则限定来源为 NAS IP（可选加固，需管理员权限）
- [x] PC 上 `curl http://192.168.31.182:11434/api/tags` 返回模型列表（当前 `{"models":[]}`）
- [x] NAS 上 `curl http://192.168.31.182:11434/api/tags` 返回 **HTTP 200**（已实测）
- [ ] （更严格）`omnioffice-api` 容器内也能访问上面地址 ← 真机验证，交给你
- [ ] 拉完模型后预热常驻，首次识别不超 60 秒（v1.0.42 起超时可在设置页调）
- [ ] 已配置开机自启 + 工作时段不休眠

---

## 7. 故障速查

| 现象 | 检查 | 处理 |
|---|---|---|
| 软件「测试连接」超时 | `OLLAMA_HOST` 是否 `0.0.0.0`；防火墙 | 重开 Ollama；重建入站规则 |
| 测试连接 404 | 服务地址是否多写了 `/chat/completions` | 地址应以 `/v1` 结尾 |
| 连接成功但识别结果为空 | 模型是不是纯文本模型 | 换 `qwen2.5vl:7b` |
| 识别返回 400 | 端点不支持 `response_format` | 代码会自动降级重试一次；仍失败则换模型 |
| 首批截图失败、后续正常 | 模型冷加载 > 60s | 预热 + `OLLAMA_KEEP_ALIVE=-1` |
| 显存溢出 / 极慢 | 并发 3 张同时推理 | 软件侧把「识别并发数」改为 **1**（见接入指引） |
| 用了一周突然连不上 | PC DHCP 换了 IP | 路由器绑定静态 IP，更新软件里的地址 |
| PC 关机后周报识别全挂 | 架构如此 | 切回云端配置（模块级覆盖可一键恢复继承） |

---

## 附：备选方案（LM Studio / vLLM）

只要暴露 **OpenAI 兼容的 `/v1/chat/completions`** 且支持 base64 图片，都能接：

- **LM Studio**（Windows 图形界面，较易上手）：装好后在「Developer / Local Server」启动服务，
  端口默认 `1234`，地址填 `http://192.168.31.182:1234/v1`；同样需要设置「Serve on Local Network」
  并放行防火墙。Load 的模型必须是 Vision 类型（如 `Qwen2.5 VL 7B`）。
- **vLLM / Xinference**：适合有多卡或 Linux 机器的场景，启动带
  `--served-model-name <名字>` 与 `--api-key <任意值>`；本项目 8 GB 显存跑不动更大的模型，暂不推荐。

本指引以 Ollama 为主，其余方案只要满足协议契约即可，软件侧配置完全一样。
