#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_images.py — llm-blackbox-testcase 素材取图脚本

从需求素材文件里把图片提取出来，产出 images/ 目录与 manifest.json。
配套规范：references/image-extraction.md 第一节。

支持格式：
  .docx / .docm / .dotx    zip 内 word/media/*
  .wps                     zip 内 word/media/*（含大小写变体兜底）
  .pptx / .ppsx / .potx    zip 内 ppt/media/*
  .xlsx / .xlsm            zip 内 xl/media/*
  .pdf                     需 pdftoppm/pymupdf，缺失时降级为「按页登记」
  .md / .markdown          解析 ![](相对路径)，按相对 md 所在目录解析
  目录                     扫描目录下常见图片文件，按自然序 + 修改时间编号
  图片文件本身             直接登记

设计约束（与技能其它脚本一致）：
  * 只用 Python 标准库，无第三方依赖、无网络
  * 不修改入参文件；只写出 --out 指定目录（默认 ./assets）
  * 脚本自身不读任何其它文件

用法：
  python3 extract_images.py <素材> [--out ./assets] [--also-text]
  python3 extract_images.py 需求.docx --out ./assets --also-text
  python3 extract_images.py ./素材目录 --out ./assets

--also-text：一并导出正文到 <out>/<素材名>-正文.txt（正文里用 [IMG img-N] 标记图片位置）。
  docx / pptx 还会给每张图在 manifest 里写入「前一正文段落 / 后一正文段落」，
  这是第 0 步把「如图所示」锚定到具体图号的直接证据。

退出码：0 = 成功（含降级）；1 = 参数/环境错误；2 = 完全无法提取。
"""

import argparse
import json
import os
import re
import shutil
import struct
import sys
import zipfile

# ---- 图片扩展名白名单 ----
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".emf", ".wmf", ".svg"}

# ---- 各格式在 zip 包内的 media 目录（按优先级尝试）----
ZIP_MEDIA_DIRS = {
    ".docx": ["word/media/"],
    ".docm": ["word/media/"],
    ".dotx": ["word/media/"],
    ".wps": ["word/media/", "Word/media/", "word/Media/"],
    ".pptx": ["ppt/media/"],
    ".ppsx": ["ppt/media/"],
    ".potx": ["ppt/media/"],
    ".xlsx": ["xl/media/"],
    ".xlsm": ["xl/media/"],
}

# ---- 尺寸过小的图（图标/分隔线）默认排除阈值 ----
MIN_DIMENSION = 16
MIN_BYTES = 512

# ---- 字节中位数启发式提示（只提醒、不排除，可调/可关）----
DEFAULT_SMALL_RATIO = 0.6
DEFAULT_LARGE_RATIO = 1.6

# ---- 从二进制头部读宽高（无需第三方库）----
def _dim_png(b):
    if len(b) >= 24 and b[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", b[16:24])
    return None


def _dim_jpeg(b):
    if len(b) < 4 or b[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(b)
    while i + 9 < n:
        if b[i] != 0xFF:
            i += 1
            continue
        marker = b[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = struct.unpack(">H", b[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", b[i + 5:i + 9])
            return (w, h)
        i += 2 + seglen
    return None


def _dim_gif(b):
    if len(b) >= 10 and b[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", b[6:10])
    return None


def _dim_bmp(b):
    if len(b) >= 26 and b[:2] == b"BM":
        w, h = struct.unpack("<ii", b[18:26])
        return (abs(w), abs(h))
    return None


def _dim_webp(b):
    try:
        if len(b) >= 30 and b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            fourcc = b[12:16]
            if fourcc == b"VP8X":
                w = int.from_bytes(b[24:27], "little") + 1
                h = int.from_bytes(b[27:30], "little") + 1
                return (w, h)
            if fourcc == b"VP8 ":
                w = struct.unpack("<H", b[26:28])[0] & 0x3FFF
                h = struct.unpack("<H", b[28:30])[0] & 0x3FFF
                return (w, h)
            if fourcc == b"VP8L":
                bits = int.from_bytes(b[21:25], "little")
                w = (bits & 0x3FFF) + 1
                h = ((bits >> 14) & 0x3FFF) + 1
                return (w, h)
    except Exception:
        return None
    return None


def image_dimension(path):
    """返回 (宽, 高)；识别不出返回 (None, None)。不抛异常。"""
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return (None, None)
    for fn in (_dim_png, _dim_jpeg, _dim_gif, _dim_bmp, _dim_webp):
        try:
            d = fn(head)
            if d:
                return (d[0], d[1])
        except Exception:
            continue
    return (None, None)


def natural_key(s):
    """自然排序：image2 < image10。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# ---- 正文伴随提取（--also-text / 前后正文段落）所需的小工具 ----
# 只依赖标准库，解析 OOXML 的 drawing -> media 映射，用于把每张图锚定到它前后那段正文。
# 这是第 0 步锚点映射的直接证据：没有它，"顺序对齐"这类锚定依据就没有支撑。
from html import unescape as _unescape

_T_RE = re.compile(r"<(?:w|a):t[^>]*>(.*?)</(?:w|a):t>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _seg_text(seg):
    """取一段 OOXML 里的可见文本（w:t / a:t），去标签、去实体。"""
    raw = "".join(_T_RE.findall(seg))
    raw = _TAG_RE.sub("", raw)
    raw = raw.replace("<w:tab/>", "\t").replace("<w:br/>", "\n")
    return _unescape(raw).strip()


def _parse_rels(z, rels_name):
    """解析 _rels/*.xml.rels，返回 {rId: zip 内路径}。"""
    out = {}
    try:
        xml = z.read(rels_name).decode("utf-8", "ignore")
    except Exception:
        return out
    base = rels_name.rsplit("/", 2)[0] if "/_rels/" in rels_name else ""
    for m in re.finditer(r"<Relationship\b[^>]*/?>", xml):
        tag = m.group(0)
        rid = re.search(r'\bId="([^"]+)"', tag)
        tgt = re.search(r'\bTarget="([^"]+)"', tag)
        if not (rid and tgt):
            continue
        t = tgt.group(1)
        if t.startswith(("http:", "https:", "//")):
            continue
        if base:
            t = os.path.normpath(os.path.join(base, t)).replace("\\", "/")
        out[rid.group(1)] = t.lstrip("/")
    return out


def _blip_ids(inner):
    """从一个段落/形状里取出它引用的图片 rel id，保持出现顺序。"""
    ids = []
    for dm in re.finditer(r"<w:drawing\b.*?</w:drawing>|<w:pict\b.*?</w:pict>", inner, re.S):
        blk = dm.group(0)
        if "<w:pict" in blk[:12]:
            for r in re.finditer(r"<v:imagedata\b[^>]*>", blk):
                m = re.search(r'r:id="([^"]+)"', r.group(0))
                if m:
                    ids.append(m.group(1))
        for m in re.finditer(r'r:embed="([^"]+)"', blk):
            ids.append(m.group(1))
    return ids


def _office_plan(z, names):
    """
    解析 docx/wps/pptx 正文，返回：
      plan  : [(media_zip_path, {"前一正文段落":…, "后一正文段落":…, "所在位置":…})] 按正文顺序
      bodies: [(body_path, [ (段落文本, [rel_id,...]) ])] 用于 --also-text 重建带图标记的正文
    不能解析时返回 (None, None) —— 调用方降级为「按 media 文件名排序」的原行为。
    """
    try:
        if "word/document.xml" in names and "word/_rels/document.xml.rels" in names:
            rels = _parse_rels(z, "word/_rels/document.xml.rels")
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
            paras = re.findall(r"<w:p(?:\s[^>]*)?>(.*?)</w:p>", xml, re.S)
            units = [(p, _seg_text(p), _blip_ids(p)) for p in paras]
            return _plan_from_units(units, rels, scene=None), [("word/document.xml", units)]

        slides = sorted([n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)],
                        key=lambda n: natural_key(n))
        if slides:
            plan, bodies = [], []
            for idx, sn in enumerate(slides, 1):
                rels = _parse_rels(z, f"ppt/slides/_rels/{os.path.basename(sn)}.rels")
                xml = z.read(sn).decode("utf-8", "ignore")
                sps = re.findall(r"<p:sp\b.*?</p:sp>", xml, re.S)
                units = [(s, _seg_text(s), _blip_ids(s)) for s in sps]
                # 幻灯片内的形状不构成"前后段落"语义，改用「本页文本」作上下文
                for (_s, txt, ids) in units:
                    for rid in ids:
                        mp = rels.get(rid)
                        if mp:
                            plan.append((mp, {"前一正文段落": txt, "后一正文段落": "",
                                              "所在位置": f"第 {idx} 页幻灯片"}))
                bodies.append((sn, units))
            return plan, bodies
    except Exception:
        return None, None
    return None, None


def _plan_from_units(units, rels, scene=None):
    """units: [(原文片段, 段落文本, [rel_id,...])] -> 按顺序的 (media路径, 上下文)。"""
    texts = [u[1] for u in units]
    plan = []
    for i, (_p, txt, ids) in enumerate(units):
        for rid in ids:
            mp = rels.get(rid)
            if not mp:
                continue
            prev = next((t for t in reversed(texts[:i]) if t), "")
            nxt = next((t for t in texts[i + 1:] if t), "")
            plan.append((mp, {"前一正文段落": prev, "后一正文段落": nxt}))
    return plan


def _render_document_text(bodies, media_to_tag, include_empty=False):
    """重建正文：每段一行；段落引用的图片在该段之后插入 [IMG img-N] 标记行。"""
    lines = []
    for _body, units in bodies:
        for (_p, txt, ids) in units:
            if txt or include_empty:
                lines.append(txt)
            for rid in ids:
                tag = media_to_tag.get(rid)
                if tag:
                    lines.append(f"[IMG {tag}]")
    return "\n".join(lines) + "\n"


class Collector:
    def __init__(self, out_dir, size_hint=True, small_ratio=DEFAULT_SMALL_RATIO,
                 large_ratio=DEFAULT_LARGE_RATIO):
        self.out_dir = out_dir
        self.img_dir = os.path.join(out_dir, "images")
        self.records = []      # 已登记的图片
        self.gaps = []         # 降级/失败记录
        self.sources = []      # 本次处理的素材文件
        self._seen_hash = {}   # (bytes,size) -> 已合并的图号，用于同图多格式合并
        self.body_text = {}    # 素材 -> 带 [IMG img-N] 标记的正文文本（仅 --also-text 时填充）
        self.size_hint = size_hint       # 字节中位数提示开关（提示≠排除）
        self.small_ratio = small_ratio
        self.large_ratio = large_ratio

    # ---------- 落盘 ----------
    def add_image(self, data, orig_name, source, location, order_hint=None, context=None):
        """写入一张图并返回记录。尺寸过小则排除但仍登记。"""
        size = len(data)
        # 同内容合并：字节完全相同的图只留一份
        key = (hash(data), size)
        if key in self._seen_hash:
            prev = self._seen_hash[key]
            prev.setdefault("合并自", []).append(f"{source}:{orig_name}")
            return None

        ext = os.path.splitext(orig_name)[1].lower()
        idx = len(self.records) + 1
        fname = f"img-{idx}{ext if ext in IMAGE_EXT else '.png'}"
        os.makedirs(self.img_dir, exist_ok=True)
        dest = os.path.join(self.img_dir, fname)
        with open(dest, "wb") as f:
            f.write(data)

        w, h = image_dimension(dest)
        excluded = None
        if w is not None and h is not None and (w < MIN_DIMENSION or h < MIN_DIMENSION):
            excluded = "尺寸过小"
        elif size < MIN_BYTES:
            excluded = "尺寸过小"

        rec = {
            "图号": f"img-{idx}",
            "文件名": fname,
            "原始文件名": orig_name,
            "来源": source,
            "位置": location,
            "字节": size,
            "宽": w,
            "高": h,
            "排除": excluded,
            "合并自": [],
        }
        if order_hint is not None:
            rec["顺序提示"] = order_hint
        # 正文上下文（可选）：锚点映射的直接证据
        if context:
            for k in ("前一正文段落", "后一正文段落", "所在位置"):
                v = context.get(k)
                if v:
                    rec[k] = v
        self.records.append(rec)
        self._seen_hash[key] = rec
        return rec

    def add_gap(self, gtype, location, desc, advice):
        self.gaps.append({"类型": gtype, "位置": location, "描述": desc, "处置建议": advice})

    def note_source(self, path, kind, count):
        self.sources.append({"文件": path, "格式": kind, "提取图片数": count})

    def manifest(self):
        kept = [r for r in self.records if not r["排除"]]
        excluded = [r for r in self.records if r["排除"]]
        # 尺寸提示：字节相对中位数明显偏小/偏大时**提醒**清点者留意（不参与排除，
        # 也不代表图有问题——正常表单/弹窗截图本来就会偏小）。阈值可用
        # --small-ratio/--large-ratio 调整，--no-size-hint 关闭。
        if self.size_hint and len(kept) >= 3:
            sizes = sorted(r["字节"] for r in kept)
            med = sizes[len(sizes) // 2]
            for r in kept:
                if r["字节"] < med * self.small_ratio:
                    r["尺寸提示"] = (f"字节数约为中位数的 {r['字节']/med:.0%}，"
                                    "请确认是否为弹窗/表单类截图（仅提醒，不代表图异常）")
                elif r["字节"] > med * self.large_ratio:
                    r["尺寸提示"] = (f"字节数约为中位数的 {r['字节']/med:.0%}，"
                                    "请确认是否为整页/长列表截图（仅提醒，不代表图异常）")
        return {
            "素材文件": self.sources,
            "图片总数": len(kept),
            "已排除": [{"图号": r["图号"], "原因": r["排除"]} for r in excluded],
            "images": kept,
            "gaps": self.gaps,
            "提示": "图号 img-N 全程不变，后续所有 JSON 产物必须沿用同一编号；"
                    "锚点映射与八类元素清点见 references/image-extraction.md。",
        }


# ---- 各格式提取器 ----

def _read_member(z, n):
    try:
        with z.open(n) as f:
            return f.read()
    except Exception:
        return None


def extract_zip_office(path, col, kind, media_dirs, also_text=False):
    """docx/wps/pptx/xlsx 系列：从 zip 的 media 目录取图。

    正文可解析时（docx/pptx）按**文档正文出现顺序**编号并附上前后正文段落，
    这是第 0 步「如图所示 → img-N」锚点映射的直接证据；
    解析不了（xlsx 等）时降级为原行为：按 media 文件名自然序。
    """
    count = 0
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            # 找实际存在的 media 前缀
            prefix = None
            for d in media_dirs:
                if any(n.startswith(d) for n in names):
                    prefix = d
                    break
            if prefix is None:
                cands = sorted({n.rsplit("/", 1)[0] + "/" for n in names if "/media/" in n.lower()})
                if cands:
                    prefix = cands[0]
            if prefix is None:
                col.add_gap("提取失败", path, f"{kind} 包内未找到 media 目录",
                            "检查素材是否内嵌图片；若无图属正常，忽略本条")
                return count

            entries = [n for n in names if n.startswith(prefix) and not n.endswith("/")]
            entries = [n for n in entries if os.path.splitext(n)[1].lower() in IMAGE_EXT
                       and os.path.basename(n)]

            # ---- 尝试解析正文顺序与上下文 ----
            plan, bodies = _office_plan(z, names)
            ctx_by_member, ordered = {}, []
            if plan:
                for mp, ctx in plan:
                    if mp not in ctx_by_member and mp in entries:
                        ctx_by_member[mp] = ctx
                        ordered.append(mp)
                # 正文里引用不到的（如页眉图）按自然序兜底追加在最后
                ordered += [n for n in sorted(entries, key=lambda n: natural_key(os.path.basename(n)))
                            if n not in ctx_by_member]
            else:
                ordered = sorted(entries, key=lambda n: natural_key(os.path.basename(n)))
                if also_text:
                    col.add_gap("锚点存疑", path,
                                f"{kind} 无法解析正文结构，未产出伴随正文（仅 xlsx/docx 非标结构会出现）",
                                "正文请人工导出后粘贴给 prompts/00-asset-inventory.md 做锚点映射")

            media_to_tag = {}
            for n in ordered:
                data = _read_member(z, n)
                if not data:
                    continue
                base = os.path.basename(n)
                r = col.add_image(data, base, os.path.basename(path), n,
                                  order_hint=count + 1, context=ctx_by_member.get(n))
                if not r:
                    # 同内容已合并到前面的图：复用它的图号，保证 [IMG img-N] 标记指向正确
                    r = next((x for x in col.records if x["位置"] == n), None)
                else:
                    count += 1
                if r:
                    media_to_tag[n] = r["图号"]

            if also_text and bodies:
                # 重建带 [IMG img-N] 标记的正文：需要 rel_id -> 图号 的桥接
                member_to_tag = {x["位置"]: x["图号"] for x in col.records}
                rid_to_tag = {}
                for (sn, _units) in bodies:
                    if "/" in sn:
                        head, tail = sn.rsplit("/", 1)
                        rels_name = f"{head}/_rels/{tail}.rels"
                    else:
                        rels_name = f"_rels/{sn}.rels"
                    if rels_name in names:
                        for rid, target in _parse_rels(z, rels_name).items():
                            tag = member_to_tag.get(target)
                            if tag:
                                rid_to_tag[rid] = tag
                text = _render_document_text(bodies, rid_to_tag)
                col.body_text[os.path.basename(path)] = text
    except zipfile.BadZipFile:
        col.add_gap("提取失败", path, f"不是合法的 {kind} zip 包（可能为旧版二进制格式）",
                    "用 WPS/Office 另存为新版格式后重试")
    except OSError as e:
        col.add_gap("提取失败", path, f"打开失败：{e}", "检查文件是否被占用")
    return count


def extract_pdf(path, col, out_dir):
    """pdf：优先按页渲染；无工具时降级为按页登记。"""
    n_pages = None
    try:
        with open(path, "rb") as f:
            head = f.read()
        # 粗略数页码，不解析对象流——够用即可
        n_pages = len(re.findall(rb"/Type\s*/Page[^s]", head)) or None
    except OSError as e:
        col.add_gap("提取失败", path, f"读取失败：{e}", "人工核对")
        return 0

    tool = shutil.which("pdftoppm")
    if not tool:
        col.add_gap(
            "提取失败", path,
            f"pdf 未抽图：本机缺少 pdftoppm（页码粗估 {n_pages or '未知'} 页）",
            "安装 poppler 后重跑；或手动把 pdf 每页截图放入 images/ 并编号，"
            "在 asset-inventory 的 assets[] 里补登",
        )
        return 0

    os.makedirs(col.img_dir, exist_ok=True)
    prefix = os.path.join(col.img_dir, "_pdfpage")
    import subprocess
    try:
        subprocess.run([tool, "-png", "-r", "150", path, prefix],
                       check=True, capture_output=True)
    except Exception as e:
        col.add_gap("提取失败", path, f"pdftoppm 渲染失败：{e}", "人工把 pdf 每页截图后补录")
        return 0

    pages = sorted([f for f in os.listdir(col.img_dir) if f.startswith("_pdfpage")],
                   key=natural_key)
    count = 0
    for i, pf in enumerate(pages, 1):
        p = os.path.join(col.img_dir, pf)
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError:
            continue
        # pdf 渲染出的整页图重新编号，避免 _pdfpage 命名流入 manifest
        os.remove(p)
        r = col.add_image(data, f"page{i}.png", os.path.basename(path), f"第 {i} 页", order_hint=i)
        if r:
            count += 1
    if count:
        col.add_gap("锚点存疑", path,
                    "pdf 按页整页截图提取，一页内可能含多张子图，锚点映射需人工细分",
                    "在 asset-inventory 里按页登记，正文引用措辞逐条人工指定页号")
    return count


def extract_markdown(path, col):
    """md：解析 ![](相对路径)，相对 md 文件所在目录解析。"""
    count = 0
    base_dir = os.path.dirname(os.path.abspath(path))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        col.add_gap("提取失败", path, f"读取失败：{e}", "人工核对")
        return 0

    # ![alt](path "title")  与 <img src="path">
    pats = [re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)"),
            re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)]
    seen = []
    for p in pats:
        seen.extend(p.findall(text))
    for i, ref in enumerate(seen, 1):
        if re.match(r"^(https?:)?//", ref):
            col.add_gap("提取失败", f"{path} 第{i}个引用",
                        f"远程图片未下载：{ref}",
                        "本地化后重跑；远程图可能失效导致需求证据丢失")
            continue
        rel = ref.split("#")[0].split("?")[0]
        cand = os.path.normpath(os.path.join(base_dir, rel))
        if not os.path.isfile(cand):
            col.add_gap("硬缺口", f"{path} 第{i}个引用",
                        f"引用的图片文件不存在：{ref}",
                        "补齐素材文件后重跑，否则该段需求缺证据")
            continue
        ext = os.path.splitext(cand)[1].lower()
        if ext not in IMAGE_EXT:
            continue
        try:
            with open(cand, "rb") as f:
                data = f.read()
        except OSError as e:
            col.add_gap("提取失败", cand, f"读取失败：{e}", "人工核对")
            continue
        r = col.add_image(data, os.path.basename(cand), os.path.basename(path), f"第{i}个图片引用",
                          order_hint=i)
        if r:
            count += 1
    return count


def extract_dir(path, col):
    """目录：扫描常见图片文件，按自然序 + 修改时间。"""
    files = []
    for root, _dirs, names in os.walk(path):
        for n in names:
            if os.path.splitext(n)[1].lower() in IMAGE_EXT:
                files.append(os.path.join(root, n))
    files.sort(key=lambda p: (os.path.getmtime(p), natural_key(os.path.basename(p))))
    count = 0
    for p in files:
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError as e:
            col.add_gap("提取失败", p, f"读取失败：{e}", "人工核对")
            continue
        r = col.add_image(data, os.path.basename(p), os.path.basename(path), p, order_hint=count + 1)
        if r:
            count += 1
    if count:
        col.add_gap("锚点存疑", path,
                    f"目录扫描得到 {count} 张图，但无正文锚点，无法判断归属",
                    "在 asset-inventory 里逐张人工指定对应章节；正文未引用的图标记为「有图无引用」")
    return count


def main():
    ap = argparse.ArgumentParser(description="llm-blackbox-testcase 素材取图")
    ap.add_argument("source", help="素材文件或目录")
    ap.add_argument("--out", default="./assets", help="输出目录，默认 ./assets")
    ap.add_argument("--also-text", action="store_true",
                    help="同时导出正文到 <out>/text.txt（含 [IMG img-N] 标记），"
                         "docx/pptx 有效，其它格式降级跳过")
    ap.add_argument("--small-ratio", type=float, default=DEFAULT_SMALL_RATIO,
                    help=f"尺寸提示阈值：字节 < 中位数×该值时提示偏小，默认 {DEFAULT_SMALL_RATIO}")
    ap.add_argument("--large-ratio", type=float, default=DEFAULT_LARGE_RATIO,
                    help=f"尺寸提示阈值：字节 > 中位数×该值时提示偏大，默认 {DEFAULT_LARGE_RATIO}")
    ap.add_argument("--no-size-hint", action="store_true",
                    help="关闭字节中位数尺寸提示（素材里小图本来就多时使用）")
    args = ap.parse_args()

    src = args.source
    if not os.path.exists(src):
        print(f"素材不存在：{src}")
        sys.exit(1)

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    col = Collector(out_dir, size_hint=not args.no_size_hint,
                    small_ratio=args.small_ratio, large_ratio=args.large_ratio)

    total = 0
    if os.path.isdir(src):
        total = extract_dir(src, col)
        col.note_source(src, "目录", total)
    elif os.path.isfile(src):
        ext = os.path.splitext(src)[1].lower()
        if ext in ZIP_MEDIA_DIRS:
            total = extract_zip_office(src, col, ext.lstrip("."), ZIP_MEDIA_DIRS[ext],
                                       also_text=args.also_text)
            col.note_source(src, ext.lstrip("."), total)
        elif ext == ".pdf":
            total = extract_pdf(src, col, out_dir)
            col.note_source(src, "pdf", total)
        elif ext in (".md", ".markdown"):
            total = extract_markdown(src, col)
            col.note_source(src, "markdown", total)
        elif ext in IMAGE_EXT:
            with open(src, "rb") as f:
                data = f.read()
            r = col.add_image(data, os.path.basename(src), os.path.basename(src), src)
            total = 1 if r else 0
            col.note_source(src, "图片", total)
        elif ext in (".doc", ".ppt", ".xls"):
            col.add_gap("提取失败", src,
                        f"旧版二进制格式（{ext}）不是 zip 包，无法自动取图",
                        "用 WPS/Office 另存为 .docx/.pptx/.xlsx 后重跑")
            col.note_source(src, ext.lstrip("."), 0)
        else:
            col.add_gap("提取失败", src, f"不支持的格式：{ext}",
                        "转成 docx/pptx/xlsx/pdf/md 后重跑")
            col.note_source(src, ext.lstrip("."), 0)

    mf = col.manifest()
    mf_path = os.path.join(out_dir, "manifest.json")
    with open(mf_path, "w", encoding="utf-8") as f:
        json.dump(mf, f, ensure_ascii=False, indent=2)

    ctx_n = sum(1 for r in mf["images"] if r.get("前一正文段落") or r.get("后一正文段落"))
    text_files = []
    for src_name, text in col.body_text.items():
        stem = os.path.splitext(src_name)[0] or src_name
        p = os.path.join(out_dir, f"{stem}-正文.txt")
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            text_files.append(p)
        except OSError as e:
            col.add_gap("提取失败", p, f"正文写出失败：{e}", "检查目录写权限")

    print("=" * 60)
    print("素材取图结果")
    print("=" * 60)
    for s in mf["素材文件"]:
        print(f"  {s['文件']}  [{s['格式']}]  提取 {s['提取图片数']} 张")
    print("-" * 60)
    for r in mf["images"]:
        dim = f"{r['宽']}x{r['高']}" if r["宽"] else "尺寸未知"
        extra = f"  <- {r.get('尺寸提示')}" if r.get("尺寸提示") else ""
        print(f"  {r['图号']:>7}  {r['文件名']:<14} {r['字节']:>9}B  {dim}{extra}")
    if mf["已排除"]:
        print("-" * 60)
        for e in mf["已排除"]:
            print(f"  [排除] {e['图号']}  {e['原因']}")
    if mf["gaps"]:
        print("-" * 60)
        for g in mf["gaps"]:
            print(f"  [{g['类型']}] {g['描述']}")
    if ctx_n:
        print(f"  [锚点上下文] {ctx_n}/{mf['图片总数']} 张图已附上前后正文段落，"
              f"可直接用于 prompts/00-asset-inventory.md 的锚点映射")
    print("-" * 60)
    print(f"图片总数 {mf['图片总数']}；缺口 {len(mf['gaps'])} 条")
    for p in text_files:
        print(f"正文已写出：{p}（含 [IMG img-N] 标记）")
    print(f"清单已写出：{mf_path}")
    print(f"下一步：把 manifest.json 与图片内容交给 prompts/00-asset-inventory.md 做锚点映射。")

    if mf["图片总数"] == 0 and mf["gaps"]:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
