# llm-blackbox-testcase

**English** | [中文](README.zh-CN.md)

An agent skill that turns a requirements document into a traceable black-box test-design report — using an LLM, but without letting the LLM improvise.

The core idea: **don't ask "which technique should we use," ask "which feature class does the object under test belong to."** Once the feature class is fixed, the black-box technique becomes a *deduction*, not a choice. The model is executing a lookup table, not guessing from experience.

---

## Why this exists

Ask an LLM to "generate test cases" and you get three predictable failure modes:

1. **Normalization laziness.** Every test point becomes "valid range" and every technique becomes "equivalence partitioning + boundary value analysis."
2. **Silent image loss.** Requirements docs say "fields as shown below." The screenshot is the *only* source of truth for those fields, buttons, and states — and it gets dropped.
3. **Invented business rules.** The model helpfully writes thresholds, ratios, and deadlines that appear nowhere in the source.

This skill attacks all three with a fixed pipeline, a frozen mapping matrix, a mechanical validator, and nine quality gates.

---

## Design principles

| Principle | What it means in practice |
|---|---|
| **Feature-first, not technique-first** | 18 feature classes (`index.json`) are a *closed* set. The model classifies, it does not invent categories. |
| **Frozen mapping matrix** | `references/mapping-matrix.md` is injected as a system constraint. The model may not pick a technique "because it's usually done that way." |
| **Images are first-class requirements** | Screenshots are extracted, numbered `img-N`, anchored to the prose that references them, and their elements extracted into 8 mandatory categories. |
| **Staged, not monolithic** | Five separate prompts, each producing an independently checkable JSON artifact. Merging them loses constraints in long outputs. |
| **Mechanically verifiable** | `scripts/validate-output.py` checks 6 of the 9 quality gates automatically. |
| **No fabricated rules** | Anything not in the source is marked `[待确认]` and blocks case execution until resolved. |

---

## Repository layout

```
llm-blackbox-testcase/
├── SKILL.md                        # Entry point — the 7-step workflow (0–6)
├── index.json                      # 18 feature classes + 14 methods (the closed taxonomy)
├── LICENSE                         # MIT (deck-library keeps its own upstream MIT license)
├── prompts/                        # Five-stage pipeline, run separately
│   ├── 00-asset-inventory.md       #   Asset inventory + text→image anchoring
│   ├── 01-requirement-decompose.md #   Atomic requirement points
│   ├── 02-feature-modeling.md      #   Test point × object-under-test feature profile
│   ├── 03-method-matching.md       #   Feature profile → technique matrix
│   ├── 04-case-generation.md       #   Executable cases + coverage self-check
│   └── system-constraint.md        #   System prompt (embeds the full mapping matrix)
├── references/
│   ├── feature-taxonomy.md         # 18 classes in depth, organized into 6 families
│   ├── mapping-matrix.md           # Feature → technique, with few-shot reasoning patterns
│   ├── method-catalog.md           # 14 black-box techniques: conditions, steps, outputs, pros/cons
│   ├── image-extraction.md         # Image extraction spec: formats, anchoring, 8 element classes
│   └── quality-gates.md            # The 9 gates and pass criteria
├── scripts/
│   ├── extract_images.py           # Image unpacker → images/ + manifest.json (--also-text: prose too)
│   ├── validate-output.py          # Mechanical validator for every JSON artifact (+ matrix check, --stage all cross-stage check)
│   └── render_report.py            # Assembles step1–4 JSON into a single-file HTML report
└── templates/
    ├── report-template.html        # Default long-form report skeleton (blue-professional)
    ├── TEMPLATE-GUIDE.md           # How to pick and adapt a visual system
    └── deck-library/               # 34 complete visual systems (MIT, upstream: see below)
```

---

## The workflow

```
Step 0  Asset inventory ──► Step 1  Ask domain/scope/template ──► Step 1.5  Pick visual system
                                                                          │
Step 6  Deliver ◄── Step 5  Full run ◄── Step 4  Sample confirm ◄── Steps 2–3  Model & match
```

### Step 0 — Asset inventory (mandatory when images are present)

Images in requirements docs carry information the prose does not. A paragraph saying "fields as shown below" makes the screenshot the *only* requirement source.

```bash
# --also-text also dumps the prose (with [IMG img-N] markers) and, for docx/pptx,
# attaches the preceding/following paragraph to every image — the direct evidence
# for anchoring "as shown below" to a concrete img-N.
python3 scripts/extract_images.py requirement.docx --out ./assets --also-text
```

This produces `images/` plus `manifest.json`. Then `prompts/00-asset-inventory.md` extracts, for **every** figure, eight mandatory element classes:

1. Field names + required markers
2. Buttons + position
3. List column headers
4. Query conditions
5. Pagination parameters
6. Status column values
7. Dialog / toast copy
8. Validation messages

Every phrase like "as shown below" must be anchored to a concrete `img-N`. Anything that can't be anchored goes into `gaps[]` as a **hard gap** — never silently dropped.

> Real-world data point that motivated this step: in one 19-point requirements doc, 10 points referenced screenshots and 5 were *pure image* requirements. The key state-machine branch — the **Publish Directly** button — existed only in a screenshot.

### Step 1 — Ask three questions

Domain knowledge (for rule correctness), scope (for output volume), and visual tone (for the report). Never guess these.

### Step 1.5 — Choose the report's visual system

Pick from 34 complete design systems in `templates/deck-library/`, using `mood` / `tone` / `formality` / `density` / `scheme`. For test reports, `density: high` matters most — tables are dense.

Two output shapes:

- **Shape A — long-form report** (default): `report-template.html` skeleton + the chosen template's design system.
- **Shape B — slide deck**: copy the whole `templates/deck-library/templates/<slug>/` directory and replace page by page.

### Step 2 — Classify feature shape

Match each requirement segment against the 18 classes in `index.json` via their `signals`. This step is qualitative only — it scopes which classes are in play.

### Step 3 — Run the five prompts

Each stage produces JSON, validated independently:

```bash
python3 scripts/validate-output.py step1.json --stage require   --manifest ./assets/manifest.json
python3 scripts/validate-output.py step2.json --stage feature
python3 scripts/validate-output.py step3.json --stage method
python3 scripts/validate-output.py step4.json --stage case      # only when expanding to executable cases
```

Once all stages exist, run the full-chain check (cross-stage consistency):

```bash
python3 scripts/validate-output.py --stage all --dir .
```

It auto-discovers `asset-inventory.json / step1~4.json / assets/manifest.json` and additionally checks what single-stage mode cannot: ① every requirement id referenced by step3/step4 must trace back to step1; ② every case's test point must match some step3 test point under the same requirement (normalized prefix + subsequence matching — abbreviated renaming is tolerated); ③ `[待确认]` requirement points must have the flag carried into their cases' expected results.

Gate ⑨ (image evidence closure) is a **hard gate** at `--stage require`: prose that references a figure must have a valid `img-N` and at least two extracted elements, with no words like "several" or "some."

### Step 4 — Prove it on one or two requirement points

Don't generate everything at once. Pick the two requirement points with the **most divergent feature shapes** (e.g. one continuous-range, one combinatorial-explosion), run them end to end, and show the user.

### Step 5 — Full run

Produces the mapping table, the case set, the coverage report, and the asset-inventory statement.

### Step 6 — Deliver

Output to the user's workspace (never back into the skill directory) and open it with `present_files`.

---

## Feature taxonomy (18 classes)

**Input features** — `F1` continuous numeric range · `F2` discrete enumeration · `F3` precision/step/format · `F4` dynamic threshold · `F15` syntax/protocol input · `F16` random/large domain

**Logical features** — `F5` boolean condition combination · `F6` constrained conditions · `F7` tiered/stepped rules · `F8` priority/arbitration

**Combinatorial features** — `F9` parameter combinatorial explosion

**Behavioral features** — `F10` state transition · `F11` flow scenario · `F12` temporal/concurrency · `F18` cross-functional end-to-end

**Computational features** — `F13` numeric computation · `F14` data dependency/idempotence

**Experience features** — `F17` no-rule / experience-driven

---

## Method catalog (14 techniques)

Equivalence class partitioning · Boundary value analysis · Decision table testing · Cause-effect graphing · State transition testing · Scenario testing · Orthogonal array testing · Pairwise testing · Classification tree method · Error guessing · Syntax testing · Random testing · Exploratory testing · Specification-based checklist

Each has a documented position, applicability, procedure, deliverable, pros/cons, and a worked securities-industry example in `references/method-catalog.md`.

The techniques compose in **four layers**, not as alternatives:

1. **Partition** — equivalence classes lay the skeleton.
2. **Combine** — decision tables / cause-effect / orthogonal / pairwise handle multi-condition and multi-parameter space.
3. **Densify** — boundary value analysis probes on-point, off-point, in-point.
4. **Patch** — error guessing and exploratory testing cover idempotence, concurrency, timeouts, replay.

Primary and secondary techniques must not cover the same data batch. A decision table's "price is valid" is a boolean; boundary value analysis asks about the difference between 10.20 and 10.21.

---

## Quality gates (9)

| # | Gate | Automated |
|---|---|---|
| ① | Traceability — every test point maps back to source text | ✅ |
| ② | No fabrication — no thresholds or ratios invented | manual |
| ③ | Feature type completeness — at least 3 classes hit, no single class > 70% | ✅ |
| ④ | Sound technique matching — no "commonly used" reasoning | ✅ |
| ⑤ | Dimensionality reduction has loss statement | ✅ |
| ⑥ | Boundary completeness — on-point, in-point, off-point all present | ✅ |
| ⑦ | Invalid-domain ratio ≥ 30% | ✅ |
| ⑧ | Expected results must be decidable — no "should work normally" | ✅ |
| ⑨ | Image evidence closure | ✅ (hard gate) |

**Pass:** ①⑤⑥⑦⑧⑨ pass and ②③④ clear manual review.
**Rejected:** any hard gate fails, or all test points recommend "equivalence class + boundary value."

Thresholds are calibratable — the 30% invalid-domain ratio is a starting point, not gospel.

---

## Quick start

```bash
# 1. Unpack images from the source document (--also-text dumps the prose too)
python3 scripts/extract_images.py requirement.docx --out ./assets --also-text

# 2. Run prompts/00-asset-inventory.md, then validate
python3 scripts/validate-output.py asset-inventory.json \
    --stage inventory --manifest ./assets/manifest.json

# 3. Continue through prompts 01 → 04, validating each stage
python3 scripts/validate-output.py step1.json --stage require --manifest ./assets/manifest.json
python3 scripts/validate-output.py step2.json --stage feature
python3 scripts/validate-output.py step3.json --stage method
python3 scripts/validate-output.py step4.json --stage case

# 3.5 Full-chain cross-stage check (run once all artifacts exist)
python3 scripts/validate-output.py --stage all --dir .

# 4. Assemble the report (metrics and gate results are computed by the script)
python3 scripts/render_report.py --dir . --out report.html --title "My feature" \
    --business-domain "Domain" \
    --inventory asset-inventory.json --manifest assets/manifest.json --embed-images
```

`--stage method` enforces the mapping matrix (e.g. F10 state-transition must use state transition
testing, a decision table is rejected). `--stage require --strict-degrade` escalates
"[figure unclear] referenced but not marked 待确认" from a warning to a hard failure.

Then invoke the skill in conversation: *"generate test cases,"* *"design test points from this requirement,"* *"apply equivalence class / boundary value / decision table / pairwise to this spec."*

---

## Requirements

- **Python 3.x**, standard library only. No third-party packages, no network access.
- **PDF image extraction** additionally needs `pdftoppm`. When absent, the script degrades gracefully to page-level registration and records the gap in `gaps[]`.
- On Windows, if `python3` is unavailable, resolve the interpreter first with `where python` (or `py -3 -c "import sys;print(sys.executable)"`) and use that absolute path. Never hard-code a machine-specific path.

---

## Extending

New feature class → add to `index.json`, `references/feature-taxonomy.md`, `references/mapping-matrix.md`, and the `FEATURE_TYPES` enum in `scripts/validate-output.py`. Then bump `feature_count`.

New technique → add to `references/method-catalog.md` first, then the mapping matrix, then the `METHODS` enum.

New asset format → add a directory mapping to `ZIP_MEDIA_DIRS` in `scripts/extract_images.py` and update the format table in `references/image-extraction.md` §1.2.

Do **not** hard-classify a shape the taxonomy doesn't cover. Mark it "new feature candidate" and propose the addition explicitly.

---

## Credits & license

- This repository is released under the **MIT License** — see [`LICENSE`](LICENSE).
- The `templates/deck-library/` directory (34 HTML visual systems) is a vendored copy of [beautiful-html-templates](https://github.com/zarazhangrui/beautiful-html-templates) by **Zara Zhang**, used under the MIT License. Its original license text is kept verbatim at `templates/deck-library/LICENSE` and applies to that directory only. Everything else in this repository — the workflow, prompts, taxonomy, scripts and `templates/TEMPLATE-GUIDE.md` — is original to this skill.
- Method descriptions follow established black-box testing practice (ISTQB-aligned) and are not derived from any single copyrighted source.
