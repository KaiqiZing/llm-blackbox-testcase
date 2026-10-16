#!/usr/bin/env python3
"""
validate-output.py — llm-blackbox-testcase 输出校验脚本

对四段 Prompt 的 JSON 产物做机械校验，对应 references/quality-gates.md 的 9 道闸门。
只读取入参指定的 JSON 文件，打印校验报告到 stdout。无网络、无第三方依赖、
不读写除入参外的任何文件。

用法：
  python3 validate-output.py <产物.json> --stage inventory # 校验 Prompt 0 产物（素材清点）
  python3 validate-output.py <产物.json> --stage require   # 校验 Prompt 1 产物（需求点清单）
  python3 validate-output.py <产物.json> --stage feature   # 校验 Prompt 2 产物（特征画像）
  python3 validate-output.py <产物.json> --stage method    # 校验 Prompt 3 产物（方法矩阵 JSON 形式）
  python3 validate-output.py <产物.json> --stage case      # 校验 Prompt 4 产物（用例集）

四段连校验（自动发现 asset-inventory.json / step1~4.json / assets/manifest.json）：
  python3 validate-output.py --stage all --dir .
  除逐段校验外，还会做跨段一致性检查：
    ① step3 引用的需求点必须存在于 step1（防止方法矩阵凭空出现需求点）
    ② step4 引用的需求点必须存在于 step1；测试点须能对应到 step3（宽松匹配，不一致仅告警）
    ③ step1 标待确认的需求点，其用例预期应至少一条带 [待确认]（待确认要传导到用例层）

闸门⑨（图片证据闭环）可选参数：
  --manifest  <manifest.json>         由 scripts/extract_images.py 产出
  --inventory <asset-inventory.json>  由 prompts/00-asset-inventory.md 产出
  两者都不提供时，闸门⑨ 跳过并说明原因。

退出码：0 = 全部通过；1 = 存在硬性闸门不通过。
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

# ---- 合法枚举（与 index.json 保持一致，扩展分类学时同步更新）----
FEATURE_TYPES = {
    "F1": "连续数值区间", "F2": "离散枚举/集合", "F3": "精度/步长/格式",
    "F4": "动态阈值", "F5": "布尔条件组合", "F6": "条件间强约束",
    "F7": "分段/阶梯规则", "F8": "优先级/仲裁", "F9": "参数组合爆炸",
    "F10": "状态迁移", "F11": "流程场景", "F12": "时序与并发",
    "F13": "数值计算", "F14": "数据依赖/幂等", "F15": "语法/协议输入",
    "F16": "随机/超大输入域", "F17": "无规则经验型", "F18": "跨功能端到端",
}
# 前 14 项与 index.json 的 methods[].name 逐一对应（规范名）；
# 末尾三项是同一方法的常见别名，仅为容错匹配，不计入 method_count。
METHODS = {
    "等价类划分", "边界值分析", "判定表法", "因果图法", "状态迁移测试",
    "场景法", "正交试验设计", "成对测试 Pairwise", "分类树法",
    "错误推测法", "语法测试", "随机测试", "探索性测试", "规格说明/检查表法",
    # 别名（非规范名）
    "成对测试", "Pairwise", "All-Pairs",
}
COMBO_SCALE_DEFAULT = 20
INVALID_RATIO_DEFAULT = 0.30

# 质量闸门 ④ · 映射矩阵：特征形态 -> 主方法 / 辅助方法（references/mapping-matrix.md 第一节）
# 这是「不凭习惯选方法」的机器化版本：-method 阶段逐行硬校验主方法是否命中矩阵。
# 修改本表必须同步 references/mapping-matrix.md，两处必须一致。
MATRIX_PRIMARY = {
    "F1": "等价类划分", "F2": "等价类划分", "F3": "边界值分析", "F4": "边界值分析",
    "F5": "判定表法", "F6": "因果图法", "F7": "等价类划分", "F8": "判定表法",
    "F9": "正交试验设计", "F10": "状态迁移测试", "F11": "场景法", "F12": "场景法",
    "F13": "边界值分析", "F14": "错误推测法", "F15": "语法测试", "F16": "随机测试",
    "F17": "错误推测法", "F18": "场景法",
}
MATRIX_SECONDARY = {
    "F1": "边界值分析", "F2": "错误推测法", "F3": "错误推测法", "F4": "等价类划分",
    "F5": "因果图法", "F6": "判定表法", "F7": "边界值分析", "F8": "场景法",
    "F9": "成对测试 Pairwise", "F10": "场景法", "F11": "错误推测法", "F12": "错误推测法",
    "F13": "等价类划分", "F14": "场景法", "F15": "等价类划分", "F16": "等价类划分",
    "F17": "探索性测试", "F18": "状态迁移测试",
}

# 质量闸门 ④：选择理由空话模式
EMPTY_REASON = re.compile(r"常用|通常|确保覆盖|比较保险|一般来说|保险起见")
# 质量闸门 ⑧：预期结果不可判定禁词
VAGUE_EXPECT = re.compile(r"应该正常|提示错误|符合预期|正确处理|正常返回|成功处理|正常提示")

# 质量闸门 ⑨：正文引用图片的措辞（命中即说明段落信息依赖某张图）
# 覆盖 如图所示/如下图/见下图/如左图所示/如图 1 所示/图 3-1 所示/按下图/如下截图/
# 如下表/见附表/界面上如下 等常见写法；用负向断言排除「例如图片」「地图」「图表」类误报。
IMAGE_REF_PHRASE = re.compile(
    r"(?<![例比诸譬])如(?:下|上|左|右)?图[\s\d\-\.、,，:：]{0,8}(?:所示)?"
    r"|(?:详见|参见|参考|参照|见)[上下左右附]?列?图"
    r"|按[上下左右附]?图"
    r"|图[\s\d\-\.]{0,6}所示"
    r"|如下[表列]|见下[表列]|见附[表图]"
    r"|截图(?:所示)?|界面上?如下"
)
# 质量闸门 ⑨：提取元素里的概述词（等于没看图）
VAGUE_ELEMENT = re.compile(r"若干|一些|等等|某些")
# 质量闸门 ⑨：合法图号形态
IMG_ID_RE = re.compile(r"^img-\d+$")
# 质量闸门 ⑨：提取元素最少条数
MIN_ELEMENTS = 2


class Report:
    def __init__(self):
        self.errors = []   # 硬性闸门不通过
        self.warnings = []  # 告警
        self.infos = []

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def info(self, msg):
        self.infos.append(msg)

    def dump(self):
        print("=" * 60)
        print("校验报告")
        print("=" * 60)
        for m in self.errors:
            print(f"  [不通过] {m}")
        for m in self.warnings:
            print(f"  [告警]   {m}")
        for m in self.infos:
            print(f"  [通过]   {m}")
        print("-" * 60)
        print(f"硬性不通过 {len(self.errors)} 项；告警 {len(self.warnings)} 项")
        return 1 if self.errors else 0


def load_items(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"读取文件失败: {e}")
        sys.exit(1)
    if isinstance(data, dict):
        for key in ("items", "data", "测试点", "需求点", "用例"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]
    if isinstance(data, list):
        return data
    print("JSON 顶层必须是数组或包含数组的对象")
    sys.exit(1)


def load_manifest_ids(path):
    """从 manifest.json 读合法图号集合；读不出返回 None（表示无法校验）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    ids = set()
    for key in ("images", "图片", "items"):
        arr = data.get(key) if isinstance(data, dict) else None
        if isinstance(arr, list):
            for r in arr:
                if isinstance(r, dict):
                    i = r.get("图号") or r.get("id")
                    if i:
                        ids.add(str(i).strip())
    return ids


def check_image_closure(items, rep, manifest_ids=None, require_images=None):
    """闸门⑨ 图片证据闭环。require_images 为 None 时按素材清单自动判定。"""
    if require_images is None and manifest_ids is None:
        rep.info("闸门⑨ 图片证据闭环：未提供 manifest.json/asset-inventory.json，跳过")
        return

    ref_items = []       # 有引用措辞的需求点
    img_items = []       # 有图片依据的需求点
    used_ids = set()
    legacy_n = 0         # 旧格式产物条数

    for i, it in enumerate(items):
        label = it.get("id", it.get("需求点", f"第{i+1}条"))
        text_basis = str(it.get("文本依据", it.get("原文依据", "")))
        is_legacy = "原文依据" in it and "图片依据" not in it
        img_basis = it.get("图片依据")

        hit_phrase = IMAGE_REF_PHRASE.search(text_basis)
        if hit_phrase:
            ref_items.append((label, hit_phrase.group(0)))

        # 老格式产物：只有 原文依据，没有 图片依据
        if is_legacy:
            legacy_n += 1
            if hit_phrase:
                rep.warn(f"闸门⑨ 未升级产物（{label}）：正文含「{hit_phrase.group(0)}」"
                         f"但字段仍是旧的『原文依据』，图片证据未结构化。"
                         f"应按 Prompt 1 契约拆成『文本依据 + 图片依据』")
            continue

        if img_basis is None:
            continue

        if not isinstance(img_basis, list):
            rep.err(f"闸门⑨ 图片依据必须是数组（{label}）：得到 {type(img_basis).__name__}")
            continue

        if img_basis:
            img_items.append(label)

        # 有引用措辞却无图片依据 → 硬性不通过
        if hit_phrase and not img_basis:
            rep.err(f"闸门⑨ 图片证据断链（{label}）：正文含「{hit_phrase.group(0)}」，"
                    f"但『图片依据』为空——该段需求的图没有被锚定")

        for k, b in enumerate(img_basis):
            if not isinstance(b, dict):
                rep.err(f"闸门⑨ 图片依据[{k}] 不是对象（{label}）")
                continue
            gid = str(b.get("图号", "")).strip()
            if not IMG_ID_RE.match(gid):
                rep.err(f"闸门⑨ 图号非法（{label}）：「{gid}」应形如 img-N，"
                        f"且必须来自 manifest.json")
            else:
                used_ids.add(gid)
                if manifest_ids is not None and gid not in manifest_ids:
                    rep.err(f"闸门⑨ 图号不存在于素材清单（{label}）：{gid}，"
                            f"清单内为 {sorted(manifest_ids)}")

            if not str(b.get("引用措辞", "")).strip():
                rep.warn(f"闸门⑨ 缺『引用措辞』（{label} / {gid}）：无法回溯这段话原本怎么提的图")

            elems = b.get("提取元素", [])
            if not isinstance(elems, list):
                rep.err(f"闸门⑨ 『提取元素』必须是数组（{label} / {gid}）")
                continue
            if len(elems) < MIN_ELEMENTS:
                rep.err(f"闸门⑨ 提取元素仅 {len(elems)} 条（{label} / {gid}）："
                        f"少于 {MIN_ELEMENTS} 条视为概述，未按八类清单逐条清点")
            vague = [e for e in elems if VAGUE_ELEMENT.search(str(e))]
            if vague:
                rep.err(f"闸门⑨ 提取元素含概述词（{label} / {gid}）：{vague[:2]}——没有真正看图；"
                        f"八类清单见 references/image-extraction.md §三")

    # 有图无引用：清单里存在但没有任何需求点用上
    if manifest_ids:
        unused = sorted(manifest_ids - used_ids)
        if unused and img_items:
            rep.warn(f"闸门⑨ 「有图无引用」：{len(unused)} 张图未被任何需求点引用 {unused}，"
                     f"人工复核是否漏需求（尤其状态机按钮、查询条件、分页上限）")

    if ref_items:
        rep.info(f"闸门⑨ 正文引用图片的段落 {len(ref_items)} 处，"
                 f"已锚定 {len(img_items)} 条需求点带图片依据，涉及图号 {sorted(used_ids)}")
    elif img_items:
        rep.info(f"闸门⑨ 无显式引用措辞，但 {len(img_items)} 条需求点带图片依据，"
                 f"涉及图号 {sorted(used_ids)}")
    elif legacy_n and legacy_n == len(items):
        rep.warn(f"闸门⑨ 本次产物为旧格式（{legacy_n} 条全部使用『原文依据』单一字段）："
                 f"图片需求源未结构化。若素材含图，建议按 Prompt 1 新契约重跑")
    else:
        rep.warn("闸门⑨ 既无引用措辞也无图片依据：若素材确实含图，说明图片需求源未被使用")


EIGHT_CATEGORIES = ("字段", "按钮", "列表列", "查询条件", "分页参数", "状态列", "弹窗文案", "校验提示")


def check_inventory(data, rep, manifest_ids=None):
    """Prompt 0 产物（asset-inventory.json）专用校验。data 为原始 dict。"""
    if not isinstance(data, dict):
        rep.err("素材清点顶层必须是对象，含 assets/image_refs/image_elements/gaps")
        return

    assets = data.get("assets", [])
    refs = data.get("image_refs", [])
    elems = data.get("image_elements", [])
    gaps = data.get("gaps", [])

    if not assets:
        rep.err("素材清点 assets 为空：未登记任何素材单元")
    else:
        img_assets = [a for a in assets if isinstance(a, dict) and a.get("类型") == "图片"]
        no_loc = [a.get("id", "?") for a in assets
                  if isinstance(a, dict) and not str(a.get("位置", "")).strip()]
        if no_loc:
            rep.err(f"素材单元缺『位置』：{no_loc}")
        else:
            rep.info(f"素材单元 {len(assets)} 个（图片 {len(img_assets)} 张）全部登记且有位置")

    # 锚点映射完整性
    if not refs and not elems:
        rep.warn("闸门⑨ 素材清点没有任何锚点映射与图片元素：若素材含图，说明未做锚定")
    for k, r in enumerate(refs):
        if not isinstance(r, dict):
            rep.err(f"image_refs[{k}] 不是对象")
            continue
        label = str(r.get("引用文本段", ""))[:24] or f"第{k+1}条"
        gid = str(r.get("指向图片", "")).strip()
        if not IMG_ID_RE.match(gid):
            rep.err(f"闸门⑨ 锚点图号非法（{label}…）：「{gid}」应形如 img-N")
        elif manifest_ids is not None and gid not in manifest_ids:
            rep.err(f"闸门⑨ 锚点图号不存在于素材清单（{label}…）：{gid}")
        if not str(r.get("锚定依据", "")).strip():
            rep.warn(f"闸门⑨ 锚点缺『锚定依据』（{label}…）：无法复核锚定是否可信")
    if refs:
        rep.info(f"闸门⑨ 锚点映射 {len(refs)} 条，全部指向合法图号"
                 if not any(IMG_ID_RE.match(str(r.get("指向图片", ""))) is None for r in refs if isinstance(r, dict))
                 else "闸门⑨ 锚点映射存在非法图号（见上）")

    # 八类元素清点完整性
    elem_ids = set()
    for k, e in enumerate(elems):
        if not isinstance(e, dict):
            rep.err(f"image_elements[{k}] 不是对象")
            continue
        gid = str(e.get("图片编号", "")).strip()
        elem_ids.add(gid)
        missing = [c for c in EIGHT_CATEGORIES if c not in e]
        if missing:
            rep.err(f"闸门⑨ 图片元素缺类（{gid or f'第{k+1}条'}）：八类清单缺 {missing}")
        total_items = sum(len(v) for c in EIGHT_CATEGORIES
                          for v in [e.get(c)] if isinstance(v, list))
        if total_items < 2:
            rep.err(f"闸门⑨ 图片元素清点仅 {total_items} 条（{gid}）：疑似概述，未按八类清单逐条提取")
        for c in EIGHT_CATEGORIES:
            v = e.get(c)
            if isinstance(v, list):
                vague = [x for x in v if VAGUE_ELEMENT.search(str(x)) and "—" not in str(x)]
                if vague:
                    rep.err(f"闸门⑨ 元素含概述词（{gid} / {c}）：{vague[:2]}")
    if elems:
        rep.info(f"闸门⑨ 八类元素清点 {len(elems)} 张图完成")

    # manifest 里的图是否都做了清点
    if manifest_ids and elems:
        uncleared = sorted(manifest_ids - elem_ids)
        if uncleared:
            rep.warn(f"闸门⑨ 有图未清点：{uncleared} 在 manifest 中存在但没有 image_elements 条目")
        else:
            rep.info("闸门⑨ manifest 全部图片均有八类元素清点")

    # gaps 统计
    hard = [g for g in gaps if isinstance(g, dict)
            and str(g.get("类型", "")) in ("硬缺口", "提取失败", "图文冲突")]
    if hard:
        rep.warn(f"素材清点遗留 {len(hard)} 条硬性缺口，"
                 f"报告中必须声明证据强度降级：{[str(g.get('描述', ''))[:36] for g in hard][:3]}")
    else:
        rep.info("素材清点无硬性缺口")


def check_require(items, rep, manifest_ids=None, require_images=None, strict_degrade=False):
    if not items:
        rep.err("需求点清单为空")
        return
    # 兼容旧字段：原文依据 = 文本依据；也接受两者并存
    def basis_of(it):
        return (str(it.get("文本依据", "")).strip()
                or str(it.get("原文依据", "")).strip())

    no_basis = [it.get("id", "?") for it in items
                if not basis_of(it) and not it.get("图片依据")]
    if no_basis:
        rep.err(f"闸门① 可追溯性：{len(no_basis)} 条需求点缺少任何依据（文本与图片均空）：{no_basis[:5]}")
    else:
        rep.info("闸门① 可追溯性：全部需求点至少有一类依据")
    vague = [it.get("id", "?") for it in items
             if re.search(r"等等|其他|相关|相关功能", str(it.get("需求点", "")))]
    if vague:
        rep.warn(f"拆解完整性：{len(vague)} 条需求点含兜底描述（{vague[:5]}），可能拆解未完成")
    types = Counter(str(it.get("类型", "")) for it in items)
    rep.info(f"需求类型分布：{dict(types)}")
    # 纯图需求点统计（正文无信息量、靠图立起来的需求）
    pure_img = [it.get("id", "?") for it in items
                if not basis_of(it) and it.get("图片依据")]
    if pure_img:
        rep.info(f"纯图需求点 {len(pure_img)} 条（正文无有效描述，证据全部来自图片）：{pure_img}")
    # 闸门⑨ 证据降级闭环：引用了 [图不清] 元素的图片依据，需求点必须标 待确认:true
    blurred = []
    for it in items:
        refs = it.get("图片依据") or []
        if isinstance(refs, dict):
            refs = [refs]
        hit = False
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            elems = ref.get("提取元素") or []
            if isinstance(elems, str):
                elems = [elems]
            for el in elems:
                if "[图不清]" in str(el):
                    hit = True
                    break
            if hit:
                break
        if hit and it.get("待确认") is not True:
            blurred.append(it.get("id", "?"))
    if blurred:
        hint = "处理办法：①标 待确认:true；②把不影响验收标准的 [图不清] 元素移入 gaps，" \
               "并从该需求点的提取元素里摘掉。--strict-degrade 可将此项升级为硬性不通过。"
        if strict_degrade:
            rep.err(f"闸门⑨ 证据降级未声明：{len(blurred)} 条需求点引用了 [图不清] 元素"
                    f"却未标注 待确认:true：{blurred[:5]}；{hint}")
        else:
            rep.warn(f"闸门⑨ 证据降级提示：{len(blurred)} 条需求点引用了 [图不清] 元素"
                     f"但未标注 待确认:true：{blurred[:5]}；{hint}")
    check_image_closure(items, rep, manifest_ids=manifest_ids, require_images=require_images)


def check_feature(items, rep):
    if not items:
        rep.err("特征画像为空")
        return
    ftypes = []
    img_lost = []
    for i, it in enumerate(items):
        ft = str(it.get("特征类型", "")).strip()
        label = it.get("测试点", f"第{i+1}条")
        if ft not in FEATURE_TYPES:
            rep.err(f"特征类型非法：'{ft}'（{label}），必须是 F1~F18")
        else:
            ftypes.append(ft)
        detail = str(it.get("特征详情", "")).strip()
        if len(detail) < 10:
            rep.warn(f"特征详情过短（{label}）：'{detail}'，应写出具体取值/条件/状态/公式")
        if re.search(r"需要合法|应该合理|正常即可", detail):
            rep.warn(f"特征详情是形容词不是数据（{label}）")
        # 闸门⑨：上游有图片依据，本步却把图片证据丢了
        if "图片依据" in it and it.get("图片依据") and not it.get("图片证据"):
            img_lost.append(label)
        evidence = it.get("图片证据", [])
        if isinstance(evidence, list):
            for e in evidence:
                m = re.search(r"img-\d+", str(e))
                if not m:
                    rep.warn(f"闸门⑨ 图片证据未标注图号（{label}）：'{str(e)[:30]}'")
        scale = it.get("组合规模")
        need = it.get("需降维")
        if isinstance(scale, (int, float)) and scale > COMBO_SCALE_DEFAULT:
            if need is not True:
                rep.err(f"闸门⑤ 降维：组合规模 {scale} > {COMBO_SCALE_DEFAULT} 但未标注需降维（{label}）")
            elif not str(it.get("降维目标", "")).strip():
                rep.err(f"闸门⑤ 降维：已标需降维但未给降维目标（{label}）")
    if img_lost:
        rep.err(f"闸门⑨ 图片证据在特征建模环节丢失：{len(img_lost)} 条测试点上游有图片依据，"
                f"但未填写『图片证据』：{img_lost[:5]}")
    elif any(it.get("图片证据") for it in items):
        rep.info("闸门⑨ 图片证据已注入特征画像")
    if ftypes:
        dist = Counter(ftypes)
        top_ft, top_n = dist.most_common(1)[0]
        if top_n / len(ftypes) > 0.7 and len(ftypes) >= 5:
            rep.err(f"闸门③ 特征完备：{FEATURE_TYPES[top_ft]} 占比 {top_n}/{len(ftypes)} > 70%，疑似归一化偷懒")
        else:
            rep.info(f"闸门③ 特征分布：{ {FEATURE_TYPES[k]: v for k, v in dist.items()} }")


def check_method(items, rep):
    if not items:
        rep.err("方法矩阵为空")
        return
    all_eq_bva = True
    for i, it in enumerate(items):
        label = it.get("测试点", f"第{i+1}条")
        methods_raw = str(it.get("推荐黑盒测试方法", it.get("推荐方法", "")))
        if not methods_raw.strip():
            rep.err(f"缺少推荐方法（{label}）")
            continue
        hit = [m for m in METHODS if m in methods_raw]
        if not hit:
            rep.err(f"方法不在合法目录内（{label}）：'{methods_raw}'")
        if set(hit) - {"等价类划分", "边界值分析"}:
            all_eq_bva = False
        reason = str(it.get("选择理由", "")).strip()
        if not reason:
            rep.err(f"缺少选择理由（{label}）")
        elif EMPTY_REASON.search(reason):
            rep.err(f"闸门④ 选择理由是空话（{label}）：'{reason[:40]}'")
        # 闸门④ 映射矩阵：主特征 -> 主方法 必须与矩阵一致
        spec = str(it.get("被测对象特征", it.get("特征类型", "")))
        fm = re.match(r"\s*(F\d+)", spec)
        if fm and fm.group(1) in MATRIX_PRIMARY:
            fid = fm.group(1)
            want_main = MATRIX_PRIMARY[fid]
            mm = re.search(r"([^\s+（(]+?)\s*（主）", methods_raw)
            main = mm.group(1).strip() if mm else None
            if main and main != want_main:
                rep.err(f"闸门④ 映射矩阵冲突：{fid} 的主方法应为『{want_main}』，"
                        f"实际写了『{main}』（{label}）")
            elif not main and want_main not in methods_raw:
                rep.err(f"闸门④ 映射矩阵冲突：{fid} 的方法里应包含『{want_main}』，"
                        f"实际为『{methods_raw}』（{label}）")
            want_sec = MATRIX_SECONDARY.get(fid)
            # 次特征可以合理地顶替主特征的辅助方法（如 F5+次特征F14 用错误推测法代替因果图法），
            # 因此可接受集合 = 主特征辅助方法 ∪ 次特征的主/辅方法。
            accepted = {want_sec} if want_sec else set()
            sm = re.search(r"次特征\s*(F\d+)", spec)
            if sm and sm.group(1) in MATRIX_PRIMARY:
                sub = sm.group(1)
                accepted |= {MATRIX_PRIMARY.get(sub), MATRIX_SECONDARY.get(sub)}
            accepted.discard(None)
            if accepted and not any(a in methods_raw for a in accepted):
                names = " / ".join(sorted(accepted))
                rep.warn(f"矩阵建议：{fid} 的辅助方法通常为『{names}』，当前未出现（{label}）")
        elif not fm:
            rep.warn(f"被测对象特征缺少 F 编号，跳过映射矩阵校验（{label}）：'{spec[:30]}'")

        target = str(it.get("覆盖目标与退出标准", it.get("覆盖目标", ""))).strip()
        if not target:
            rep.warn(f"缺少覆盖目标与退出标准（{label}）")
    if all_eq_bva and len(items) >= 3:
        rep.err("闸门③ 全部测试点都只推荐 等价类+边界值，典型偷懒信号，打回")
    else:
        rep.info("闸门③ 方法分布非单一")


def check_case(items, rep, invalid_ratio=INVALID_RATIO_DEFAULT):
    if not items:
        rep.err("用例集为空")
        return
    invalid_kinds = ("无效", "离点", "异常")
    invalid_n = 0
    vague_n = 0
    boundary_missing = []
    for i, it in enumerate(items):
        label = it.get("用例ID", f"第{i+1}条")
        ctype = str(it.get("用例类型", ""))
        if any(k in ctype for k in invalid_kinds):
            invalid_n += 1
        expect = str(it.get("预期结果", ""))
        if VAGUE_EXPECT.search(expect):
            vague_n += 1
            rep.err(f"闸门⑧ 预期结果不可判定（{label}）：'{expect[:40]}'")
        data = str(it.get("输入数据", ""))
        if re.search(r"任意值|合法值|正常值|有效值$|某个|一些", data):
            rep.warn(f"输入数据不具体（{label}）：'{data[:40]}'")
        tp = str(it.get("测试点", ""))
        if "边界" in ctype:
            boundary_missing.append(tp)
    ratio = invalid_n / len(items)
    if ratio < invalid_ratio:
        rep.err(f"闸门⑦ 无效域占比 {ratio:.0%} < {invalid_ratio:.0%}，只覆盖了正常路径")
    else:
        rep.info(f"闸门⑦ 无效域占比 {ratio:.0%} ≥ {invalid_ratio:.0%}")
    if not any("边界" in str(it.get("用例类型", "")) for it in items):
        rep.warn("闸门⑥ 用例集中没有边界类型用例，检查边界完整性")
    rep.info(f"用例总数 {len(items)}，其中无效/离点/异常 {invalid_n} 条")


def _discover(base):
    """all 模式下自动发现产物文件；返回 (manifest, inventory, {stage: path})。"""
    found = {}
    for cand in (os.path.join(base, "assets", "manifest.json"),
                 os.path.join(base, "manifest.json")):
        if os.path.isfile(cand):
            found["manifest"] = cand
            break
    if os.path.isfile(os.path.join(base, "asset-inventory.json")):
        found["inventory"] = os.path.join(base, "asset-inventory.json")
    stages = {}
    for stage, name in (("require", "step1.json"), ("feature", "step2.json"),
                        ("method", "step3.json"), ("case", "step4.json")):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            stages[stage] = p
    return found.get("manifest"), found.get("inventory"), stages


def _stage_banner(rep, stage, path):
    names = {"inventory": "Prompt 0 素材清点", "require": "Prompt 1 需求点拆解",
             "feature": "Prompt 2 特征建模", "method": "Prompt 3 方法匹配",
             "case": "Prompt 4 用例生成"}
    rep.info(f"—————— {names.get(stage, stage)}（{os.path.basename(path)}） ——————")


def _run_stage(stage, path, rep, args, manifest_ids, skip_inv_gaps=False):
    """跑单个阶段（all 模式复用；解析失败记为硬性不通过而不是直接退出）。

    skip_inv_gaps=True 用于 all 模式：素材清点段已经报过 gaps，
    require 段不再重复报同一批硬性缺口。
    """
    _stage_banner(rep, stage, path)
    if stage == "inventory":
        try:
            with open(path, "r", encoding="utf-8") as f:
                inv = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            rep.err(f"{os.path.basename(path)} 读取/解析失败：{e}")
            return None
        check_inventory(inv, rep, manifest_ids=manifest_ids)
        return inv

    items = None
    try:
        items = load_items(path)
    except SystemExit:
        rep.err(f"{os.path.basename(path)} 加载失败：JSON 无法解析")
        return None
    if stage == "require":
        if args.inventory and not skip_inv_gaps:
            try:
                with open(args.inventory, "r", encoding="utf-8") as f:
                    inv = json.load(f)
                if isinstance(inv, dict):
                    hard = [g for g in inv.get("gaps", [])
                            if isinstance(g, dict) and str(g.get("类型", "")) in
                            ("硬缺口", "提取失败", "图文冲突")]
                    if hard:
                        rep.warn(f"闸门⑨ 素材清点遗留 {len(hard)} 条硬性缺口，"
                                 f"报告中必须声明证据强度降级："
                                 f"{[g.get('描述', '')[:40] for g in hard][:3]}")
            except (OSError, json.JSONDecodeError):
                pass
        check_require(items, rep, manifest_ids=manifest_ids, strict_degrade=args.strict_degrade)
    elif stage == "feature":
        check_feature(items, rep)
    elif stage == "method":
        check_method(items, rep)
    elif stage == "case":
        check_case(items, rep, invalid_ratio=args.invalid_ratio)
    return items


def _tp_match(tp, p):
    """测试点宽松匹配：兼容空格/引号差异与缩写改写。

    规则（任一命中即算匹配）：
    1. 归一化后 12 字符前缀一致（或互为前缀）；
    2. 归一化后一方是另一方的子序列（≥4 字符）——覆盖「新增保存→待上架」
       对「新增保存 → 待上架初始状态」这类缩写命名。
    归一化仅剔除空格与装饰性引号（「」『』"），不动语义字符。
    """
    def norm(s):
        for ch in " \u3000「」『』\"'":
            s = s.replace(ch, "")
        return s

    def subseq(a, b):
        it = iter(b)
        return all(c in it for c in a)

    a, b = norm(tp), norm(p)
    if not a or not b:
        return False
    if a[:12] == b[:12] or a.startswith(b[:12]) or b.startswith(a[:12]):
        return True
    if len(a) >= 4 and subseq(a, b):
        return True
    if len(b) >= 4 and subseq(b, a):
        return True
    return False


def check_cross_stage(s1, s3, s4, rep):
    """跨段一致性：单段模式查不到的问题在这里查。"""
    if not (s1 or s3 or s4):
        return
    rep.info("—————— 跨段一致性 ——————")
    ids1 = {str(r.get("id", "")).strip() for r in (s1 or []) if r.get("id")}

    # ① step3 的需求点必须能在 step1 里找到
    if s1 and s3:
        ghosts = sorted({str(r.get("需求点", "")).strip() for r in s3
                         if r.get("需求点") and str(r.get("需求点", "")).strip() not in ids1})
        if ghosts:
            rep.err(f"方法矩阵引用了 step1 不存在的需求点（凭空出现）：{ghosts[:5]}")
        else:
            rep.info(f"step3 需求点全部可回溯到 step1（{len(ids1)} 个需求点）")

    # ② step4 的需求点必须存在于 step1；测试点应能对上 step3（宽松前缀匹配，仅告警）
    if s1 and s4:
        bad_rids = sorted({str(c.get("需求点", "")).strip() for c in s4
                           if c.get("需求点") and str(c.get("需求点", "")).strip() not in ids1})
        if bad_rids:
            rep.err(f"用例集引用了 step1 不存在的需求点：{bad_rids[:5]}")
    if s3 and s4:
        by_rid = {}
        for r in s3:
            by_rid.setdefault(str(r.get("需求点", "")).strip(), []).append(
                str(r.get("测试点", "")).strip())
        orphans = []
        for c in s4:
            tp = str(c.get("测试点", "")).strip()
            rid = str(c.get("需求点", "")).strip()
            pool = by_rid.get(rid) or []
            if not any(_tp_match(tp, p) for p in pool if tp and p):
                orphans.append(f"{rid}:{tp[:20]}")
        if orphans:
            rep.warn(f"{len(orphans)} 条用例的测试点在 step3 同需求点下找不到对应项"
                     f"（命名不一致或凭空出现，建议统一措辞）：{orphans[:5]}")
        else:
            rep.info(f"step4 用例的测试点全部可回溯到 step3（{len(by_rid)} 个需求点分组）")

    # ③ 待确认闭环：step1 标待确认的需求点，其用例预期里应至少一条带 [待确认]
    if s1 and s4:
        todo_ids = {str(r.get("id", "")).strip() for r in s1 if r.get("待确认") is True}
        if todo_ids:
            unflagged = []
            for rid in sorted(todo_ids):
                cases = [c for c in s4 if str(c.get("需求点", "")).strip() == rid]
                if cases and not any("[待确认]" in str(c.get("预期结果", "")) for c in cases):
                    unflagged.append(rid)
            if unflagged:
                rep.warn(f"{len(unflagged)} 个待确认需求点的用例预期均未标 [待确认]，"
                         f"规则不确定没有传导到用例层：{unflagged[:5]}")
            else:
                rep.info(f"待确认标记已传导到用例层（{len(todo_ids)} 个需求点核对完毕）")


def main():
    ap = argparse.ArgumentParser(description="llm-blackbox-testcase 输出校验")
    ap.add_argument("path", nargs="?", default=None,
                    help="待校验的 JSON 产物路径（--stage all 时可省略，改用 --dir 自动发现）")
    ap.add_argument("--stage", required=True,
                    choices=["inventory", "require", "feature", "method", "case", "all"],
                    help="产物所处阶段：inventory=素材清点 require=需求点 feature=特征画像 "
                         "method=方法矩阵 case=用例集 all=四段连校验+跨段一致性")
    ap.add_argument("--dir", default=".",
                    help="--stage all 时的产物目录（默认当前目录），自动发现 "
                         "asset-inventory.json / step1~4.json / assets/manifest.json")
    ap.add_argument("--invalid-ratio", type=float, default=INVALID_RATIO_DEFAULT,
                    help="无效域占比阈值，默认 0.30")
    ap.add_argument("--manifest", default=None,
                    help="extract_images.py 产出的 manifest.json，用于闸门⑨ 校验图号有效性")
    ap.add_argument("--inventory", default=None,
                    help="Prompt 0 产出的 asset-inventory.json，用于闸门⑨ 校验锚点闭环")
    ap.add_argument("--strict-degrade", action="store_true",
                    help="闸门⑨ 证据降级升级为硬性不通过：引用 [图不清] 元素的需求点必须标 待确认:true")
    args = ap.parse_args()

    # ---- all 模式：四段连校验 + 跨段一致性 ----
    if args.stage == "all":
        base = os.path.abspath(args.dir)
        manifest, inventory, stages = _discover(base)
        if not stages and not inventory:
            print(f"在 {base} 下没找到任何产物（asset-inventory.json / step1~4.json）")
            sys.exit(1)
        if inventory:
            stages = {"inventory": inventory, **stages}
        if inventory and not args.inventory:
            args.inventory = inventory
        if manifest and not args.manifest:
            args.manifest = manifest
        rep = Report()
        rep.info(f"连校验目录：{base}" +
                 (f"（manifest: {os.path.relpath(manifest, base)}）" if manifest else "（未发现 manifest.json）"))
        manifest_ids = load_manifest_ids(manifest) if manifest else None
        loaded = {}
        for stage in ("inventory", "require", "feature", "method", "case"):
            if stage not in stages:
                rep.warn(f"跳过 {stage} 段：产物缺失（{stage} 不适用时忽略本条）")
                continue
            loaded[stage] = _run_stage(stage, stages[stage], rep, args, manifest_ids,
                                       skip_inv_gaps=("inventory" in stages))
        check_cross_stage(loaded.get("require"), loaded.get("method"), loaded.get("case"), rep)
        sys.exit(rep.dump())

    # ---- 单段模式（原行为不变） ----
    if not args.path:
        print("缺少待校验的 JSON 产物路径（或改用 --stage all --dir <目录>）")
        sys.exit(1)

    items = load_items(args.path) if args.stage != "inventory" else None
    rep = Report()

    manifest_ids = None
    if args.manifest:
        manifest_ids = load_manifest_ids(args.manifest)
        if manifest_ids is None:
            rep.warn(f"闸门⑨ 无法解析 manifest.json：{args.manifest}，图号有效性校验跳过")

    if args.stage == "inventory":
        try:
            with open(args.path, "r", encoding="utf-8") as f:
                inv = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"读取失败: {e}")
            sys.exit(1)
        check_inventory(inv, rep, manifest_ids=manifest_ids)
        sys.exit(rep.dump())

    if args.inventory:
        inv = None
        try:
            with open(args.inventory, "r", encoding="utf-8") as f:
                inv = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            rep.warn(f"闸门⑨ 无法解析 asset-inventory.json：{e}")
        if isinstance(inv, dict):
            gaps = inv.get("gaps", [])
            hard = [g for g in gaps if isinstance(g, dict)
                    and str(g.get("类型", "")) in ("硬缺口", "提取失败", "图文冲突")]
            if hard:
                rep.warn(f"闸门⑨ 素材清点遗留 {len(hard)} 条硬性缺口，"
                         f"报告中必须声明证据强度降级：{[g.get('描述', '')[:40] for g in hard][:3]}")

    if args.stage == "require":
        check_require(items, rep, manifest_ids=manifest_ids, strict_degrade=args.strict_degrade)
    elif args.stage == "feature":
        check_feature(items, rep)
    elif args.stage == "method":
        check_method(items, rep)
    else:
        check_case(items, rep, invalid_ratio=args.invalid_ratio)
    sys.exit(rep.dump())


if __name__ == "__main__":
    main()
