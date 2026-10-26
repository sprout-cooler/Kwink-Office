# UI 重构交付说明（ColorOS 17 风格）

> 本次是**纯视觉重构**：功能、信息架构、业务逻辑、数据模型、API 契约全部不变。
> 所有改动只发生在「长什么样」和「怎么动」这两层。

---

## 一、改动范围

### 1.1 新增（设计体系地基）

| 文件 | 作用 |
|---|---|
| `src/styles/tokens.css` | **设计 token 唯一真源**。基础色板 → 浅色语义 token → `html.dark` 深色语义 token → Element Plus 变量覆写。改主题只改这一处。 |
| `src/styles/element-theme.css` | Element Plus 组件级覆写（按钮/输入/选择器/表格/卡片/对话框/抽屉/标签/空状态/加载/提示/消息/单选/复选/表单）。 |
| `src/styles/base.css` | 重置 + 全局排版 + 工具类 + 动效关键帧 + 骨架屏 + `prefers-reduced-motion` 归零。 |
| `src/composables/theme.ts` | 深浅色管理：跟随系统 → 浅 → 深 三态循环，localStorage 持久化。 |
| `src/composables/chart-theme.ts` | ECharts 配色与主题联动（option 是 JS 对象拿不到 CSS 变量，需独立模块 + 版本号订阅）。 |
| `src/components/ui/` | 9 个可复用组件 + 统一出口 `index.ts`。 |

**已删除**：`src/styles/theme.css`（原文件仅 6 个变量，深蓝硬边侧栏风格，已被上述体系取代）。

### 1.2 组件库（`src/components/ui/`）

| 组件 | 职责 | 关键 API |
|---|---|---|
| `OOCard` | 统一卡片容器 | `title` `subtitle` `hoverable` `loading` `flush` `tinted`；插槽 `header`/`actions`/`footer` |
| `OOEmptyState` | 统一空状态 | `title` `description` `variant`(`inbox`/`search`/`chart`/`folder`/`error`/`users`) `loading` `rows` |
| `OOStatTile` | KPI 指标块 | `label` `value` `icon` `tone`(7 色) `hint` `trend` `delta` |
| `OOPageHeader` | 页面级标题区 | `title` `description` `badge`；默认插槽放右侧操作 |
| `OOToolbar` | 内容区工具条 | `hint` `dense`；插槽 `left`/`right` |
| `OOSectionTitle` | 区块小标题 | `title` `description` |
| `OOSkeleton` | 骨架屏 | `variant`(`card`/`table`/`list`) |
| `OOThemeToggle` | 三态主题切换 | — |
| `OOIcon` | 内联 SVG 图标映射 | `name` `size`；24×24 网格 / 1.8px 描边 / 圆头圆角 |

### 1.3 页面（17 个全部改造完成）

| 模块 | 页面 |
|---|---|
| 壳层 | `AppShell.vue`（侧栏+顶栏+Tab+面板）、`LoginView.vue`、`SettingsDrawer.vue`、`AiConfigForm.vue` |
| 数据大屏 | `OverviewTab` `WorkloadTab` `CustomerTab` `TripTab` `FinanceTab` `ShareTab` `BizDashboardPanel` `ChartBox` `TripMap` |
| 周报 | `WeeklyReportPanel` `UploadTab` `ReviewTab` `SummaryTab` `ManualTab` `ExportTab` `ExportHistoryPanel` `TemplateVersionDialog` `TaskTimeField` |
| 图片工具 | `ImageToolPanel` `ImagePicker` `ConvertTab` `StitchTab` `CompressTab` `OcrTab` `EditTab` `GalleryTab` |

**信息架构零改动**：左侧通高竖栏 → 顶栏 A 层 → Tab C 层 → 面板 D 层，模块注册表、Tab 顺序、字段名、校验规则全部保留。

---

## 二、关键设计决策

### 2.1 深浅双模不是简单反色

深色模式**不是把浅色值反过来**：

| 维度 | 浅色 | 深色 | 理由 |
|---|---|---|---|
| 背景 | 底 `#f5f7fb` / 卡 `#ffffff` | 底 `#0e1117` / 卡 `#171a22` | 卡片比底**提亮一档**形成层次，不是纯黑 |
| 品牌色 | `#4c6fff` | `#4c6fff`（图形）/ `#8aa0ff`（文字） | 图形色保持一致，文字色提亮到 400 档才在深底可读 |
| 阴影 | `rgba(21,26,38,.04~.12)` | `rgba(0,0,0,.30~.58)` + 品牌辉光 | 深色下纯黑阴影不可见，改用更深的黑 + 微弱品牌色辉光 |
| 三级文字 | `#667084` | `#828c9e` | 深色下 surface-2 比 surface 更亮，三级字压上去更费劲（见 2.4） |

**主题防闪白**：`initTheme()` 在 `createApp().mount()` **之前**同步应用主题类。
晚一步会先渲染一帧浅色再切深色，用户能看到明显闪白。

### 2.2 图表配色独立成模块

ECharts 的 option 是 JS 对象，**拿不到 CSS 变量**。若每个图表各写各的 hex，
改主题色要逐个找，且深色模式必然失配。

做法：`composables/chart-theme.ts` 提供色板与文字/网格/提示框色，
主题切换时 `notifyChartThemeChange()` 递增版本号 → 触发所有 `computed` 重算 → `setOption` 重绘。
`ChartBox.vue` 订阅该版本号。

### 2.3 一切视觉常量收敛到 token

组件里**不允许出现硬编码色值**（`#xxx` / `rgba(...)`），一律 `var(--oo-*)`。
改主题只改 `tokens.css` 一处。

例外（业务数据，不是样式）：
- `StitchTab.vue` 的 `const background = ref("#ffffff")` —— 拼接背景色，要传给后端。

### 2.4 对比度是**实测出来的**，不是算出来的

这是本次最花功夫的部分。**静态脚本只能验证「我选的 hex 组合」，
用户看到的是「浏览器算出来的最终渲染色」** —— 中间隔着 `opacity`、`color-mix()`、
`backdrop-filter`、渐变叠加。所以最终判据是真实 Chromium 的 `getComputedStyle`。

审计方式：遍历 17 个页面的**全部可见文本节点**，向上找到**第一个不透明祖先**
作为真实背景（渐变背景取「对白字最不利」的那一端色标），按 WCAG 2.1 相对亮度公式计算。

**首轮审计发现 120 项未达标**，逐条定位根因后修复，**终态 742 个节点零未达标**：

| 问题 | 实测值 | 根因 | 修复 |
|---|---|---|---|
| 单选/复选选中态 | 4.18:1 | EP 用 `--el-color-primary` 当填充底 | 覆写 EP 原生的 `--el-radio-button-checked-bg-color` → 新 token `--oo-brand-fill` |
| 主按钮/侧栏选中/页头徽章 | 4.18:1（浅）/ 3.58:1（深） | 渐变**起点**色太亮 | 渐变两端都换成能承载白字的值 |
| alert 描述文字 | 3.45:1 | EP 的 `.el-alert--info.is-light .el-alert__description`（specificity 0,3,0）压过了低优先级规则 | 提优先级 + 改次级文字色 |
| 选择器提示文字 | 3.61:1 | 误用 placeholder 色 | 改三级文字色 |
| 深色三级文字 | 4.12:1 | 深色下 surface-2 更亮 | 提到 `#828c9e` |
| 深色 KPI 图标 | 3.47:1 | `--oo-brand` 在深色下偏暗 | 改 `--oo-text-brand` |
| 禁用按钮 | 1.92:1 | EP 置灰后仍是白字压浅紫 | 改「次级文字 + 表面底」 |
| info 语义文字 | 4.37:1 | 色值偏浅 | 压深一档 |
| 复选框选中标签 | 4.18:1 | EP 把 label 染成 primary 色 | 改 `--oo-text-brand` |

**新增 token `--oo-brand-fill`**：一个 token 只管一种用法。
`--oo-brand`(#4c6fff) 作图形色没问题，但当「白字的底」只有 4.18:1。
凡是白字压品牌色的场景统一走 `--oo-brand-fill`（浅 `#3559e6` → 5.64:1，深 `#4260e8` → 5.16:1）。

### 2.5 响应式不是「等比缩小」

| 断点 | 行为 |
|---|---|
| > 1024px | KPI 4~6 列（auto-fit），图表双栏 |
| ≤ 900px | 财务页「饼图 + 流水明细」双栏 → 单栏 |
| ≤ 768px | 顶栏次要操作隐藏；窄屏表单改上下堆叠 |
| ≤ 640px | EP 表单标签从「左固定宽」改为「上堆叠」（`label-width` 是固定像素，会挤压内容区） |
| ≤ 560px | KPI 两列 + 卡片内边距/字号压缩；网格 `minmax(min(Xpx,100%),1fr)`；表单字段撑满 |

**两个真实踩坑**：

1. **`minmax(380px, 1fr)` 在窄容器下会溢出** —— 容器窄于 380px 时网格列宽仍被强制定为 380px。
   全项目统一改为 `minmax(min(380px, 100%), 1fr)`。
2. **内联 `style="width: 160px"` 会撑破容器** —— 改为语义类 `.oo-field-w-md` 等，
   窄屏（≤560px）统一撑满。

实测 390px / 768px 两个视口，**5 个代表性页面全部零横向溢出**。

### 2.6 图标用内联 SVG，不引图标库

NAS 可能离线，字体文件/图标库走 CDN 会加载失败。内联 SVG：
① 可继承 `currentColor` 自动适配深浅色；② 无额外请求；③ 0 体积依赖。
统一 24×24 网格、1.8px 描边、圆头圆角，与 Element Plus 同一视觉语言。

### 2.7 尊重系统的「减少动效」

`@media (prefers-reduced-motion: reduce)` 下全部动画时长归零。
KPI 数字用 `tabular-nums`，避免刷新时宽度抖动（CLS）。

---

## 三、组件复用结构

```
src/styles/
  ├── tokens.css          ← 唯一真源：色板 → 语义 token（浅/深）→ EP 变量覆写
  ├── element-theme.css   ← EP 组件级覆写（不改 EP 源码，只覆写 --el-* 变量 + 组件样式）
  └── base.css            ← 重置 / 工具类 / 动效关键帧 / 骨架屏 / reduced-motion

src/composables/
  ├── theme.ts            ← 三态主题（跟随系统/浅/深），mount 前同步应用
  └── chart-theme.ts      ← ECharts 配色，独立于 CSS 变量，版本号订阅重绘

src/components/ui/        ← 自研组件（只做 EP 覆盖不到的部分）
  ├── OOCard  OOEmptyState  OOStatTile  OOPageHeader
  ├── OOToolbar  OOSectionTitle  OOSkeleton  OOThemeToggle  OOIcon
  └── index.ts            ← 统一出口，页面统一 `import { OOCard, ... } from "@/components/ui"`

src/shell/AppShell.vue    ← 壳层：侧栏 / 顶栏 / Tab / 面板 四层结构
src/modules/*/            ← 业务页面，全部复用上面三层
```

**复用原则**：
- EP 能做的一律用 EP（表格、弹窗、表单、标签）→ 避免两套控件
- EP 做不到的才自研（KPI 块、页面标题、图形化空状态、图标映射）
- 页面里不再写卡片样式，容器视觉收敛到 `OOCard` 一处

---

## 四、运行方式

### 4.1 开发

```bash
# 后端（本地 mock 身份模式）
cd omnioffice/app/server
IDENTITY_MODE=mock APP_AUTH_REQUIRED=0 \
  uvicorn app.main:app --host 127.0.0.1 --port 8787

# 前端（vite dev，代理 /api → 8787）
cd omnioffice/app/web
npm install
npm run dev            # http://127.0.0.1:5173
```

### 4.2 构建

```bash
cd omnioffice/app/web
npm run typecheck      # vue-tsc --noEmit
npm run build          # 产物落到 ../server/public，随 server 一起打进镜像
```

### 4.3 打包与部署

见仓库根 `docs/` 与 `tools/` 下的 `package-fpk.ps1` / `release.ps1`。
设计 token 全部在 CSS 里，**不需要任何构建期配置或额外资源**。

### 4.4 主题切换

- 顶栏右侧「自动 / 浅 / 深」三态按钮（`OOThemeToggle`）
- 首次访问默认跟随系统
- 选择持久化在 `localStorage` 的 `oo-theme` 键

---

## 五、验证记录

| 项目 | 方法 | 结果 |
|---|---|---|
| 类型检查 | `vue-tsc --noEmit` | **零报错** |
| 构建 | `vite build` | 成功 |
| 对比度（浅色） | Chromium 1243 实测，17 页 | 379 节点，**0 未达标** |
| 对比度（深色） | Chromium 1243 实测，17 页 | 363 节点，**0 未达标** |
| 响应式 390px | 5 个代表页 + 逐元素溢出检测 | **零横向溢出** |
| 响应式 768px | 同上 | **零横向溢出** |
| 控制台错误 | 全页面遍历 | 仅腾讯地图海外请求失败（无外网环境所致，与 UI 无关） |

**已知非 UI 问题**：本机无外网，腾讯地图瓦片请求返回失败/400。
真机上正常；代码未改动，仅对 SDK 自带的比例尺/版权文字做了 `:deep()` 深色适配。

---

## 六、后续建议

1. **新增页面时先查 `components/ui/`** —— 能复用就别新写卡片样式。
2. **改主题色只动 `tokens.css`** —— 组件里不应出现硬编码色值。
3. **改动色值后重跑对比度审计** —— 静态算不算不算，
   必须真实浏览器取 `getComputedStyle`。参考本文 2.4 的修复清单与坑。
4. **图表新增时走 `chart-theme.ts`** —— 不要在 option 里写死 hex，
   否则深色模式必然失配。
