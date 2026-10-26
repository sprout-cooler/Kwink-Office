# KwinkOffice 设计规范（Design Token 清单）

> 视觉参考：OPPO ColorOS 17 —— 纯净留白、柔和渐变、圆润卡片、细腻阴影、舒适动效。
> 本文件是**可复用的设计 token 清单**，与代码一一对应。
>
> 代码位置：
> - 变量定义：`src/styles/tokens.css`
> - Element Plus 组件级覆写：`src/styles/element-theme.css`
> - 基础层（重置/工具类/动效）：`src/styles/base.css`
> - 可复用组件：`src/components/ui/`

---

## 一、色彩系统

### 1.1 品牌色（蓝紫渐变，ColorOS 年轻感主色）

| Token | 值 | 用途 |
|---|---|---|
| `--oo-brand-50` | `#eef2ff` | 极浅填充 |
| `--oo-brand-100` | `#dfe6ff` | 浅填充 |
| `--oo-brand-200` | `#c3d0ff` | 浅描边 |
| `--oo-brand-300` | `#a8b8ff` | 深色模式辅助 |
| `--oo-brand-400` | `#8aa0ff` | 深色模式品牌文字 |
| `--oo-brand-500` | `#4c6fff` | 品牌主色 / 焦点环 |
| `--oo-brand-600` | `#3559e6` | 品牌文字 / 按钮底 |
| `--oo-brand-700` | `#2b47c4` | 品牌按下态 |
| `--oo-brand-800` | `#22389a` | 最深档 |

### 1.2 辅助色

| 色相 | 100 | 300 | 500 | 600 | 700 | 用途 |
|---|---|---|---|---|---|---|
| 青 teal | `#d3f5ef` | `#5fd6c6` | `#14b8a6` | `#0e9384` | `#0b7c72` | 成功 / 数据可视化 |
| 紫 purple | `#ece7fd` | `#b9a7f5` | `#7c5cf0` | `#6440d6` | `#4f31a8` | 品牌渐变端 / 出差 |
| 粉 pink | `#fde4ec` | `#f5a8c0` | `#e8638f` | `#c74a78` | `#b03a66` | 强调 / 提醒 |

### 1.3 语义色（浅色模式文字用 700 档，色块用 500 档）

| 语义 | 100（底色） | 500（图形） | 700（文字） | 文字色用途 |
|---|---|---|---|---|
| 成功 success | `#e6f4d8` | `#639922` | `#3b6d11` | 状态标签、正向指标 |
| 警告 warning | `#fdefd5` | `#d99114` | `#8a5a00` | 配额告警、待办 |
| 危险 danger | `#fde9e7` | `#e2483f` | `#a32d25` | 错误、删除 |
| 信息 info | `#d3f5ef` | `#14b8a6` | `#0b7c72` | 中性提示 |

### 1.4 中性灰

`--oo-gray-50` `#f7f8fa` / `-100` `#eef0f4` / `-200` `#e3e8f0` / `-300` `#d2d9e4` / `-400` `#a8b1c0` / `-500` `#7d879c` / `-600` `#5a6478` / `-700` `#3f4759` / `-800` `#262c3a` / `-900` `#151a26`

---

## 二、语义 Token（实际使用）

### 2.1 背景层

| Token | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--oo-bg-app` | `#f5f7fb` | `#0e1117` | 应用底色 |
| `--oo-bg-surface` | `#ffffff` | `#171a22` | 卡片 / 面板 |
| `--oo-bg-surface-2` | `#f8fafd` | `#1f232d` | 卡片内嵌套区 / 表头 |
| `--oo-bg-surface-3` | `#eef1f7` | `#262b36` | 三级凹陷区 / 进度槽 |
| `--oo-bg-hover` | `rgba(53,89,230,.06)` | `rgba(138,160,255,.10)` | 悬浮底 |
| `--oo-bg-active` | `rgba(53,89,230,.11)` | `rgba(138,160,255,.17)` | 按下底 |

### 2.2 文字层

| Token | 浅色 | 深色 | 对比度（实测） |
|---|---|---|---|
| `--oo-text-primary` | `#1a2033` | `#e8ebf2` | 16.17:1 / 14.58:1 |
| `--oo-text-secondary` | `#5a6478` | `#9ba3b4` | 5.95:1 / 6.87:1 |
| `--oo-text-tertiary` | `#667084` | `#828c9e` | 4.64:1 / 4.63:1 |
| `--oo-text-placeholder` | `#7d879c` | `#8b95a6` | 3.61:1（占位符非正文） |
| `--oo-text-brand` | `#3559e6` | `#8aa0ff` | 5.64:1 / 7.08:1 |
| `--oo-text-inverse` | `#ffffff` | `#151a26` | — |

> **三级文字取值踩坑（浅色）**：初版 `#8b94a7` 在 `#f5f7fb` 上仅 **2.84:1**，远不达标；
> 一路压深到 `#667084` 才在所有背景上站上 4.5:1。
> 「淡灰显得轻盈」与「可读性」冲突时，可读性优先。
>
> **三级文字取值踩坑（深色）**：初版 `#7a8394` 在最浅的 `--oo-bg-surface-2`(`#1f232d`)
> 上只有 **4.12:1** —— 因为深色模式里 surface-2 比 surface 更亮，三级字压上去反而更费劲。
> 提到 `#828c9e` 后为 4.63:1。
>
> **教训**：对比度不能只看「主要背景」，必须把**每一档背景都算一遍**取最差值。

### 2.3 描边层

| Token | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--oo-border-subtle` | `#eef1f6` | `#21252f` | 分隔线、卡片描边 |
| `--oo-border-default` | `#e3e8f0` | `#262b36` | 默认描边 |
| `--oo-border-strong` | `#d2d9e4` | `#333a49` | 输入框、强调 |
| `--oo-border-brand` | `#4c6fff` | `#4c6fff` | 聚焦态 |

### 2.4 品牌填充

| Token | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--oo-brand` | `#4c6fff` | `#4c6fff` | 品牌图形、描边、焦点环 |
| `--oo-brand-hover` | `#3559e6` | `#5f7dff` | 悬浮态 |
| `--oo-brand-active` | `#2b47c4` | `#7a90ff` | 按下态 |
| `--oo-brand-fill` | `#3559e6` | `#4260e8` | **承载白字的填充**（选中态、按钮底） |
| `--oo-brand-soft` | `#eef2ff` | `rgba(76,111,255,.16)` | 浅填充（选中态底） |
| `--oo-brand-soft-hover` | `#dfe6ff` | `rgba(76,111,255,.26)` | 浅填充悬浮 |
| `--oo-brand-on` | `#ffffff` | `#ffffff` | 品牌底上的文字 |

> **`--oo-brand-fill` 为什么单独存在**
> `--oo-brand`(#4c6fff) 作为**图形色**没问题，但一旦用它当**白字的底**，
> 实测只有 4.18:1，达不到正文 4.5:1。所以凡是「白字压品牌色」的场景
> （单选/复选选中态、品牌渐变按钮、侧栏选中项）统一走 `--oo-brand-fill`：
> 浅色 `#3559e6` → 白字 5.64:1；深色 `#4260e8` → 白字 5.16:1。
> **一个 token 只管一种用法**，比在每个使用点临时调色更不容易漏。

---

## 三、圆角体系

| Token | 值 | 用途 |
|---|---|---|
| `--oo-radius-xs` | 6px | 极小元素（小图标底、进度条） |
| `--oo-radius-sm` | 8px | 小控件（骨架行、标签底、内联按钮） |
| `--oo-radius-md` | 12px | **默认**（输入框、按钮、嵌套卡） |
| `--oo-radius-lg` | 16px | **卡片** |
| `--oo-radius-xl` | 20px | 对话框、抽屉 |
| `--oo-radius-2xl` | 28px | 登录卡、Hero 容器 |
| `--oo-radius-pill` | 999px | 标签、头像、胶囊按钮 |

Element Plus 对齐：`--oo-radius-ep-base` = 12px、`--oo-radius-ep-sm` = 8px（EP 默认 8/4，必须同步否则圆角不一致）。

---

## 四、间距体系（4 的倍数）

`--oo-space-1` 4 / `-2` 8 / `-3` 12 / `-4` 16 / `-5` 20 / `-6` 24 / `-7` 32 / `-8` 40 / `-9` 48 / `-10` 64

**常用规则**
- 卡片内边距：16px 20px（上下 16，左右 20）
- 卡片之间：16px（`--oo-space-4`）
- 页面区块之间：20px（`--oo-space-5`）
- 页面外边距：24px（`--oo-space-6`），窄屏降到 16px
- 表单 label 与控件：8px（`--oo-space-2`）

---

## 五、字体层级

**字体族**：`--oo-font-sans` = PingFang SC / HarmonyOS Sans SC / Microsoft YaHei / system-ui
**等宽**：`--oo-font-mono` = SF Mono / JetBrains Mono / Consolas

| Token | 值 | 用途 |
|---|---|---|
| `--oo-text-2xs` | 11px | 角标、图标旁说明 |
| `--oo-text-xs` | 12px | 辅助说明、表头、时间戳 |
| `--oo-text-sm` | 13px | 表格正文、按钮、次级标题 |
| `--oo-text-base` | 14px | **正文默认** |
| `--oo-text-md` | 15px | 空状态标题、表单控件 |
| `--oo-text-lg` | 16px | 顶栏标题、弹窗标题 |
| `--oo-text-xl` | 18px | 页面标题（窄屏） |
| `--oo-text-2xl` | 22px | 页面标题（默认） |
| `--oo-text-3xl` | 28px | KPI 数值 |
| `--oo-text-4xl` | 34px | Hero 数值 |

**字重**：regular 400 / medium 500 / semibold 600 / bold 700（**只用 400 与 500/600 两档**，避免视觉噪音）
**行高**：tight 1.25（标题）/ normal 1.5（正文）/ relaxed 1.7（长文本）
**数字**：`.oo-num` 启用 `tabular-nums`，防止 KPI 刷新时宽度抖动

---

## 六、阴影与渐变

### 6.1 阴影（细腻，不用纯黑）

| Token | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--oo-shadow-xs` | `0 1px 2px rgba(21,26,38,.04)` | `0 1px 2px rgba(0,0,0,.30)` | 骨架、徽标 |
| `--oo-shadow-sm` | `0 2px 6px rgba(21,26,38,.06)` | `0 2px 6px rgba(0,0,0,.36)` | **卡片默认** |
| `--oo-shadow-md` | `0 4px 14px rgba(21,26,38,.07)` | `0 4px 14px rgba(0,0,0,.42)` | 卡片悬浮 |
| `--oo-shadow-lg` | `0 8px 28px rgba(21,26,38,.09)` | `0 8px 28px rgba(0,0,0,.50)` | 弹层、悬浮卡片 |
| `--oo-shadow-xl` | `0 16px 48px rgba(21,26,38,.12)` | `0 16px 48px rgba(0,0,0,.58)` | 对话框 |
| `--oo-shadow-brand` | `0 6px 18px rgba(76,111,255,.24)` | `0 6px 18px rgba(76,111,255,.34)` | 主按钮、品牌图标 |

### 6.2 渐变

| Token | 值 | 用途 |
|---|---|---|
| `--oo-gradient-brand` | 浅色 `linear-gradient(135deg,#3559e6,#6b48e8)` / 深色 `linear-gradient(135deg,#4260e8,#7a5ce0)` | 主按钮、头像、选中态 |
| `--oo-gradient-brand-soft` | 品牌色 12%~16% 透明渐变 | 强调区块底色 |
| `--oo-gradient-brand-soft-hover` | 品牌色 18%~24% | 强调区块悬浮 |
| `--oo-gradient-surface` | 品牌 4% → 透明 | 卡片顶部微光 |
| `--oo-gradient-shimmer` | 骨架流光 | 骨架屏动画 |

> **渐变两端都要能承载白字**
> 渐变背景上的文字对比度不能只看起点 —— 终点可能更亮。
> 初版浅色 `#4c6fff→#7c5cf0`：白字 4.18 / 4.52，**起点不达标**；
> 深色 `#5f7dff→#8f6cf5`：白字 3.58 / 3.73，**两端都不达标**。
> 现值浅色 5.64 / 5.65、深色 5.16 / 4.74，两端全部达标。

---

## 七、动效

### 7.1 缓动曲线

| Token | 曲线 | 用途 |
|---|---|---|
| `--oo-ease-out` | `cubic-bezier(.22,1,.36,1)` | **默认**，减速出场 |
| `--oo-ease-in-out` | `cubic-bezier(.65,0,.35,1)` | 对称动画 |
| `--oo-ease-spring` | `cubic-bezier(.34,1.56,.64,1)` | 轻微回弹 |

### 7.2 时长

`--oo-dur-fast` 120ms（hover 反馈）/ `--oo-dur-base` 200ms（常规过渡）/ `--oo-dur-slow` 320ms（面板切换、主题切换）/ `--oo-dur-slower` 480ms（大幅位移）

### 7.3 内置动画

`oo-fade-up`（面板淡入上浮）/ `oo-fade-in` / `oo-scale-in` / `oo-shimmer`（骨架流光）/ `oo-spin`

**无障碍**：`@media (prefers-reduced-motion: reduce)` 下全部动画时长归零（`base.css` 已处理）。

---

## 八、层级（z-index）

`--oo-z-base` 1 / `--oo-z-sticky` 100 / `--oo-z-drawer` 1500 / `--oo-z-dialog` 2000 / `--oo-z-popper` 2050 / `--oo-z-toast` 3000

---

## 九、焦点环

| Token | 值 | 说明 |
|---|---|---|
| `--oo-focus-ring` | 浅 `0 0 0 3px rgba(76,111,255,.28)` / 深 `rgba(138,160,255,.40)` | 外圈光晕 |
| `--oo-focus-ring-offset` | `0 0 0 1px var(--oo-border-brand)` | 内圈描边 |

所有可聚焦元素必须显式声明焦点样式（WCAG 2.4.7）。全局基线在 `base.css` 的 `:focus-visible`，组件内覆写时保留 `box-shadow` 双层。

---

## 十、组件复用结构

```
src/components/ui/
├── OOCard.vue          卡片容器（title/subtitle/loading/flush + header/actions/footer 插槽）
├── OOEmptyState.vue    空状态（5 种 SVG 图形 + loading 骨架 + 操作插槽）
├── OOStatTile.vue      KPI 数字块（tone 色调 + trend 趋势）
├── OOPageHeader.vue    页面标题区（title/description/badge + 操作插槽）
├── OOToolbar.vue       工具条（left/right 插槽）
├── OOSectionTitle.vue  区块小标题
├── OOSkeleton.vue      骨架屏（card/table/list 三形态）
├── OOThemeToggle.vue   主题切换（系统 → 浅 → 深 三态循环）
├── OOIcon.vue          内联 SVG 图标映射（24×24 网格 / 1.8px 描边）
└── index.ts            统一出口
```

**引用方式**：`import { OOCard, OOEmptyState } from "@/components/ui";`

### 组合模式

```
OOPageHeader（页面标题 + 操作）
  └─ OOCard（内容容器）
       ├─ OOToolbar（筛选/搜索/操作）
       ├─ el-table（数据，OOCard 用 flush）
       ├─ OOEmptyState（无数据时替代表格）
       └─ OOStatTile 网格（KPI 区）
```

---

## 十一、深浅色模式

### 11.1 切换机制

- 触发：`<html>` 上加/去 `.dark` 类 → CSS 变量整体切换
- 存储：`localStorage["oo-theme"]`，值 `light` / `dark` / `system`
- 三态循环：跟随系统 → 浅色 → 深色 → 跟随系统
- 跟随系统时监听 `matchMedia("(prefers-color-scheme: dark)")` 实时响应

### 11.2 首屏防闪白

主题必须在 `createApp().mount()` **之前同步应用**（`main.ts` 里调用 `initTheme()`）。
晚一步会先用浅色渲染一帧再切深色，用户看到明显闪白。

### 11.3 深色模式的设计原则

不是简单反色：
- 背景**降明**（app `#0e1117`），卡片**提亮一档**（`#171a22`）形成层次
- 品牌色提亮到 400 档（`#8aa0ff`）以保证在深底上的对比度
- 阴影改用更深的黑 + 微弱品牌辉光
- 同时设置 `color-scheme`，让浏览器原生滚动条/表单控件也切深色

---

## 十二、Element Plus 覆写策略

**不修改 EP 源码**，只覆写 CSS 变量 + 组件级样式。

| 层级 | 文件 | 作用 |
|---|---|---|
| 变量 | `tokens.css` | `--el-color-*` `--el-text-*` `--el-border-*` `--el-bg-*` `--el-fill-*` `--el-border-radius-*` `--el-font-*` `--el-box-shadow*` `--el-transition-*` |
| 组件 | `element-theme.css` | 按钮/输入/表格/卡片/对话框/标签/空状态/加载/进度/开关/滑块/提示的具体圆角、阴影、边框、悬浮态 |

**样式加载顺序**（`main.ts` 中固定，不可乱）：

```
element-plus/dist/index.css   ← 必须最先
  → styles/tokens.css           ← token + EP 变量
  → styles/element-theme.css    ← EP 组件级
  → styles/base.css             ← 重置与工具类
```

---

## 十三、响应式断点

| 断点 | 变化 |
|---|---|
| `> 1024px` | 完整布局，导航展开，顶栏显示文字 |
| `≤ 1024px` | 顶栏操作项只留图标 |
| `≤ 768px` | 侧栏收成图标条（68px），页面边距降到 16px，工具条换行，栅格降单列，隐藏表格次要列 |

**硬规则**：任何断点下都不得出现横向滚动；可点区域不小于 32×32px。

---

## 十四、无障碍清单（P0 门禁）

### 14.1 静态计算（选色时的初筛）

- [x] 所有交互元素有可访问名称（`aria-label` 或可见文本）
- [x] 正文对比度 ≥ 4.5:1，大字/UI ≥ 3:1
- [x] 不单靠颜色传达信息（状态都有文字标签）
- [x] 全部功能键盘可达（Tab 顺序合理）
- [x] 每个可聚焦元素有可见焦点环
- [x] 支持 `prefers-reduced-motion`
- [x] 320px → 桌面流体布局，无横向滚动
- [x] 骨架屏高度贴近真实内容，避免 CLS

### 14.2 浏览器真实渲染实测（最终判据）

> 静态脚本只能验证「我选的 hex 组合」，用户看到的是「浏览器算出来的最终渲染色」——
> 中间隔着 `opacity`、`color-mix()`、`backdrop-filter`、渐变叠加。
> 所以最终以真实 Chromium 的 `getComputedStyle` 实测为准。

**实测环境**：Chromium 1243，1440×900，**全部 17 个页面**（3 模块 × 各自全部二级 Tab），
每个页面遍历全部可见文本节点，向上找到**第一个不透明祖先**作为真实背景
（渐变背景取「对白字最不利」的那一端色标）。

#### 实测结果

| 模式 | 页面数 | 采样文本节点 | 未达标 |
|---|---|---|---|
| 浅色 | 17 | 379 | **0** |
| 深色 | 17 | 363 | **0** |

**总计 742 个文本节点，未达标 0 项。**

#### 本轮修复清单（都是实测发现的真问题）

| 问题 | 实测值 | 根因 | 修复 |
|---|---|---|---|
| 单选/复选选中态 | `#ffffff` on `#4c6fff` = 4.18:1 | EP 用 `--el-color-primary`（= `--oo-brand`）当填充底 | 覆写 EP 原生的 `--el-radio-button-checked-bg-color` → `--oo-brand-fill` |
| 主按钮 / 侧栏选中 / 页头徽章 | 白字压渐变起点 = 4.18:1（浅）/ 3.58:1（深） | 渐变起点色太亮 | 渐变两端都改用能承载白字的值（5.64 / 5.16） |
| alert 描述文字 | `#7d879c` on `#f8fafd` = 3.45:1 | EP 的 `.el-alert--info.is-light .el-alert__description`（specificity 0,3,0）压过了我们的低优先级规则 | 提优先级到 `.el-alert.is-light .el-alert__description` 并改用次级文字色 |
| 选择器提示文字 | `#7d879c` on `#ffffff` = 3.61:1 | 用了 placeholder 色 | 改三级文字色（4.64:1） |
| 深色三级文字 | `#7a8394` on `#1f232d` = 4.12:1 | 深色下 surface-2 比 surface 更亮 | 提到 `#828c9e`（4.63:1） |
| 深色 KPI 图标 | `#4c6fff` on 合成底 = 3.47:1 | `--oo-brand` 在深色下偏暗 | 改 `--oo-text-brand`（深色自动变 `#8aa0ff` → 5.91:1） |
| 禁用按钮 | `#ffffff` on `#a8b8ff` = 1.92:1 | EP 置灰后仍是白字 | 改「次级文字色 + 表面色底」（5.26 / 5.60） |
| info 语义文字 | `#0b7c72` on `#d3f5ef` = 4.37:1 | 色值偏浅 | 压深到 `#0a6f66`（5.20:1） |
| 复选框选中时标签 | `#4c6fff` on `#ffffff` = 4.18:1 | EP 把 label 染成 primary 色 | 改 `--oo-text-brand`（5.64:1） |

#### 审计脚本的坑（记录下来避免重犯）

1. **不能只取 `backgroundColor`** —— 渐变背景用 `background-image`，
   `backgroundColor` 是 `rgba(0,0,0,0)`，会把「白字压浅紫渐变」漏判成合规。
2. **不能笼统用卡片底色** —— 必须向上找元素**真正的**背景祖先，
   否则「浅色文字压在浅色提示块上」这类真问题会被漏掉。
3. **腾讯地图瓦片文字不算** —— `.tmap-scale-text` / `.logo-text` 是第三方 SDK 内容，
   但仍用 `:deep()` 覆写为跟随主题，否则深色下不可读（1.21:1 / 1.38:1）。
4. **禁用控件在 WCAG 里豁免**，但本项目仍按 4.5:1 处理 —— 禁用态也要读得出来。

---

## 十五、使用约定

1. **禁止在组件里写死颜色** —— 一律 `var(--oo-*)`。改主题只改 `tokens.css`。
2. **新增语义色先加 token**，再在组件里引用，不要在组件里临时起名。
3. **新增组件先查 `components/ui/`** —— 能复用就别新写。
4. **Element Plus 组件优先** —— 自研组件只做 EP 覆盖不到的部分（KPI 块、页面标题、图形化空状态）。
5. **图表配色走 `composables/chart-theme.ts`** —— ECharts option 是 JS 对象拿不到 CSS 变量，主题切换时需 `notifyChartThemeChange()` 触发重绘。
