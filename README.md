# 全能办公室（OmniOffice）

> 统一的工作入口：把分散在各系统的工作内容收拢到一处。
> 飞牛 fnOS 第三方应用（`.fpk`），内置**周报模块**，支持后续扩展更多办公模块。

[![版本](https://img.shields.io/badge/version-1.0.25-blue)](releases/)
[![平台](https://img.shields.io/badge/platform-fnOS%20all-green)](https://www.fnos.cn)
[![维护者](https://img.shields.io/badge/maintainer-kwink-orange)](https://blog.kwink.cn)

---

## 一、这是什么

一个装在飞牛 NAS 上的 Docker 化第三方应用，用户从桌面图标点开即用，无需自建账号体系。

当前已实现两个核心模块：**周报**（把分散在各系统的工作截图/记录收拢进来 → AI 识别成结构化任务 → 人工校对 → 按公司模板填充导出 Excel 成品与区域截图）与**图片处理**（格式转换 / 拼接 / 压缩 / OCR / 编辑）。

**产物直接在 NAS 文件管理器里取用**，无需再传回电脑。

| 项 | 值 |
|---|---|
| 应用名 | 全能办公室（`omnioffice`）|
| 当前版本 | **1.0.25** |
| 包类型 | `.fpk`（fnOS 应用中心直装）|
| 平台 | fnOS 1.1.3100+，`platform=all` |
| 网关前缀 | `/app/omnioffice` |

---

## 二、核心能力（周报模块）

```
上传截图/记录 → AI 识别 → 分区归类 → 人工校对 → 绑定模板 → 导出双产物
```

- **AI 识别**：调用大模型把截图内容转成结构化任务条目，按线上/线下/培训/售前等分区归类
- **人工校对**：表格化校对，支持**可点击编辑 + 原位日历面板**选择「识别校对时间」
- **模板管理**：模板上传 → Excel 锚点结构校验 → 版本化管理（差异对比 / 一键回滚）
- **导出双产物**：① 保真 Excel 成品（按锚点填充、序列号按周期重算）② 区域截图（连续内容区 / 完整表体两套口径）
- **导出历史**：产物集中管理，支持搜索、重命名、删除
- **账号数据隔离**：多账号登录后数据按账号独立隔离

---

## 二之二、图片处理模块（`image_tool`）

```
上传图片 → 格式转换 / 拼接 / 压缩 / OCR / 编辑 → 我的图库统一管理
```

| 能力 | 说明 |
|---|---|
| **格式转换** | PNG / JPEG / WebP / GIF / BMP / TIFF 六种互转。透明度按目标格式正确处理（转 JPEG 时合成白底而非压黑）；EXIF 默认剥离，避免 GPS 坐标随图外发；手机照片横竖方向自动摆正；动图转换保留帧与时长 |
| **图片拼接** | 水平（左右）/ 垂直（上下）/ 网格三种方式，含间距、背景色、列数；尺寸不一致时可等比缩放到统一尺寸；拼接顺序可上下调整 |
| **图片压缩** | 两种模式：**质量因子**（1~100）与**目标体积**（内部二分搜索质量因子）。压不动时如实回报「该图已无压缩空间」并给出替代建议，不会给用户一个反而更大的文件 |
| **图片 OCR** | 复用本应用已配置的 AI 模型，返回**整图文本 + 每块文字的位置**（千分比坐标，可在图上叠加高亮框）。纯文字提取推荐 `qwen3.5-ocr` |
| **图片编辑** | 缩放 / 旋转 / 裁剪 / 文字水印（含位置、不透明度） |
| **我的图库** | 上传原件与各能力的加工产物统一管理，支持预览、下载、删除、按来源溯源 |

**技术要点**

- **零新增外部服务**：OCR 复用项目既有 VLM 通道（经 `settings_service.resolve_ai(db, "image_tool", owner=)` 取配置，自动获得模块级 AI 覆盖与账号隔离），不引入 tesseract/PaddleOCR
- **唯一新增依赖是 Pillow**：纯 wheel 自带 jpeg/zlib/webp/libtiff 编解码器，slim 镜像无需 `apt`
- **能力可独立调用**：`convert/stitch/compress/transform/ocr` 五个文件只依赖本包的 `constants/errors/imaging`，**不碰数据库与身份**，可直接在脚本里复用（`app/server/app/modules/image_tool/examples.py` 有七个可执行示例）
- **能力清单驱动前端**：`GET /api/image-tool/capabilities` 返回格式白名单与参数区间，前端下拉/滑块由此生成——后端新增一种格式，前端零改动
- **统一异常契约**：所有可预期错误抛 `ImageToolError`，由路由层统一翻译为 `{"detail": {"error", "message"}}`，且每条 `message` 都是**可行动的中文提示**而非英文原始异常

---

## 三、技术架构

```
fnOS 统一网关 /app/omnioffice  ← 转发 NAS 登录态（X-Trim-* Header）
        │  app.sock
        ▼
┌──────────────┐   ┌──────────┐   ┌──────────────┐
│  omnioffice  │   │postgres │   │    redis     │
│     api      │──▶│  :5432   │   │    :6379     │
└──────────────┘   └──────────┘   └──────────────┘
        │
┌──────────────┐
│  omnioffice  │  异步识别队列（AI 调用耗时，脱离请求线程）
│    worker    │
└──────────────┘
```

| 层| 技术选型 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + Pinia |
| 后端 | FastAPI + Uvicorn + SQLAlchemy 2.0 |
| 数据库 | PostgreSQL 3（真机）/ SQLite（本地开发回退）|
| 缓存/队列 | Redis |
| 文档处理 | openpyxl（Excel 填充）+ LibreOffice（区域截图渲染）|
| AI 接入 | 百炼 DashScope 等 OpenAI 兼容协议服务商（可自定义）|

**两级身份**：① fnOS 网关 Header（平台级）→ ② 应用账号 HttpOnly Cookie 会话（数据按账号隔离）。
所有业务表通过 `owner_uid` 归属，无需逐表改造。

**数据持久化**（易踩坑点）：数据库与用户文件（模板/原图/导出）**同挂 `${TRIM_PKGVAR}/data`**，
fnOS 升级保留该目录、只清空安装目录 —— 两者不同命必然产生「DB 记录在、文件没了」的脏数据。

---

## 四、目录结构

```
omnioffice/                应用包目录（fpk 打包源）
├── manifest               应用元信息（版本/平台/入口）
├── config/
│   ├── privilege          权限声明（run-as=package 最小权限）
│   └── resource           资源声明（docker-project / data-share）
├── wizard/                配置向导（AI Key 等敏感配置注入）
├── cmd/main               生命周期脚本（start / stop / status）
└── app/
    ├── ui/config          桌面入口（iframe + gatewaySocket）
    ├── docker/            Compose 编排 + Dockerfile
    ├── server/            FastAPI 后端
    │   └── app/
    │       ├── core/      配置 / 身份 / 账号 / 设置服务
    │       ├── db/        模型与会话
    │       └── modules/   业务模块（weekly_report / image_tool）
    └── web/               Vue 3 前端
        └── src/modules/   前端模块（weekly_report / image_tool）

releases/                  版本化安装包（只新增不覆盖）+ build-log.json
tools/                     打包与发布脚本
scripts/build-fpk.js       打包脚本（自动递增版本号）
build/                     打包门禁与编码归一脚本
```

---

## 五、本地开发

### 后端

```bash
cd omnioffice/app/server
# 未配置 DATABASE_URL 时自动回退 SQLite（数据落在 ./data/）
python run_tests.py       # 跑全量单测
uvicorn app.main:app --reload
```

### 前端

```bash
cd omnioffice/app/web
npm install
npm run dev
```

---

## 六、打包发布

```bash
# 自动递增版本号（默认 patch）→ 校验 → fnpack 打包 → 归档到 releases/
powershell -ExecutionPolicy Bypass -File tools\package-fpk.ps1 -Bump patch -Message "变更说明"

# 提交 + 打标签 + 推双远端
powershell -ExecutionPolicy Bypass -File tools\release.ps1
```

**打包流水线**（顺序不可调换）：
```
前端构建 → 编码归一 → 清理陈旧产物 → 单测 → slim瘦身 → 打包门禁 → fnpack
```

> ⚠️ 单测会重新生成 `__pycache__`，若 slim 在单测之前，门禁必报硬失败「`__pycache__` 会被打进 FPK」→ 无产物。

**版本号纪律**：
- 每次打包自动递增 `manifest.version`，**绝不复用版本号**（复用会撞已有 git tag 直接报错退出）
- 产物归档为 `releases/omnioffice_<版本>_<平台>_<日期>.fpk`，**只新增不覆盖**
- 版本化安装包与 `build-log.json` 一并提交进 Git，盘上不覆盖、git 里也留档

**Git 仓库**（双远端，每版都推）：

| 远端 | 地址 |
|---|---|
| `gitee` | `git@gitee.com:cool_fashion_palace_2514978304/Kwink-Office.git` |
| `gitcode` | `git@gitcode.com:qq_38832318/Kwink-Office.git` |

---

## 七、安装到飞牛 NAS

1. 从 `releases/` 取对应版本的 `.fpk`
2. 上传到 NAS 后在**应用中心 → 手动安装**上传该包
3. 首次启动按向导配置大模型 API（Key / 地址 / 模型）
4. 从桌面图标「全能办公室」进入

> 同一份产出也可给第三方 NAS 用普通 Docker 部署（`app/docker/docker-compose.yaml`），镜像入口按 `SOCKET_PATH` 有无自动切换 Unix Socket / TCP 双形态。

---

## 八、版本历史

| 版本 | 日期 | 关键变更 |
|---|---|---|
| 1.0.26 | 2026-10-19 | **新增图片处理模块** `image_tool`：格式转换 / 拼接 / 压缩 / OCR + 图片编辑、我的图库；Pillow 为唯一新增依赖 |
| 1.0.25 | 2026-10-18 | 修复删除模板 500（漏解绑 `ExportArtifact` 真外键）；SQLite 打开外键强制使测试环境与真机 PG 约束一致 |
| 1.0.24 | 2026-10-18 | 修复模板文件丢失与重复上传无法生效：数据目录改为 `TRIM_PKGVAR` 与库同命、删除同步清文件并自动解绑 |
| 1.0.22 | 2026-10-18 | 周报「识别校对时间」升级为可点击编辑 + 原位日历面板 |
| 1.0.21 | 2026-10-14 | 注册登录、模板版本管理、导出历史管理、配置导入导出；全量账号数据隔离 |
| 1.0.20 | 2026-10-14 | 修正百炼地域专属域名与模型清单（修复 404） |
| 1.0.18~19 | 2026-10-13~14 | 初始化 Git 与版本化打包体系 |

完整清单见 `releases/build-log.json`。

---

## 九、文档

| 文档 | 内容 |
|---|---|
| [`全能办公室_开发说明文档.md`](全能办公室_开发说明文档.md) | 项目介绍、技术方案、开发进度、Roadmap、需求记录 |
| [`全能办公室_开发约束_避坑指南落地.md`](全能办公室_开发约束_避坑指南落地.md) | 开发约束 A1–A21、踩坑记录 K1–K10（含真实事故）|
| [`全能办公室_统一开发文档.md`](全能办公室_统一开发文档.md) | 上述内容合集，供整体查阅 |
| [`飞牛开发者文档.md`](飞牛开发者文档.md) | fnOS 平台开发规范 |

---

## 十、⚠️ 已知易踩坑点

以下均为**真机踩过的坑**，改代码前务必先看：

| 坑 | 症状 | 铁律 |
|---|---|---|
| **数据挂错目录** | 升级后 DB 记录还在、文件全没了 → 接口 410 | 用户文件与数据库**必须同挂 `${TRIM_PKGVAR}`**，绝不挂安装目录 |
| **SQLite 不强制外键** | 本地单测全绿、真机 PG 才报 `ForeignKeyViolation` → 500 | 测试环境约束行为必须与真机一致，`session.py` 已开 `PRAGMA foreign_keys=ON` |
| **删主表漏解绑引用表** | 删模板必 500 | 参照 kwinkstock `tags.ts`：先清引用表再删主表，且解绑**要先 `commit()`** |
| **打包顺序** | 门禁硬失败、打不出包 | 单测 → slim → 门禁 → fnpack，不可调换 |
| **版本号复用** | 构建被拒 / 覆盖历史包 | 用 `build-fpk.ps1` 自动递增，产物只新增不覆盖 |
| **升级不重建容器** | 改了代码但没生效 | compose 必须版本化 image 标签 + `up -d --build` |

---

## 十一、许可与维护

- 维护者：[kwink](https://blog.kwink.cn)
- 问题反馈：请通过仓库 Issue 反馈