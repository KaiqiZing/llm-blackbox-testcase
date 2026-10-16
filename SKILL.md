---
name: llm-blackbox-testcase
description: 基于大模型的黑盒测试用例生成方法论 skill。当用户要求"生成测试用例"、"写测试点"、"用黑盒方法设计用例"、"等价类/边界值/判定表/因果图/正交/Pairwise/状态迁移/场景法/错误推测"、"需求拆解成测试点"、"AI 生成测试用例"、"LLM 测试设计"、"基于业务场景组合黑盒测试方法"时使用；也让用户挑报告视觉模板（34 套 HTML 模板库可选，支持长文档报告与幻灯片 deck 两种形态）。核心思路：不问"该用什么方法"，问"被测对象的特征属于哪一类"。工作流为：素材清点（取图 + 锚定）→ 问业务域与范围 → 选报告视觉模板 → 读特征索引识别特征形态 → 按固化映射矩阵匹配方法 → 用 1 个需求点做样例确认 → 全量生成 → 交付 HTML 报告。内含完整特征形态分类学、黑盒方法目录、特征→方法映射矩阵（Few-Shot）、五段可复用 Prompt、图片需求源提取规范、质量闸门校验脚本（含图片证据闭环闸门）、报告骨架与 34 套视觉模板库。
agent_created: true
---

# LLM 黑盒测试用例生成方法论

一套可复用的"需求 → 测试用例"工作流。核心思路：**不问"该用什么方法"，问"被测对象的特征属于哪一类"**。特征形态一旦确定，黑盒方法就是推论，不是选择——模型执行的只是查表，不是凭经验猜。

本技能自带一套固定的输出契约：索引文件驱动路由、先出小样例给用户确认、产出固定为（成品 + 路径 + 一句理由）、视觉系统是封闭集合。
该模板库已**内置**在 `templates/deck-library/`（34 套，MIT，随本技能一起分发）——本技能可以在生成报告时让用户从 34 套里挑一套视觉系统。

- Skill 根目录：本 `SKILL.md` 所在目录（安装位置随宿主而异，示例中一律写成 `scripts/...` 相对路径）
- 特征形态索引：`index.json`（18 类特征形态，**先只读这个**，别全读 references）
- **图片需求源提取规范：`references/image-extraction.md`（取图方法 / 锚点映射 / 八类必提元素 / 回填方式）**
- 固化映射矩阵（含 Few-Shot）：`references/mapping-matrix.md` ← 方法匹配时注入这个
- 特征形态完整分类学：`references/feature-taxonomy.md`（18 大形态详解，按 6 大类组织 + 证券示例）
- 黑盒方法完整目录：`references/method-catalog.md`（14 种方法：适用条件、步骤、产出、优缺点）
- 质量闸门：`references/quality-gates.md`（9 道闸门，含图片证据闭环，可机械化检查项）
- 五段 Prompt：`prompts/00-asset-inventory.md`（素材清点）→ `01-requirement-decompose.md` ~ `04-case-generation.md`
- 系统级约束：`prompts/system-constraint.md`（含映射矩阵，作 system prompt 用）
- 输出报告模板：`templates/report-template.html`（blue-professional 设计系统，单文件长文档）
- **报告视觉模板选型手册：`templates/TEMPLATE-GUIDE.md`（选型流程 / 推荐梯队 / 幻灯→长文改造规范 / CJK 规格 / 红线）← 选模板时读这个**
- **视觉模板库：`templates/deck-library/`（34 套完整设计系统 + 画廊 + 102 张预览图）**
  - 选型索引：`templates/deck-library/index.json`（`mood` / `tone` / `occasion` / `formality` / `density` / `scheme` / `best_for`）
  - 预览画廊：`templates/deck-library/gallery.html`（缩略图 + 情绪标签 + 筛选，直接 `present_files` 推给用户挑）
  - 单套模板：`templates/deck-library/templates/<slug>/`（`template.html` 完整多页演示稿 + `design.md` 设计系统规格 + `template.json` 元数据）
- **取图脚本：`scripts/extract_images.py`（一键解包素材里的图，产出 images/ + manifest.json；同内容图自动合并去重、过小图自动排除、按字节中位数给偏大/偏小的图附中性的「尺寸提示」；`--also-text` 一并导出正文与每张图的前后正文段落）**
- **报告装配脚本：`scripts/render_report.py`（把 step1~step4 的 JSON 产物装配成单文件 HTML 长文档；指标与闸门结论由脚本实算/实跑，不由模型手填；`--embed-images` 可把图内联进 §0 做到单文件自包含）**
- 输出校验脚本：`scripts/validate-output.py`（对第 3 步五段 Prompt 的 JSON 产物做机械校验，含闸门⑨；方法矩阵按 `references/mapping-matrix.md` 硬校验主方法；`--stage all --dir .` 四段连校验 + 跨段一致性：需求点回溯 / 测试点宽松匹配 / 待确认传导）

---

## 工作流（必须按顺序执行，不要跳步骤）

### 第 0 步 — 素材清点（含图片时不可跳过）

需求素材里的图（原型图、界面截图、状态图、字段表截图）常常承载**正文没写、但必须测**的信息。
典型陷阱：正文只写一句「字段如图所示」，图就是**唯一**需求源；漏了图，需求点直接缺一半。

**怎么判断要不要跑这一步**：素材里有没有图（docx/pptx/xlsx 内嵌图、pdf 页、md 相对路径图、对话粘贴的截图）。
有图就必跑，没有图可跳过（但要说明「本次素材无图，闸门⑨ 不适用」）。

```bash
# 1) 一键取图，产出 images/ + manifest.json
#    加 --also-text 同时导出正文（含 [IMG img-N] 标记）；docx/pptx 会额外
#    给每张图附上「前一正文段落 / 后一正文段落」——这是锚点映射的直接证据
python3 scripts/extract_images.py <素材文件> --out ./assets --also-text
```

> **取正文与取图的优先顺序**：docx / pptx / xlsx / pdf 一律优先用 `extract_images.py`（加 `--also-text`）。
> 用 office 类工具 `open_file --image_dir` 取图在部分素材上会产出空目录，图片只能从会话 URL 拿，
> 且拿不到图与正文的相对位置——不要把它当首选路径。

2) 逐张看图（**必须真的看**，不能只看文件名），按 `references/image-extraction.md` §三 的八类清单清点：
   字段名+必输标记 / 按钮+位置 / 列表列名 / 查询条件 / 分页参数 / 状态列 / 弹窗文案 / 校验提示。

3) 跑 `prompts/00-asset-inventory.md`，产出 `asset-inventory.json`（素材清单 + 锚点映射 + 缺口清单）。
   **关键动作**：把正文里「如图所示 / 如下图 / 见下图 / 如图 1 所示 / 图 3-1 所示 / 按下图 / 如下截图 / 如下表 / 界面如下」这类措辞，
   逐条锚定到具体图号 `img-N`。锚不上的写进 `gaps[]`，不许放过。

4) 校验素材清点结果：

```bash
python3 scripts/validate-output.py asset-inventory.json --stage inventory --manifest ./assets/manifest.json
```

**为什么这一步不能省**：实测某需求文档 19 条需求点里，10 条引用截图、5 条是纯图需求（正文只有「如图所示」），
且状态机的关键分支「直接上架」按钮**只存在于图片里**。不做素材清点，这几条需求全部静默丢失。

### 第 1 步 — 先读特征索引，再问业务域 / 范围 / 报告模板

即使用户的需求已经很具体，也要先问这三件事（**业务域知识**决定规则正确性，**范围**决定产出体量，**模板**决定视觉调性）：

> 开始拆解之前先确认三件事（+ 一个可选第四问）：
> 1. **什么业务域？**（比如：证券交易、银行支付、保险核保、电商、SaaS 后台……有没有领域规则文档/接口文档/历史缺陷库可以提供？）
> 2. **这次覆盖到什么粒度？**（只出「需求点 | 测试点 | 特征 | 方法」映射表，还是要展开到可执行用例？大概几个需求点？）
> 3. **报告想要什么调性？**（正式交付 / 内部评审 / 投屏演示；克制专业 / 学术档案 / 编辑部质感 / 数据看板……也可以直接说"用默认的"或"先看画廊"）
> 4. **（要展开用例时必问）测试边界到哪一层？**——有无接口文档？能否直接调接口（绕过前端）？
>    端侧 / 外部系统的验证环境是否可用？答案决定「非法迁移防护、越权矩阵、跨系统推送」类用例的写法：
>    - **可直调接口** → 写成可执行用例（具体请求 + 预期响应/状态码），`是否可自动化: 是`；
>    - **只有 UI** → 降级为「UI 层入口缺失断言」，覆盖度报告里显式声明接口层未覆盖（这是缺口，不是待确认）；
>    - **未知** → 用例标 [待确认] 进 §6，不进执行集。

等用户回答，不要先猜。用户没给业务规则时，明确告知"规则将以通用常识为准，产出中所有规则性表述都会标注 [待确认]"。
第 4 问的答案在第 5 步生成用例时消费：不问就写，最常见的后果是产出一批"写了跑不了"的用例
（预期结果只能写 [待确认]），或者把接口层缺口误当成需求待确认项。
**问的同时**，把**技能根目录** `index.json` 的各 `signals` / `examples` 在脑子里与素材做一次初筛匹配，为第 3 步特征建模做准备。

> 注意区分两个 `index.json`：**技能根目录** `index.json` = 18 类特征形态索引（本步骤用）；
> `templates/deck-library/index.json` = 34 套视觉模板元数据（第 1.5 步用）。

### 第 1.5 步 — 定报告视觉模板（不可跳过，第 4 步之前完成）

**模板不是"最后套个皮"，是第 4 步给用户看样例的载体。样式定得晚，前面的映射表和用例表格白排一遍。**

完整流程、推荐梯队、改造规范见 **`templates/TEMPLATE-GUIDE.md`**（选模板前先读它）。要点：

1. **问清形态**（若第 1 步没问出来就补问）：要**长文档报告**（滚动阅读、逐条核对，默认）还是**幻灯片 deck**（投屏讲、键盘翻页）？
2. **读 `templates/deck-library/index.json` 挑 3 个候选**：匹配 `mood` / `tone` / `best_for` / `formality` / `scheme`。
   测试报告优先看 **`density`**（`high` 才扛得住密集表格）与 **`formality`**（正式场景要 `high`/`medium-high`）。
   三个候选要**拉开差异**：一个正中、一个温和替代、一个反差野牌（比如深色版）。
3. **给用户看预览，等确认**（二选一）：
   - 快：`present_files` 推 `templates/deck-library/gallery.html`，用户自己 34 套里点。
   - 准：取候选的 `template.html` 第一页换成用户真实标题/项目名/日期，落工作区 `previews/`，`present_files` 推 3 个对比。
4. **用户选完再进第 2 步**。用户说"用默认"→ 直接走 `templates/report-template.html`（blue-professional），不要再来回确认。

**测试报告推荐梯队**（详见手册第三节）：
第一梯队 `blue-professional`(默认) · `cobalt-grid` · `signal` · `monochrome` · `cartesian` · `stencil-tablet`；
第二梯队 `soft-editorial` · `emerald-editorial` · `editorial-forest` · `editorial-tri-tone` · `long-table` · `mat` · `vellum` · `broadside` · `neo-grid-bold`；
第三梯队（低正式度，正式测试报告**不用**）`8-bit-orbit` · `daisy-days` · `sakura-chroma` · `pink-script` · `scatterbrain` · `retro-zine` · `retro-windows` · `peoples-platform` · `creative-mode` · `coral` · `studio` · `playful` · `pin-and-paper` · `block-frame` · `raw-grid` · `bold-poster` · `capsule` · `grove`。
**合规 / 归档场景硬性避开深色模板。**

### 第 2 步 — 识别特征形态（对照 `index.json` 的 18 类）

把用户需求与素材的每个环节对照 18 类特征形态的 `signals` / `examples` 做初筛匹配。这一步只定性不定量——先圈出"这个需求大概会涉及哪几类特征"，为第 3 步的特征建模做准备。

字段速查：

| 字段 | 用法 |
|---|---|
| `signals` | 判定信号，逐条对照需求的描述 |
| `examples` | 示例场景，软信号，不是硬过滤 |
| `methods` | primary / secondary，第 3 步的输出依据 |
| `avoid_for` | 误用警告：出现这种特征时不要用该主方法 |
| `combo_scale_rule` | 组合规模判定规则，> 20 必须标"需降维" |
| `failure_signal` | 该特征下最常见的漏测模式，质量闸门会查 |

特征形态**跨类是常态**——一个测试点通常带 1 个主特征 + 1~2 个次特征，都要记录。

### 第 3 步 — 五段 Prompt 逐段跑，素材清点 → 特征建模 → 方法匹配

按顺序执行（文件在 `prompts/`，**分次调用，不要合成一段**；每段产出 JSON，可独立复核、可单独重跑）：

1. `00-asset-inventory.md`：素材 → 素材清单 + 文本→图片锚点映射 + 缺口清单（**素材含图时必跑**）
2. `01-requirement-decompose.md`：素材 → 原子需求点清单（每条必须可独立验证，依据分「文本依据」+「图片依据」）
3. `02-feature-modeling.md`：需求点 → 测试点 × 被测对象特征画像（特征必须归入 `index.json` 的 18 类之一）
4. `03-method-matching.md`：特征画像 → 方法矩阵（**必须注入 `references/mapping-matrix.md` 作为系统约束**，禁止凭习惯选方法）
5. `04-case-generation.md`：方法矩阵 → 可执行用例 + 覆盖度自检（需要展开到用例时才跑这段）

每段跑完，用 `scripts/validate-output.py <产物.json>` 做机械校验：

```bash
python3 scripts/validate-output.py step1.json --stage require --manifest ./assets/manifest.json
python3 scripts/validate-output.py step2.json --stage feature
python3 scripts/validate-output.py step3.json --stage method
python3 scripts/validate-output.py step4.json --stage case    # 展开到可执行用例时才跑
```

**四段跑齐后，再跑一次四段连校验（跨段一致性检查）：**

```bash
python3 scripts/validate-output.py --stage all --dir .
```

自动发现当前目录的 `asset-inventory.json / step1~4.json / assets/manifest.json`，逐段校验之外还查三件单段查不到的事：
① step3/step4 引用的需求点必须能在 step1 里回溯（防凭空出现）；
② step4 用例的测试点应能对上 step3 同需求点下的测试点（归一化前缀 + 子序列宽松匹配，缩写改写不算失配；告警级，提示统一措辞）；
③ step1 标 `待确认:true` 的需求点，其用例预期应至少一条带 `[待确认]`（规则不确定须传导到用例层）。

校验不过 → 回到对应 Prompt 补跑，不要带病往下走。
**闸门⑨ 图片证据闭环**在 `--stage require` 时生效：正文引用图的段落必须有对应 `图号` 与 `提取元素`，缺一即硬性不通过。

### 第 4 步 — 拿 1~2 个需求点做完整样例，给用户确认

不要一口气全量生成。挑 1~2 个**特征形态差异最大**的需求点（比如一个"连续数值区间"型 + 一个"组合爆炸"型），完整跑通"需求点 → 测试点 → 特征 → 方法 → 用例"，交给用户确认：

> 先拿两个差异最大的需求点跑通给你看：
> 1. **R1 委托价格**（连续数值区间型）→ 等价类 + 边界值，X 条用例
> 2. **R6 委托类型组合**（组合爆炸型）→ 正交 L18 + Pairwise，72 组合降到 18 条
>
> 这个密度和格式可以吗？确认后我全量跑。

等用户确认。（注意：样例直接以表格，或**第 1.5 步选定模板的设计系统**渲染成 `templates/report-template.html` 的一个章节来呈现，不要另起炉灶设计样式。若用户在第 1.5 步只选了模板还没看封面，可顺手把封面 + 这一节一起推过去，一次确认掉。）

### 第 5 步 — 全量生成

用户确认后，对所有需求点跑完流程，产出：

1. **映射表**（核心交付）：需求点 | 拆分测试点 | 被测对象特征 | 推荐黑盒测试方法（主+辅）
2. **用例集**（用户要求展开时）：每条测试点的可执行用例，数据具体到值、预期唯一可判定
3. **覆盖度报告**：需求覆盖率、方法覆盖率、无效域用例占比、降维损失说明，
   以及**测试边界缺口声明**（第 1 步第 4 问答案为「只有 UI」时，显式列出哪些用例降级为
   UI 层断言、接口层哪些检查没做）
4. **素材清点说明**（素材含图时）：图片总数、锚点映射条数、未用到的图、证据降级声明

遇到 `index.json` 没有覆盖的新特征形态：**不要硬归类**。在输出中显式标注"新特征候选：<描述>"，并建议是否补进分类学（详见下方「扩展规则」）。

### 第 6 步 — 交付

按第 1.5 步定的形态产出，**用 `present_files` 打开成品**：

- **形态 A 长文档报告**（默认）：**优先用 `scripts/render_report.py` 装配**，不要把上百行表格手敲进 HTML：

```bash
python3 scripts/render_report.py --dir . --out 报告.html --title "<需求名>" \
    --business-domain "<业务域>" \
    --inventory asset-inventory.json --manifest assets/manifest.json [--embed-images]
```

  脚本会把 `templates/report-template.html` 的 `<style>` **整套提取**作为唯一视觉真源，
  自动装配封面 / §0 素材清点 / §1 映射表 / §2 方法分布 / §3 用例集 / §4 降维损失 / §5 闸门 / §6 待确认，
  并实跑 `validate-output.py` 生成 §5 的闸门结论、给大表挂上筛选控件。
  只有需要人工改写个别段落时，才直接以 `templates/report-template.html` 为骨架手改；
  套用第 1.5 步**选定模板的设计系统**时（色板来自该模板 `design.md` 的 `colors:`、字体来自 `typography:`），
  用 `--template <该模板的 template.html>` 整套切换，语义组件 `tag-pill` / `callout` / `bar-track` /
  `step-circle` 与表格粘性表头的**结构不改**。用户没选模板 → 直接用 blue-professional 原样。
- **形态 B 幻灯片 deck**：整目录复制 `templates/deck-library/templates/<slug>/` 到工作区（含其自带的 `deck-stage.js`），按页序建议逐页替换内容，页码 `NN / TT` 同步更新。

交付说明附一句：本次覆盖几个需求点、用到哪几种方法、有哪些 [待确认] 项和降维损失、图片来源是否完整提取；**再附一句选型理由**（如"Signal 的高密度栅格能扛 60 条用例一页不溢出"）**+ 一句 caveat**（如"深色底打印费墨，归档建议换 Monochrome"）。不要逐步骤汇报过程。

---

## 保留 / 替换规则

**必须保留（这些就是方法论本身）：**

- **特征类型学**：18 类特征形态（`index.json` + `references/feature-taxonomy.md`）是封闭系统，生成时不许临时发明新类别。确实遇到新形态 → 走「扩展规则」。
- **映射矩阵**：`references/mapping-matrix.md` 的 特征→方法 对应关系是系统约束，不许凭"通常都这么做"改映射。映射错了改矩阵，不要在单个用例里绕。
- **多段分离**：不许把 Prompt 合成一段。合并会在长输出里丢约束（尤其"标注依据"这类）。
- **素材清点不可跳过**：素材含图时必须先跑第 0 步，图片不是正文的配图，是独立需求源。
- **闸门⑨ 图片证据闭环**：正文引用图的措辞必须锚定到图号并提取元素，不许让「如图所示」成为空话。
- **JSON Schema 字段**：`scripts/validate-output.py` 依赖固定字段名，改字段必须先改脚本。
- **报告设计系统**：`templates/report-template.html` 的色板、字体声明、组件语法（tag-pill / card-tinted / bar-track / step-circle / callout）不许**逐个**改；整套换成 `deck-library` 里某个模板的设计系统是允许的（第 1.5 步的选定动作），但必须**整套换**——色板与字体同源。缺版式时用**当前**设计系统现场设计，不要引入第三套视觉语言。
- **模板库的封闭性**：`deck-library/` 的 34 套是封闭集合，不许临时拼装"新模板"。要新视觉语言 → 走「扩展规则」，按上游规格补进 `deck-library/templates/<new-slug>/`（`template.html` + `design.md` + `template.json`）并更新 `index.json` 的 `template_count`。
- **长文档注入契约**：`report-template.html` 里的注入点（封面 / 章节锚点 / 映射表 / 用例表 / 覆盖度 / [待确认] 清单）结构固定，换设计系统时只换这些点的**外观**，不改**位置与语义**。

**必须替换（这些是业务的内容）：**

- 需求原文、业务规则、领域示例（证券示例只是 Few-Shot，换业务域时整体替换）
- 风险等级阈值（`combo_scale_rule` 的 20 可按团队接受度调）
- 质量闸门中"无效域占比 ≥ 30%"这类数值（按团队缺陷分布校准）
- 图片八类必提元素清单：通用；但若业务域有额外的图必提项（如证券的行情刷新时间、涨跌色），追加进团队副本

**禁止事项：**

- 不要跳过第 1 步直接生成；不要跳过第 4 步的样例确认（说一堆取舍不如直接给用户看）。
- **不要跳过第 1.5 步的模板确认**：用户明确说"用默认的"才算跳过；不确认就直接套 blue-professional，等于替用户定了调性。
- **不要跨模板混搭**：不许拿 A 的封面 + B 的表格页 + C 的色板。选定哪套就整套用。也不要只改色板不改字体（或反之）——设计系统是捆绑的。
- **不要跳过第 0 步**：素材含图却不做素材清点，等于放弃一半需求源，这是本技能最严重的失误。
- 不要让模型编造业务规则。规则缺失时标 [待确认]，不许替业务方拍板。
- **不要让模型猜图**：看不清的元素写「[图不清] 疑似：xxx」，不许编造图里没有的字段或按钮。
- 不要接受"全部测试点都推荐等价类+边界值"的输出——这是模型偷懒的标志，触发质量闸门 ③。

---

## 扩展规则（发现新特征形态 / 新方法时）

1. 在 `index.json` 的 `features` 数组新增条目：slug（小写连字符）、name、signals、examples、methods、avoid_for、combo_scale_rule、failure_signal。
2. 同步更新 `references/feature-taxonomy.md`（详解）与 `references/mapping-matrix.md`（映射 + Few-Shot）。
3. 若引入新的黑盒方法，先写入 `references/method-catalog.md`（适用条件、步骤、产出、优缺点、组合关系），再进映射矩阵。
4. 更新 `index.json` 的 `feature_count` / `method_count`，并给 `scripts/validate-output.py` 的合法枚举补上新值。
5. 新增素材格式（如 visio、axure 原型包）→ 在 `scripts/extract_images.py` 的 `ZIP_MEDIA_DIRS` 加目录映射，
   并同步 `references/image-extraction.md` §1.2 的格式表。
6. 新增视觉模板 → 在 `templates/deck-library/templates/<new-slug>/` 放齐 `template.html` + `design.md` + `template.json`
   （有翻页脚本就一并带上 `deck-stage.js`），更新 `templates/deck-library/index.json` 的 `template_count` 与 `templates[]`，
   补一张预览图到 `templates/deck-library/screenshots/<slug>-1.png`，并回写 `gallery.html` 的卡片与链接。
   同时在 `templates/TEMPLATE-GUIDE.md` 第三节的梯队表里给它归位。

---

## 本机环境的注意事项

- **呈现方式**：成品用 `present_files` 交付，不要用 `open` 命令。画廊 `templates/deck-library/gallery.html` 同样用 `present_files` 推（Windows 下不要用 `open <path>`，改 `present_files` 或 `start "" "<path>"`）。
- **上下文控制**：`references/` 各文件较长。**第 2 步只需要 `index.json` + `references/mapping-matrix.md`**；只有命中陌生特征或需要向用户解释方法原理时，才去读 `feature-taxonomy.md` / `method-catalog.md` 的对应章节。**第 0 步只需要 `references/image-extraction.md`**。
  **第 1.5 步只需要 `templates/TEMPLATE-GUIDE.md` + `templates/deck-library/index.json`**——`index.json` 已带 `mood`/`tone`/`formality`/`density`/`scheme`/`best_for`，足够选出 3 个候选，**选型前不要逐个读 34 份 `design.md`**；只有用户选定后，才去读那一套的 `design.md`（并优先读末尾的 CJK 章节）。
- **模板库路径自洽**：`deck-library/gallery.html` 内的相对链接（`templates/<slug>/template.html`、`screenshots/<slug>-N.png`）是相对 `deck-library/` 根目录的，**整个目录一起复制/一起移动**，不要只搬 `gallery.html`。34 套模板里 10 套自带 `deck-stage.js`（同目录引用），复制单套 deck 时必须**连该目录整个带走**，否则翻页失效。
- **字体**：`templates/report-template.html` 声明 Space Grotesk + Inter，已带 CJK 降级链（PingFang SC / Microsoft YaHei）。国内网络下西文字体可能退化为系统字体，中文字体不受影响。外部依赖仅两个 CDN：`fonts.googleapis.com`（字体）与 `cdn.jsdelivr.net/npm/chart.js`（部分模板的图表），离线环境需换本地字体/图表库。
- **脚本环境**：`scripts/validate-output.py` 与 `scripts/extract_images.py` 只用 Python 标准库，无第三方依赖、无网络。
  - `validate-output.py` 不读写除入参外的任何文件，直接用系统 `python3` 运行即可。
  - `extract_images.py` 只写出 `--out` 指定目录（默认 `./assets`），pdf 抽图需要系统有 `pdftoppm`（缺失时自动降级为「按页登记」并记入 `gaps`，不会崩）。
- **本机路径提醒**：Windows 下 `python3` 可能不存在，改用当前环境的解释器绝对路径。先探测，不要硬编码：
  - Git Bash / WSL：`which python3 || which python`
  - Windows：`where python`（或 `py -3 -c "import sys;print(sys.executable)"`）
  - 若使用托管运行时，按其安装位置拼出绝对路径（不同机器、不同版本号都不一样）。

**跨环境移植性提醒（本技能会被复制到其它机器 / 上传到远端仓库）：** 任何文档或脚本里都不要写死某台机器的
用户名、家目录或解释器版本号；示例一律用 `python3` 加相对路径，附一句"Windows 下若 `python3` 不存在，
改用 `where python` 得到的绝对路径"。

