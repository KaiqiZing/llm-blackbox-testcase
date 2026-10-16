# llm-blackbox-testcase

[English](README.md) | **中文**

一个把需求文档变成**可追溯黑盒测试设计报告**的 Agent 技能——用大模型，但不让大模型自由发挥。

核心思路：**不问「该用什么方法」，问「被测对象的特征属于哪一类」。** 特征形态一旦确定，黑盒方法就是推论，不是选择。模型执行的只是查表，不是凭经验猜。

---

## 为什么需要它

直接让大模型「生成测试用例」，你几乎一定会拿到这三种毛病：

1. **归一化偷懒**：所有测试点都变成「取值范围」，所有方法都是「等价类 + 边界值」。
2. **图片静默丢失**：需求里写「字段如图所示」，那张截图就是这些字段、按钮、状态的**唯一**需求源——然后它被漏掉了。
3. **编造业务规则**：模型很热心地写出需求文档里根本没有的比例、阈值、时限。

本技能用固定流水线、冻结的映射矩阵、机械校验脚本和 9 道质量闸门，逐一堵住这三个口子。

---

## 设计原则

| 原则 | 落地方式 |
|---|---|
| **先特征，后方法** | 18 类特征形态（`index.json`）是**封闭集合**。模型只做分类，不许发明类别。 |
| **映射矩阵冻结** | `references/mapping-matrix.md` 作为系统约束全量注入，不许因为「通常都这么做」改映射。 |
| **图片是一等需求源** | 截图被提取、编号 `img-N`、锚定到引用它的正文段落，并按 8 类必提元素逐条清点。 |
| **分段而非合并** | 五段独立 Prompt，每段产出可独立复核的 JSON。合并会在长输出里丢约束。 |
| **可机械校验** | `scripts/validate-output.py` 自动检查 9 道闸门中的 6 道。 |
| **不编造规则** | 源头没有的一律标 `[待确认]`，并阻塞用例执行直到澄清。 |

---

## 目录结构

```
llm-blackbox-testcase/
├── SKILL.md                        # 入口——7 步工作流（第 0~6 步）
├── index.json                      # 18 类特征形态 + 14 种方法（封闭分类学）
├── LICENSE                         # MIT 许可（deck-library 保留其上游 MIT 许可）
├── prompts/                        # 五段流水线，分次调用
│   ├── 00-asset-inventory.md       #   素材清点 + 文本→图片锚点映射
│   ├── 01-requirement-decompose.md #   原子需求点拆解
│   ├── 02-feature-modeling.md      #   测试点 × 被测对象特征画像
│   ├── 03-method-matching.md       #   特征画像 → 方法矩阵
│   ├── 04-case-generation.md       #   可执行用例 + 覆盖度自检
│   └── system-constraint.md        #   系统提示词（内嵌完整映射矩阵）
├── references/
│   ├── feature-taxonomy.md         # 18 类特征详解，按 6 大类组织
│   ├── mapping-matrix.md           # 特征 → 方法映射，含少样本判断范式
│   ├── method-catalog.md           # 14 种黑盒方法：适用条件、步骤、产出、优缺点
│   ├── image-extraction.md         # 取图规范：各载体格式、锚点定位、8 类必提元素
│   └── quality-gates.md            # 9 道闸门与通过标准
├── scripts/
│   ├── extract_images.py           # 一键取图 → images/ + manifest.json（--also-text 一并导出正文）
│   ├── validate-output.py          # 对每段 JSON 产物做机械校验（含矩阵硬校验与 --stage all 四段连校验）
│   └── render_report.py            # 把 step1~4 JSON 装配成单文件 HTML 报告
└── templates/
    ├── report-template.html        # 默认长文档报告骨架（blue-professional）
    ├── TEMPLATE-GUIDE.md           # 视觉模板选型与改造手册
    └── deck-library/               # 34 套完整视觉系统（MIT，来源见文末）
```

---

## 工作流

```
第 0 步 素材清点 ──► 第 1 步 问业务域/范围/模板 ──► 第 1.5 步 定视觉模板
                                                        │
第 6 步 交付 ◄── 第 5 步 全量生成 ◄── 第 4 步 样例确认 ◄── 第 2~3 步 建模与方法匹配
```

### 第 0 步 — 素材清点（素材含图时不可跳过）

需求文档里的图承载了正文没写的信息。一句「字段如图所示」就让截图成了**唯一**需求源。

```bash
# --also-text 一并导出正文（含 [IMG img-N] 标记），并给每张图附上前后正文段落
python3 scripts/extract_images.py 需求.docx --out ./assets --also-text
```

产出 `images/`、`manifest.json` 与 `<素材名>-正文.txt`。docx / pptx 会在 manifest 里给每张图写入
`前一正文段落` / `后一正文段落`——「如图所示」这类措辞就靠它锚定到具体图号，锚定依据不再是"猜顺序"。
（docx/pptx/xlsx/pdf 优先用本脚本取图；office 类工具的 `open_file --image_dir` 在部分素材上会产出空目录。）

随后 `prompts/00-asset-inventory.md` 对**每张**图按 8 类必提元素逐条清点：

1. 字段名 + 必输标记
2. 按钮 + 位置
3. 列表列名
4. 查询条件
5. 分页参数
6. 状态列取值
7. 弹窗 / 提示文案
8. 校验提示

正文里每处「如图所示」都必须锚定到具体 `img-N`。锚不上的写进 `gaps[]`，等级为**硬缺口**——绝不静默丢弃。

> 促成这一步的真实数据：某份 19 条需求点的文档里，10 条引用截图、5 条是**纯图需求**；状态机的关键分支「直接上架」按钮**只存在于截图里**。

### 第 1 步 — 问三个问题

业务域（决定规则正确性）、覆盖粒度（决定产出体量）、报告调性（决定视觉）。这三件事不要猜。

### 第 1.5 步 — 定报告视觉模板

从 `templates/deck-library/` 的 34 套完整设计系统里挑，匹配字段为 `mood` / `tone` / `formality` / `density` / `scheme`。测试报告首看 `density: high`——表格太密。

两种产出形态：

- **形态 A — 长文档报告**（默认）：`report-template.html` 骨架 + 选定模板的设计系统。
- **形态 B — 幻灯片 deck**：整目录复制 `templates/deck-library/templates/<slug>/`，逐页替换内容。

### 第 2 步 — 识别特征形态

把每个需求环节对照 `index.json` 的 18 类 `signals` 做初筛。这一步只定性不定量，目的是圈出会涉及哪几类特征。

### 第 3 步 — 跑五段 Prompt

每段产出 JSON，独立校验：

```bash
python3 scripts/validate-output.py step1.json --stage require   --manifest ./assets/manifest.json
python3 scripts/validate-output.py step2.json --stage feature
python3 scripts/validate-output.py step3.json --stage method
python3 scripts/validate-output.py step4.json --stage case      # 展开到可执行用例时才跑
```

四段产物齐了以后，再跑一次四段连校验（跨段一致性）：

```bash
python3 scripts/validate-output.py --stage all --dir .
```

自动发现 `asset-inventory.json / step1~4.json / assets/manifest.json`，额外检查单段模式查不到的问题：① step3/step4 引用的需求点必须能回溯到 step1；② 用例的测试点必须能对上 step3 同需求点下的测试点（归一化前缀 + 子序列宽松匹配，缩写改写不算失配）；③ 标 `待确认:true` 的需求点必须把 `[待确认]` 传导到用例预期里。

闸门 ⑨（图片证据闭环）在 `--stage require` 时是**硬性门禁**：正文引用图的段落必须有合法 `img-N` 与 ≥ 2 条提取元素，且不得出现「若干」「一些」这类概述词。

### 第 4 步 — 拿一两个需求点做样例

不要一口气全量生成。挑**特征形态差异最大**的两个需求点（比如一个连续区间型 + 一个组合爆炸型），完整跑通，交给用户确认。

### 第 5 步 — 全量生成

产出映射表、用例集、覆盖度报告、素材清点说明。

### 第 6 步 — 交付

输出到**用户当前工作区**（不要写回技能目录），用 `present_files` 打开成品。

---

## 特征形态分类学（18 类）

**输入特征** —— `F1` 连续数值区间 · `F2` 离散枚举/集合 · `F3` 精度/步长/格式 · `F4` 动态阈值 · `F15` 语法/协议输入 · `F16` 随机/超大输入域

**逻辑特征** —— `F5` 布尔条件组合 · `F6` 条件间强约束 · `F7` 分段/阶梯规则 · `F8` 优先级/仲裁

**组合特征** —— `F9` 参数组合爆炸

**行为特征** —— `F10` 状态迁移 · `F11` 流程场景 · `F12` 时序与并发 · `F18` 跨功能端到端

**计算特征** —— `F13` 数值计算 · `F14` 数据依赖/幂等

**经验特征** —— `F17` 无规则经验型

---

## 黑盒方法目录（14 种）

等价类划分 · 边界值分析 · 判定表法 · 因果图法 · 状态迁移测试 · 场景法 · 正交试验设计 · 成对测试 Pairwise · 分类树法 · 错误推测法 · 语法测试 · 随机测试 · 探索性测试 · 规格说明/检查表法

每种方法的定位、适用条件、执行步骤、产出物、优缺点与证券行业实例，见 `references/method-catalog.md`。

方法之间是**四层叠加**，不是多选一：

1. **分域** —— 等价类划分打底，铺骨架。
2. **组合** —— 判定表 / 因果图 / 正交 / Pairwise 处理多条件多参数空间。
3. **加密** —— 边界值在上点、离点、内点取数据。
4. **补漏** —— 错误推测与探索性测试覆盖幂等、并发、超时、重放。

主方法与辅助方法不得覆盖同一批数据。判定表里的「价格合法」是个布尔值，边界值问的是 10.20 与 10.21 的差别。

---

## 质量闸门（9 道）

| # | 闸门 | 自动检查 |
|---|---|---|
| ① | 可追溯性——每条测试点都能回溯到需求原文 | 是 |
| ② | 无编造——不自行补充阈值、比例 | 人工 |
| ③ | 特征类型完备——至少命中 3 类，单一类占比 ≤ 70% | 是 |
| ④ | 方法匹配合理——选择理由不得是「常用方法」 | 是 |
| ⑤ | 降维有损失说明——组合总数 / 降维后数量 / 覆盖率 / 舍弃清单 | 是 |
| ⑥ | 边界完整性——上点、内点、离点三层齐全 | 是 |
| ⑦ | 无效域占比 ≥ 30% | 是 |
| ⑧ | 预期结果可判定——禁止「应该正常」 | 是 |
| ⑨ | 图片证据闭环 | 是（硬性） |

**通过**：①⑤⑥⑦⑧⑨ 全过，②③④ 人工复核无疑义。
**打回**：任一硬性闸门不过，或出现「全部推荐等价类 + 边界值」。

阈值可校准——30% 无效域占比是经验起点，不是铁律。纯校验类功能可提到 50%，纯展示类可降到 20%。

---

## 快速开始

```bash
# 1. 从源文档取图（--also-text 一并导出正文与前后段落）
python3 scripts/extract_images.py 需求.docx --out ./assets --also-text

# 2. 跑 prompts/00-asset-inventory.md，然后校验
python3 scripts/validate-output.py asset-inventory.json \
    --stage inventory --manifest ./assets/manifest.json

# 3. 依次跑 prompts 01 → 04，每段各自校验
python3 scripts/validate-output.py step1.json --stage require --manifest ./assets/manifest.json
python3 scripts/validate-output.py step2.json --stage feature
python3 scripts/validate-output.py step3.json --stage method
python3 scripts/validate-output.py step4.json --stage case

# 3.5 四段连校验（产物齐了以后跑一次）
python3 scripts/validate-output.py --stage all --dir .

# 4. 一键装配报告（指标与闸门结论由脚本实算/实跑，不用手填）
python3 scripts/render_report.py --dir . --out 报告.html --title "需求名" \
    --business-domain "业务域" \
    --inventory asset-inventory.json --manifest assets/manifest.json --embed-images
```

`--stage method` 会按 `references/mapping-matrix.md` 硬校验主方法（如 F10 状态机必须用状态迁移测试，
用判定表会被判不通过）；`--stage require --strict-degrade` 可把「引用 [图不清] 元素却未标待确认」
从告警升级为硬性不通过。

在对话里触发本技能：「生成测试用例」「把这个需求拆成测试点」「用等价类/边界值/判定表/正交法设计用例」。

---

## 环境要求

- **Python 3.x**，仅用标准库。无第三方依赖，无网络。
- **PDF 抽图**需要系统有 `pdftoppm`。缺失时自动降级为「按页登记」，并记入 `gaps[]`，不会崩。
- **Windows** 下若 `python3` 不存在，先用 `where python`（或 `py -3 -c "import sys;print(sys.executable)"`）探测解释器，再用得到的绝对路径调用。**不要写死某台机器的路径**。

---

## 扩展规则

新增特征形态 → 改 `index.json`、`references/feature-taxonomy.md`、`references/mapping-matrix.md`，以及 `scripts/validate-output.py` 的 `FEATURE_TYPES` 枚举，最后更新 `feature_count`。

新增黑盒方法 → 先写入 `references/method-catalog.md`，再进映射矩阵，最后补 `METHODS` 枚举。

新增素材格式 → 在 `scripts/extract_images.py` 的 `ZIP_MEDIA_DIRS` 加目录映射，并同步 `references/image-extraction.md` §1.2 的格式表。

分类学没覆盖的形态**不要硬归类**，标为「新特征候选」并显式提出补充建议。

---

## 致谢与许可

- 本仓库以 **MIT 许可**发布——见 [`LICENSE`](LICENSE)。
- `templates/deck-library/` 目录（34 套 HTML 视觉系统）是 [beautiful-html-templates](https://github.com/zarazhangrui/beautiful-html-templates) 的副本，作者 **Zara Zhang**，按 MIT 许可使用。其原始许可文本原样保留在 `templates/deck-library/LICENSE`，仅适用于该目录。本仓库其余部分（工作流、prompts、分类学、脚本与 `templates/TEMPLATE-GUIDE.md`）均为原创。
- 方法描述遵循既有的黑盒测试实践（与 ISTQB 对齐），不取自任何单一受版权保护的来源。
