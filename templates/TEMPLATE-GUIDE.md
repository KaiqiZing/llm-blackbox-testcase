# 报告视觉模板选型手册

`templates/` 下有两件事，别搞混：

| 路径 | 是什么 | 形态 |
|---|---|---|
| `templates/report-template.html` | **默认报告骨架**（blue-professional 设计系统的单文件长文档，表格优先、粘性表头、内置筛选 JS） | 单页长文档（滚动阅读） |
| `templates/deck-library/` | **34 套完整视觉系统**（上游 beautiful-html-templates，MIT） | 多页 HTML 幻灯片（键盘翻页） |
| `templates/TEMPLATE-GUIDE.md` | 本文件——怎么选、怎么把幻灯片模板改造成长文档报告 | — |

> `deck-library/` 是**设计系统库**，不是"换掉 report-template.html 的文件"。选模板 = 选**色板 + 字体 + 组件语法**，然后套到报告骨架上。

---

## 一、选型在哪一步做

放在**第 4 步（样例确认）之前**，和第 0 步素材清点一样属于"不可跳过"的前置动作。理由：视觉调性定得晚，前面的映射表/用例表格白排一遍。

推荐顺序：

```
第 0 步 素材清点  →  第 1 步 问业务域  →  【选模板】  →  第 3~4 步 建模/样例  →  第 5 步 全量  →  第 6 步 交付
```

问模板可以和"问业务域与范围"**合并成一次提问**，省一轮往返。

---

## 二、怎么选（三步，别跳）

### 1. 问两个问题

> 这份测试报告的场合是什么？
> - **正式交付**（给甲方 / 评审会 / 合规归档）
> - **内部评审**（团队复盘 / 研发对齐）
> - **演示汇报**（会上投屏讲，要能翻页）
>
> 想要什么调性？
> - 克制专业 / 学术档案 / 编辑部质感 / 数据看板 / 干净现代 …

### 2. 读 `deck-library/index.json` 挑 3 个候选

匹配字段：`mood` / `tone` / `occasion` / `best_for` / `formality` / `density` / `scheme`。

`density: high` = 能扛密集表格与长列表 → **测试报告优先看这个字段**。
`formality: high` = 正式场景安全。
`scheme: dark` = 深色，投屏好看但打印/长时间阅读累，长文档报告慎用。

三个候选要**拉开差异**：一个正中（稳妥）、一个温和替代（同正式度换质感）、一个反差野牌（比如深色版）。

### 3. 给用户看预览，等确认

两个办法，按用户熟悉程度选：

- **快**：直接用 `present_files` 推 `deck-library/gallery.html` —— 34 套缩略图 + 情绪标签 + 筛选（搜关键词 / 按明暗 / 按正式度），用户自己点。
- **准**：取每个候选的 `deck-library/templates/<slug>/template.html` **第一页**，把占位内容换成用户真实的需求名称/项目名/日期，存成独立 HTML 落到工作区 `previews/`，再 `present_files` 推 3 个文件对比。

Windows 环境**不要**用 `open <path>`，用 `present_files` 或 `start "" "<path>"`。

---

## 三、测试报告推荐梯队

针对"需求点 | 测试点 | 特征 | 方法 | 用例"这类**高密度表格 + 长文本**内容，按适配度分档：

### 第一梯队 — 正式交付首选

| slug | 名称 | 正式度 | 密度 | 明暗 | 适配理由 |
|---|---|---|---|---|---|
| `blue-professional` | Blue Professional | medium-high | medium | light | **默认**。已有长文档骨架 `report-template.html`，米白底 + 钴蓝单强调色，表格与数值标注层次清晰 |
| `cobalt-grid` | Cobalt Grid | high | medium | light | 设计研究/学术气质，栅格严谨，适合方法论文档 |
| `signal` | Signal | high | high | mixed | 机构级、密度最高（18 页），适合大体量用例集 + 覆盖度报告 |
| `monochrome` | Monochrome | high | high | light | 克制档案感（18 页），纯黑白灰，打印友好、归档友好 |
| `cartesian` | Cartesian | high | low | light | 安静优雅，适合"方法论说明 + 少量用例"的轻量交付 |
| `stencil-tablet` | Stencil & Tablet | medium-high | medium | light | 档案/质朴质感，克制但不像咨询报告 |

### 第二梯队 — 轻正式 / 编辑部质感

`soft-editorial` · `emerald-editorial` · `editorial-forest` · `editorial-tri-tone` · `long-table` · `mat` · `vellum`(dark) · `broadside`(dark) · `neo-grid-bold`

适合内部评审、团队内分享。`broadside`（20 页）和 `signal` 一样能扛量，但深色、戏剧性强。

### 第三梯队 — 不宜用于正式测试报告

`8-bit-orbit` · `daisy-days` · `sakura-chroma` · `pink-script` · `scatterbrain` · `retro-zine` · `retro-windows` · `peoples-platform` · `creative-mode` · `coral` · `studio` · `playful` · `pin-and-paper` · `block-frame` · `raw-grid` · `bold-poster` · `capsule` · `grove`

理由：低正式度、装饰多、对比弱或大面积深底——表格可读性和长时间阅读体验都会掉。
**能用的例外**：内部"AI 生成用例质量复盘"这类要活泼一点的分享场，可用 `neo-grid-bold` / `bold-poster` / `coral`。
**合规 / 归档场景硬性避开深色模板**（`pink-script` / `vellum` / `broadside` / `studio` / `8-bit-orbit`）。

---

## 四、两种产出形态（先问清用户要哪种）

### 形态 A — 长文档报告（默认，推荐）

**滚动阅读的单文件长文**，表格优先。用于评审、归档、逐条核对用例。

做法：用 `templates/report-template.html` 作骨架，把 **选定模板的设计系统**替换进去。

要把骨架里哪些东西换成选定模板的（从 `deck-library/templates/<slug>/design.md` 抽）：

| 骨架里的东西 | 换成 |
|---|---|
| `:root` 里的色板变量 | 选定模板 `design.md` 的 `colors:` 段 |
| `--font-display` / `--font-body` | 选定模板 `design.md` 的 `typography:` 段（保留 Google Fonts 导入） |
| 圆角 / 边框 / 卡片底色浓度 | 选定模板 `design.md` 的组件规格（`card-bg`、`border`、`radius`） |
| 封面几何装饰（`::after` clip-path 斜切） | 选定模板的封面装饰语汇（条纹、色块、纸纹、栅格） |

**不要换的**：`.wrap` 宽度与节奏、表格粘性表头、筛选 JS、`tag-pill` / `callout` / `bar-track` / `step-circle` 这几类**语义组件**的结构。语义组件是方法论的一部分（标签 = 特征/方法/风险，callout = [待确认]、降维损失），换了就不是同一份报告了。

### 形态 B — 幻灯片 deck（用户要投屏讲时）

**多页 HTML 幻灯片**，键盘翻页。用于评审会讲 15 分钟。

做法：把 `deck-library/templates/<slug>/` **整个目录**复制到工作区（连同该目录自带的 `deck-stage.js`，若模板有的话），逐页替换内容，分页结构见该模板自带的 `design.md`。

测试报告的 deck 化**页序建议**：

1. 封面（需求名称 / 被测系统 / 版本 / 日期）
2. 本次覆盖范围（需求点数量、方法分布）— 用 `metric`/大数字版式
3. 素材清点结论（图片总数、锚点映射、未用图、证据降级声明）
4. **映射表**（需求点 | 测试点 | 特征 | 主辅方法）—— 一页放不下的拆两页，页码 `NN / TT` 同步更新
5. 特征形态分布（哪个形态命中多少测试点）
6. 样例：1~2 个差异最大的需求点，展开到用例
7. 覆盖度（需求覆盖率 / 方法覆盖率 / 无效域占比 / 降维损失）
8. [待确认] 清单 + 下一步

---

## 五、中文（CJK）注意 — 本库已内置规格

多数 `design.md` 末尾带 **CJK 章节**，中文内容务必先读它。要点通常是：

- CJK 行高比拉丁规格放大 **15–25%**（拉丁 display 常用 0.84–0.96 行高，中文会上下碰撞，最低 **1.0**）
- 中文字间距**归零**（拉丁的 −0.005em ~ −0.04em 负字距会让方块字笔画重叠）
- 中文不做 `text-transform: uppercase`
- 粗体/斜体：Instrument Serif italic 无中文对应，用思源宋体 400 + 松行高替代
- CJK 字体走 `cn-fontsource` CDN，**不要自己编包名**
- 混排句式如「使用 Claude 思考」应落在同一字体栈里自动按字形回退，不要额外加语言 class

---

## 六、红线（做错就废）

**必须原样保留**（这就是设计系统本身）

- 字体（Google Fonts 导入与 `font-family` 声明）—— 不许替换成"差不多的 Inter"
- 色板（所有 `:root` 变量）—— 不许改色
- 版式网格、绝对定位、flex 层级
- 页面级 CSS 类与语义组件语法
- 装饰元素（角标、纸纹、手绘涂鸦、几何形、SVG 插画）—— 不是可选噪音
- 导航运行时（`deck-stage.js` / 内联键盘 / scroll-snap）—— 原样沿用

**必须替换**（这是业务的内容）

- 需求原文、业务规则、领域示例（证券示例只是 Few-Shot）
- 标题、正文、列表、图注
- 数字与统计占位（`47%`、`2.4M`、`+142%`）
- 人名、日期、出处、`[Topic]` `[Year]` `[Studio]` 这类占位符
- 图片占位（`img-placeholder`）→ 换真实图片，**尺寸保持一致**

**禁止**

- 跨模板混搭页面（拿 A 的封面 + B 的表格页）
- 因为"Inter 差不多"就换字体；因为"这个蓝太蓝"就改色
- 去"现代化"老模板
- 缺版式时换模板或回退问用户——应当用**当前模板的设计系统**（同字体、同色板、同装饰语汇、同间距节奏、同组件语法）现场设计缺失页。自查法：插进两页之间看一眼，像同一个系统就用，像拼接的就重做。

**加页**：复制最合适的现成版式再加，并更新页码 `NN / TT`。
**减页**：从底部删，并更新页码。

---

## 七、交付与落盘

- 输出到**用户当前工作区**，不要写回技能目录。技能目录里的 `deck-library/` 保持原样，只做**复制源**。
- 每个产物（预览 / 中间稿 / 终稿）都用 `present_files` 给可点击路径。
- 最终稿附一句**选型理由**（调性匹配点，如"Signal 的高密度栅格能扛 60 条用例一页不溢出"）+ 一句 caveat（如"深色底打印会费墨，归档建议换 Monochrome"）。

---

## 八、外部依赖

只有两个 CDN：`fonts.googleapis.com`（字体）与 `cdn.jsdelivr.net/npm/chart.js`（部分模板的图表）。
离线环境需替换为本地字体/图表库。国内网络下西文字体可能退化为系统字体，**中文字体不受影响**（已带 CJK 降级链）。

---

## 九、素材来源与许可

- 模板来源：https://github.com/zarazhangrui/beautiful-html-templates （MIT，作者 Zara Zhang）——本仓库使用的是其模板文件，许可文本见 `deck-library/LICENSE`，仅适用于该目录。
- 本仓库其余部分（工作流、prompts、分类学、脚本、本手册）均为原创。
- 新增/更新模板时：对齐上游 `git pull` 后重新复制 `templates/`、`screenshots/`、`index.json`、`gallery.html` 即可。
