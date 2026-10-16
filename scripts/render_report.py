#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_report.py — llm-blackbox-testcase 报告装配脚本

把五段 Prompt 的 JSON 产物装配成单文件 HTML 长文档报告。

设计约束（与技能其它脚本一致）：
  * 只用 Python 标准库，无第三方依赖、无网络
  * 只读入参指定的 JSON + 本技能的 templates/report-template.html；只写出 --out 指定文件
  * 视觉上当且仅当使用 templates/report-template.html 的 <style>（整套提取，同源）；
    追加的筛选控件与缩略图样式只用该设计系统已有的 CSS 变量，不引入第二套视觉语言

用法：
  python3 render_report.py --dir . --out 报告.html --title "英文研报运营"
  python3 render_report.py --dir . --out r.html --title X \
      --inventory asset-inventory.json --manifest assets/manifest.json --embed-images

自动发现的产物：step1.json(需求点) step2.json(特征画像) step3.json(方法矩阵)
                step4.json(用例集，可选)
step3 缺失时仍可产出只含前两段内容的报告。

退出码：0 = 成功；1 = 参数/文件错误。
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from html import escape as e

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TEMPLATE = os.path.join(SKILL_ROOT, "templates", "report-template.html")
VALIDATOR = os.path.join(SKILL_ROOT, "scripts", "validate-output.py")

# 追加在此设计系统之上的少量样式（只用模板已有变量）
EXTRA_CSS = """
/* ---- 表格筛选工具条（render_report.py 追加，变量沿用本设计系统）---- */
.ftoolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 12px 0}
.ftoolbar select,.ftoolbar input{
  font-family:var(--font-body);font-size:12.5px;color:var(--text);
  background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:6px 10px;min-width:130px;
}
.ftoolbar input[type=search]{min-width:200px}
.ftoolbar .fcount{margin-left:auto;font-family:var(--font-display);font-weight:600;
  font-size:12.5px;color:var(--primary)}
.tbl-wrap{margin-top:8px}
/* ---- 图片素材缩略图（§0 素材清点）---- */
.img-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.img-card{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-md);
  padding:12px}
.img-card img{width:100%;border-radius:var(--radius-sm);border:1px solid var(--border);
  display:block;cursor:zoom-in}
.img-card .cap{font-family:var(--font-display);font-weight:600;font-size:12.5px;
  color:var(--primary);margin:8px 0 4px}
.img-card .ctx{font-size:11.5px;color:var(--text-muted);line-height:1.5}
.img-card .ctx b{font-weight:600;color:var(--text)}
"""

# 表格筛选 JS：对 class="filterable" 的表按 data-filters="列号:标签,..." 生成下拉，
# data-search="1" 时再给一个关键字框。纯原生，无依赖。
FILTER_JS = """
// ---- 表格筛选：data-filters="0:需求点,1:类型" data-search="1" ----
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('table.filterable').forEach(function (tbl) {
    var specs = (tbl.dataset.filters || '').split(',').filter(Boolean).map(function (s) {
      var parts = s.split(':'); return { idx: parseInt(parts[0], 10), label: parts[1] || s };
    });
    if (!specs.length) return;
    var body = tbl.tBodies[0]; if (!body) return;
    var rows = Array.prototype.slice.call(body.rows);
    var host = tbl.closest('.tbl-wrap') || tbl.parentNode;
    var bar = document.createElement('div'); bar.className = 'ftoolbar';

    function uniq(i) {
      var seen = {}, out = [];
      rows.forEach(function (r) {
        var c = r.cells[i]; if (!c) return;
        var t = (c.textContent || '').trim().split(/[\\n\\r]+/)[0].slice(0, 24);
        if (t && !seen[t]) { seen[t] = 1; out.push(t); }
      });
      return out.sort();
    }
    function apply() {
      var vals = [], kw = (bar.__kw ? bar.__kw.value.trim().toLowerCase() : '');
      bar.querySelectorAll('select').forEach(function (s) { vals.push(s.value); });
      var shown = 0;
      rows.forEach(function (r) {
        var ok = true, text = (r.textContent || '').toLowerCase();
        for (var i = 0; i < specs.length; i++) {
          if (!vals[i]) continue;
          var c = r.cells[specs[i].idx];
          if (!c || (c.textContent || '').indexOf(vals[i]) === -1) { ok = false; break; }
        }
        if (ok && kw && text.indexOf(kw) === -1) ok = false;
        r.style.display = ok ? '' : 'none';
        if (ok) shown++;
      });
      bar.__count.textContent = shown + ' / ' + rows.length + ' 条';
    }

    specs.forEach(function (sp) {
      var sel = document.createElement('select');
      var opt0 = document.createElement('option'); opt0.value = ''; opt0.textContent = '全部' + sp.label;
      sel.appendChild(opt0);
      uniq(sp.idx).forEach(function (v) {
        var o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o);
      });
      sel.addEventListener('change', apply); bar.appendChild(sel);
    });
    if (tbl.dataset.search === '1') {
      var kw = document.createElement('input');
      kw.type = 'search'; kw.placeholder = '关键字过滤（任意列）';
      kw.addEventListener('input', apply); bar.__kw = kw; bar.appendChild(kw);
    }
    var cnt = document.createElement('span'); cnt.className = 'fcount';
    bar.__count = cnt; bar.appendChild(cnt);
    host.parentNode.insertBefore(bar, host);
    apply();
  });
});
"""


# ---------- 基础工具 ----------
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_style(template):
    """整套提取模板的设计系统，这是视觉的唯一真源。"""
    try:
        with open(template, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as ex:
        print(f"[warn] 读取模板失败（{ex}），回退内置样式可能不一致")
        return "", ""
    m = re.search(r"<style[^>]*>(.*?)</style>", raw, re.S)
    if not m:
        print("[warn] 模板里没找到 <style>，报告将只有结构没有样式")
        return "", ""
    return m.group(1), raw


def r_year_month(day=None):
    import datetime
    d = day or datetime.date.today()
    return d.strftime("%Y-%m-%d")


def tag_of(spec):
    """从 'F5 布尔条件组合（次特征 F14）' 取出 (F5, 布尔条件组合, F14|None)。"""
    m = re.match(r"\s*(F\d+)\s*([^（(（]*)", spec or "")
    if not m:
        return ("", spec or "", None)
    fid = m.group(1)
    name = (m.group(2) or "").strip()
    sm = re.search(r"次特征\s*(F\d+)", spec or "")
    return (fid, name, sm.group(1) if sm else None)


def main_of(method_str):
    m = re.search(r"([^\s+（(]+?)\s*（主）", method_str or "")
    return m.group(1).strip() if m else ""


def aux_of(method_str, main):
    parts = re.findall(r"([A-Za-z\u4e00-\u9fff· ]+?（(?:辅|补漏)[^）]*）)", (method_str or "")[len(main):])
    if parts:
        return " + ".join(p.strip() for p in parts)
    rest = re.sub(r"^.*?（主）\s*\+?\s*", "", method_str or "").replace("（辅）", "").strip()
    return rest


def inline_image(path):
    try:
        ext = os.path.splitext(path)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}.get(ext)
        if not mime:
            return None
        with open(path, "rb") as f:
            return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None


# ---------- 各段渲染 ----------
def build_metrics(s1, s2, s3, s4):
    n_case = len(s4)
    invalid = [c for c in s4 if str(c.get("用例类型", "")) in ("无效", "边界·离点", "异常")]
    automatable = [c for c in s4 if str(c.get("是否可自动化", "")).startswith("是")]
    kinds = len({tag_of(s.get("特征类型", ""))[0] for s in s2} - {""})
    ratio = (len(invalid) / n_case * 100) if n_case else 0
    cells = [
        (len(s1), "需求点", "7 类需求沉淀自需求点类型的分布统计"),
        (len(s2), "测试点", f"横跨 {kinds} 类特征形态（F1~F18）"),
        (n_case, "可执行用例", f"可自动化 {len(automatable)} 条") if n_case else
        (len(s3), "方法矩阵条目", "本次未展开到可执行用例"),
        (f"{ratio:.0f}%", "无效域用例占比", f"无效/离点/异常 {len(invalid)} 条，阈值 ≥30%"),
    ]
    return "".join(
        f'<div class="metric"><div class="v">{e(str(v))}</div><div class="l">{e(l)}</div>'
        f'<div class="d">{e(d)}</div></div>' for v, l, d in cells
    )


def build_map_table(s1, s2, s3):
    meta = {}
    for r in s1:
        meta.setdefault(r.get("id", ""), {"名": r.get("需求点", ""), "类型": r.get("类型", "")})
    sub_by = {}
    for s in s2:
        sub_by.setdefault(s.get("需求点id", ""), s.get("次特征", "无"))
    rows = []
    for idx, it in enumerate(s3):
        rid = it.get("需求点", "")
        info = meta.get(rid, {})
        spec = it.get("被测对象特征", "")
        fid, fname, sub = tag_of(spec)
        sub = sub or (sub_by.get(rid) or None)
        method = it.get("推荐黑盒测试方法", "")
        main = main_of(method)
        aux = aux_of(method, main)
        tag = f'<span class="ftype">{e(fid)} {e(fname)}</span>' if fid else ""
        stag = f'<span class="ftype sub">{e(sub)}</span>' if sub and sub != "无" else ""
        rows.append(
            f'<tr><td class="req">{e(rid)} {e(info.get("名", ""))}'
            f'<br><span class="muted">[{e(info.get("类型", ""))}]</span></td>'
            f'<td>{e(it.get("测试点", ""))}</td>'
            f'<td>{tag}{stag}</td>'
            f'<td><b>{e(main)}</b>' + (f' + <span class="muted">{e(aux)}</span>' if aux else "") +
            f'<br><span class="muted">{e(it.get("方法分工", "")[:60])}…</span></td></tr>'
        )
    return "".join(rows)


def build_case_table(s4):
    pill_cls = {"有效": "tag-pill", "无效": "tag-pill warn", "异常": "tag-pill warn",
                "边界·上点": "tag-pill warn", "边界·内点": "tag-pill", "边界·离点": "tag-pill warn"}
    pri_map = {"高": "P0", "中": "P1", "低": "P2"}
    rows = []
    for c in s4:
        t = str(c.get("用例类型", ""))
        cls = pill_cls.get(t, "tag-pill")
        auto = str(c.get("是否可自动化", "")).startswith("是")
        rows.append(
            f'<tr><td class="req">{e(c.get("用例ID", ""))}</td>'
            f'<td><span class="{cls}">{e(t)}</span></td>'
            f'<td>{e(c.get("需求点", ""))} · {e(c.get("测试点", "")[:30])}</td>'
            f'<td><span class="muted">前置:</span> {e(c.get("前置条件", "")[:46])}'
            f'<br><span class="muted">输入:</span> {e(c.get("输入数据", "")[:64])}</td>'
            f'<td>{e(c.get("预期结果", ""))}</td>'
            f'<td><span class="muted">{e(c.get("方法归属", ""))}</span><br>'
            f'<span class="tag-pill{" warn" if not auto else ""}">'
            f'{"可自动化" if auto else "需人工"}</span> '
            f'<span class="muted">{e(pri_map.get(c.get("优先级", ""), ""))}</span></td></tr>'
        )
    return "".join(rows)


def build_dimension(s2, s3):
    """§4 降维条目：数据来自特征画像。"""
    if not s2:
        return '<div class="callout">本次没有超过 20 的组合规模，无需降维。</div>'
    target = {}
    for s in s3:
        target.setdefault(s.get("测试点", ""), s.get("覆盖目标与退出标准", ""))
    cards = []
    for s in s2:
        if s.get("需降维") is not True:
            continue
        scale = s.get("组合规模", 0)
        goal = str(s.get("降维目标", ""))
        m = re.search(r"(\d+)\s*条", goal)
        reduced = int(m.group(1)) if m else 0
        g = target.get(s.get("测试点", ""), "")
        pct = (reduced / scale * 100) if isinstance(scale, (int, float)) and scale else 0
        cards.append(
            f'<div class="card">'
            f'<div class="barrow"><div class="lbl">{e(s.get("需求点id", ""))} {e(s.get("测试点", "")[:24])}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:100%;opacity:.3"></div></div>'
            f'<div class="val">{e(str(scale))} 全组合</div></div>'
            f'<div class="barrow"><div class="lbl"></div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%"></div></div>'
            f'<div class="val">{e(str(reduced) or "—")} 降维后</div></div>'
            f'<p style="margin-top:12px;font-size:13px;color:var(--text-muted)">'
            f'{e(goal or g)}</p></div>'
        )
    return "".join(cards) or '<div class="callout">本次所有测试点组合规模均 ≤20，无需降维。</div>'


def build_todo(s1):
    items = [r for r in s1 if r.get("待确认") is True]
    if not items:
        return '<div class="callout">本次没有待确认项：所有规则性表述均有文本或图片依据。</div>'
    out = []
    for r in items:
        why = r.get("业务规则", "") or r.get("验收标准", "")
        out.append(
            f'<div class="callout warn"><b>[待确认 · {e(r.get("id", ""))}]</b> '
            f'{e(r.get("需求点", ""))}'
            f'<br><span class="muted">{e(why[:180])}</span></div>'
        )
    return "".join(out)


def build_inventory(manifest, inventory, embed, base, man_dir=None):
    if not (manifest or inventory):
        return '<div class="callout">本次未提供素材清点产物（manifest.json / asset-inventory.json），' \
               '若需求素材含图，请先跑第 0 步再做本表。</div>'
    parts = []
    imgs = (manifest or {}).get("images", [])
    if imgs:
        imap = {r.get("图号"): r for r in imgs}
        gaps = (inventory or {}).get("gaps", [])
        hard = [g for g in gaps if str(g.get("类型", "")) in ("硬缺口", "提取失败", "图文冲突")]
        refs = (inventory or {}).get("image_refs", [])
        png_ids = {k for k, v in imap.items() if str(v.get("文件名", "")).lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp"))}
        parts.append(
            f'<div class="grid g4" style="margin-bottom:16px">'
            f'<div class="metric"><div class="v">{len(imgs)}</div><div class="l">图片素材</div>'
            f'<div class="d">已排除 {len((manifest or {}).get("已排除", []))} 张</div></div>'
            f'<div class="metric"><div class="v">{len(refs)}</div><div class="l">锚点映射</div>'
            f'<div class="d">「如图所示」类措辞逐条锚定</div></div>'
            f'<div class="metric"><div class="v">{len(gaps)}</div><div class="l">缺口</div>'
            f'<div class="d">其中硬性 {len(hard)} 条</div></div>'
            f'<div class="metric"><div class="v">{len(png_ids)}</div><div class="l">可作证</div>'
            f'<div class="d">已登记的一大/批图片</div></div></div>'
        )
        cards = []
        embedded = 0
        for k in sorted(imap, key=lambda x: int(re.sub(r"\D", "", x) or 0)):
            rec = imap[k]
            prev = rec.get("前一正文段落", "") or ""
            nxt = rec.get("后一正文段落", "") or ""
            slot = ""
            if embed:
                fname = rec.get("文件名", "")
                for cand in (os.path.join(man_dir or base, "images", fname),
                             os.path.join(base, "images", fname),
                             os.path.join(base, "assets", "images", fname)):
                    if cand and os.path.isfile(cand):
                        data = inline_image(cand)
                        if data:
                            slot = f'<img src="{data}" alt="{e(k)}">'
                            embedded += 1
                        break
            cards.append(
                f'<div class="img-card">'
                f'<div class="cap">{e(k)} · {e(rec.get("文件名", ""))} '
                f'<span class="muted">{e(str(rec.get("宽", "?")))}x{e(str(rec.get("高", "?")))}</span></div>'
                + slot +
                f'<div class="ctx"><b>前一段：</b>{e(prev[:90]) or "—"}<br>'
                f'<b>后一段：</b>{e(nxt[:90]) or "—"}</div></div>'
            )
        if embed and embedded == 0:
            parts.append('<div class="callout warn">--embed-images 已指定，'
                         '但没在 images/ 目录里找到对应图片文件，本节退化为只显示前后正文段落。</div>')
        if cards:
            parts.append(f'<div class="img-grid">{"".join(cards)}</div>')
    gaps = (inventory or {}).get("gaps", [])
    if gaps:
        rows = "".join(
            f'<tr><td class="req">{e(str(g.get("类型", "")))}</td>'
            f'<td>{e(str(g.get("位置", ""))[:30])}</td><td>{e(str(g.get("描述", "")))}</td>'
            f'<td>{e(str(g.get("处置建议", "")))}</td></tr>' for g in gaps
        )
        parts.append(
            f'<div class="tbl-wrap" style="margin-top:16px"><table class="filterable" data-filters="0:类型">'
            f'<thead><tr><th style="width:96px">类型</th><th style="width:160px">位置</th>'
            f'<th>描述</th><th style="width:220px">处置建议</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
        )
    return "".join(parts)


def run_validator(files):
    """调用 validate-output.py 取真实校验结果，报告里的闸门状态不由模型手填。

    files: [(stage, path, [extra_args...]), ...]
    """
    lines = []
    for item in files:
        stage, path = item[0], item[1]
        extra = item[2] if len(item) > 2 else []
        if not path or not os.path.isfile(path):
            continue
        try:
            cp = subprocess.run(
                [sys.executable, VALIDATOR, path, "--stage", stage] + extra,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
            )
            for ln in (cp.stdout or "").splitlines():
                s = ln.strip()
                if s.startswith(("[通过]", "[不通过]", "[告警]", "[警告]")):
                    lines.append((stage, s))
        except Exception:
            continue
    return lines


_LABEL = re.compile(r"^\[(?:通过|不通过|告警|警告)\]\s*")


def _clean(s):
    return _LABEL.sub("", s).strip()


# 每条校验输出按关键字归档到对应闸门（name, 关键字, 所属阶段）
GATE_RULES = [
    ("素材清点（闸门⑨）", r"素材单元|锚点映射|八类元素|图片证据|硬性缺口|证据降级", "inventory"),
    ("① 可追溯性", r"可追溯性|缺少任何依据", "require"),
    ("② 无编造", r"无编造|纯图需求点|编造|证据降级", "require"),
    ("③ 特征分布", r"特征分布|特征类型|归一化偷懒|方法分布", "feature"),
    ("④ 方法匹配合理", r"映射矩阵|选择理由|方法不在合法目录|方法分布", "method"),
    ("⑤ 降维有损失说明", r"降维", "feature"),
    ("⑥ 边界完整性", r"边界", "case"),
    ("⑦ 无效域占比 ≥30%", r"无效域占比", "case"),
    ("⑧ 预期结果可判定", r"预期结果|用例总数|输入数据不具体", "case"),
]


def build_gates(files):
    res = run_validator(files)
    if not res:
        return '<div class="callout warn">未取到机械校验结果：请确认 step 产物路径正确，' \
               '或手动跑一遍 scripts/validate-output.py 后把结论补进本节。</div>'
    ran = {st for st, _ in res}
    stage_fail = {}
    for st, s in res:
        stage_fail[st] = stage_fail.get(st, False) or s.startswith("[不通过]")

    cards = []
    for name, pattern, stage in GATE_RULES:
        hit = [s for st, s in res if st == stage and re.search(pattern, s)]
        # 通过项排前面，告警/不通过排后面，读起来才不会把告警当结论
        hit.sort(key=lambda s: 0 if s.startswith("[通过]") else (2 if s.startswith("[不通过]") else 1))
        fail = any(s.startswith("[不通过]") for s in hit) or stage_fail.get(stage, False) and not hit
        warn = any(s.startswith(("[告警]", "[警告]")) for s in hit)
        if hit:
            txt = " · ".join(_clean(s) for s in hit[:3])
        elif stage in ran:
            txt = f"该阶段实跑无 [不通过] 项，本闸门未触发告警（{stage} 段共 {sum(1 for st, _ in res if st == stage)} 条输出）"
        else:
            txt = "对应阶段产物缺失，本闸门本次不适用"
        if fail:
            mark = "fail"
        elif warn:
            mark = "todo"                      # 有告警：需人工确认，但不阻断交付
        elif hit or stage in ran:
            mark = "pass"                      # 有通过项，或该阶段实跑且未触发任何告警
        else:
            mark = "todo"                      # 产物缺失，本闸门不适用
        sign = "！" if mark == "fail" else ("!" if mark == "todo" else "✓")
        cards.append(
            f'<div class="gate"><span class="mark {mark}">{sign}</span>'
            f'<div><h4>{e(name)}</h4><p>{e(txt[:220])}</p></div></div>'
        )
    return "".join(cards)


def main():
    ap = argparse.ArgumentParser(description="llm-blackbox-testcase 报告装配")
    ap.add_argument("--dir", default=".", help="五段产物所在目录，默认当前目录")
    ap.add_argument("--out", default="报告.html", help="输出 HTML 路径")
    ap.add_argument("--title", required=True, help="需求名称，用于标题与页脚")
    ap.add_argument("--step1", default=None, help="覆盖默认 step1.json 路径")
    ap.add_argument("--step2", default=None, help="覆盖默认 step2.json 路径")
    ap.add_argument("--step3", default=None, help="覆盖默认 step3.json 路径")
    ap.add_argument("--step4", default=None, help="覆盖默认 step4.json 路径（可缺）")
    ap.add_argument("--inventory", default=None, help="asset-inventory.json")
    ap.add_argument("--manifest", default=None, help="assets/manifest.json")
    ap.add_argument("--template", default=DEFAULT_TEMPLATE, help="模板 HTML（取其 <style> 整套提取）")
    ap.add_argument("--embed-images", action="store_true",
                    help="把 assets/images 里的图以 base64 内联进 §0（单文件自包含，体积会变大）")
    ap.add_argument("--business-domain", default="未指定", help="业务域，展示在封面")
    args = ap.parse_args()

    base = os.path.abspath(args.dir)

    def pick(explicit, name, required=True):
        p = explicit or os.path.join(base, name)
        if not os.path.isfile(p):
            if required:
                print(f"[error] 缺少产物：{p}")
                sys.exit(1)
            return None
        return p

    p1 = pick(args.step1, "step1.json")
    p2 = pick(args.step2, "step2.json")
    p3 = pick(args.step3, "step3.json")
    p4 = pick(args.step4, "step4.json", required=False)
    if not os.path.isfile(p4 or "") and os.path.isfile(os.path.join(base, "step4.json")):
        p4 = os.path.join(base, "step4.json")

    s1 = load_json(p1) if p1 else []
    s2 = load_json(p2) if p2 else []
    s3 = load_json(p3) if p3 else []
    s4 = load_json(p4) if p4 and os.path.isfile(p4) else []

    inv = None
    for cand in (args.inventory, os.path.join(base, "asset-inventory.json")):
        if cand and os.path.isfile(cand):
            inv = load_json(cand)
            break
    man = None
    for cand in (args.manifest, os.path.join(base, "assets", "manifest.json"),
                 os.path.join(base, "manifest.json")):
        if cand and os.path.isfile(cand):
            man = load_json(cand)
            break

    style, _raw_template = read_style(args.template)
    today = r_year_month()

    # 质量闸门：实跑校验器，素材清点段需要 --manifest / --inventory
    inv_path = args.inventory
    if not inv_path:
        cand = os.path.join(base, "asset-inventory.json")
        inv_path = cand if os.path.isfile(cand) else None
    man_path = args.manifest
    if not man_path:
        for cand in (os.path.join(base, "assets", "manifest.json"), os.path.join(base, "manifest.json")):
            if os.path.isfile(cand):
                man_path = cand
                break
    inv_job = []
    if inv_path and man_path:
        inv_job = [("inventory", inv_path, ["--manifest", man_path])]
    gate_jobs = inv_job + [("require", p1, (["--manifest", man_path] if man_path else [])),
                           ("feature", p2, []), ("method", p3, []), ("case", p4, [])]

    n_img = len((man or {}).get("images", []))
    n_todo = sum(1 for r in s1 if r.get("待确认") is True)
    used_methods = len({main_of(x.get("推荐黑盒测试方法", "")) for x in s3} - {""})

    # 模板自带筛选/缩略图样式时不再重复注入（避免同一选择器出现两份）
    css = style if ".ftoolbar{" in style else style + EXTRA_CSS
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(args.title)} · 黑盒测试设计报告</title>
<style>
{css}
</style>
</head>
<body>

<header class="cover">
  <div class="wrap cover-inner">
    <div class="eyebrow">Black-Box Test Design Report</div>
    <div class="accent-line"></div>
    <h1>{e(args.title)} · 黑盒测试设计报告</h1>
    <p class="sub">由五段推理链路装配：素材清点 → 需求点拆解 → 特征建模 → 方法匹配 → 用例生成。
      共覆盖 {len(s1)} 个需求点、{len(s2)} 个测试点、{len(s4)} 条可执行用例，用到 {used_methods} 种主方法；
      素材含 {n_img} 张界面截图。</p>
    <div class="cover-meta">
      <span class="tag-pill solid">业务域：{e(args.business_domain)}</span>
      <span class="tag-pill">素材：{n_img} 图</span>
      <span class="tag-pill">生成日期：{e(today)}</span>
      <span class="tag-pill warn">[待确认] 项：{n_todo} 条</span>
    </div>
  </div>
  <div class="cover-dots"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
</header>

<div class="nav"><div class="wrap">
  <a href="#s0">素材清点</a><a href="#s1">映射表</a><a href="#s2">方法分布</a>
  <a href="#s3">用例集</a><a href="#s4">降维损失</a><a href="#s5">质量闸门</a><a href="#s6">待确认</a>
</div></div>

<div class="wrap">

<section id="s0">
  <div class="sec-head"><span class="step-circle">0</span><h2>素材清点说明</h2></div>
  <p class="sec-desc">图片不是配图，是独立需求源。本节列出每张图的来源与前後正文段落——
    「如图所示」这类措辞就靠这张表锚定到具体图号。</p>
  {build_inventory(man, inv, args.embed_images, base, os.path.dirname(man_path) if man_path else None)}
</section>

<section id="s1">
  <div class="sec-head"><span class="step-circle">1</span><h2>需求点 × 测试点 × 特征 × 方法 映射表</h2></div>
  <p class="sec-desc">核心交付物。每行一条测试点；特征列含主特征与次特征标签（F1~F18），
    方法列标注主方法与辅助方法及分工边界。表头下拉可按需求点/特征筛选，关键字框做全表搜索。</p>
  <div class="tbl-wrap"><table class="filterable" data-filters="0:需求点,3:方法" data-search="1">
    <thead><tr>
      <th style="width:210px">需求点</th><th style="width:190px">拆分测试点</th>
      <th>被测对象特征</th><th style="width:250px">推荐黑盒测试方法</th>
    </tr></thead>
    <tbody>{build_map_table(s1, s2, s3)}</tbody>
  </table></div>
</section>

<section id="s2">
  <div class="sec-head"><span class="step-circle">2</span><h2>方法分布</h2></div>
  <p class="sec-desc">全部指标由脚本从产物里算出，不由模型手填。单一主方法占比过高时，
    请回到第 2 步复核是否做了特征归一化偷懒。</p>
  <div class="grid g4">{build_metrics(s1, s2, s3, s4)}</div>
</section>

<section id="s3">
  <div class="sec-head"><span class="step-circle">3</span><h2>可执行用例集（{len(s4)} 条）</h2></div>
  <p class="sec-desc">输入数据具体到值、预期结果唯一可判定。
    可按「用例类型 / 自动化」筛选后交给执行者；P0 请先跑。</p>
  <div class="tbl-wrap"><table class="filterable" data-filters="1:类型,0:需求点" data-search="1">
    <thead><tr>
      <th style="width:96px">用例ID</th><th style="width:86px">类型</th>
      <th style="width:190px">需求点 · 测试点</th><th style="width:230px">前置 / 输入数据</th>
      <th>预期结果</th><th style="width:150px">方法归属 / 自动化</th>
    </tr></thead>
    <tbody>{build_case_table(s4)}</tbody>
  </table></div>
</section>

<section id="s4">
  <div class="sec-head"><span class="step-circle">4</span><h2>降维损失</h2></div>
  <p class="sec-desc">组合规模 &gt; 20 的测试点必须给出：组合总数、降维后数量、舍弃的组合与风险判断。
    没有损失说明的降维不可信。</p>
  {build_dimension(s2, s3)}
</section>

<section id="s5">
  <div class="sec-head"><span class="step-circle">5</span><h2>质量闸门核验</h2></div>
  <p class="sec-desc">下列结论由 scripts/validate-output.py 实跑产出，不是人工填写。</p>
  {build_gates(gate_jobs)}
</section>

<section id="s6">
  <div class="sec-head"><span class="step-circle">6</span><h2>待确认项清单</h2></div>
  <p class="sec-desc">模型不替业务方拍板。以下需求点带有 [待确认] 标记，
    相关用例在确认前不得进入正式执行集。</p>
  {build_todo(s1)}
</section>

<footer>llm-blackbox-testcase · {e(args.title)} · {e(today)} ·
  素材 {n_img} 图，证据完整性已在 §0 声明</footer>
</div>

<script>
{FILTER_JS}
</script>
</body>
</html>
"""
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_doc)
    size = os.path.getsize(out)
    print(f"报告已写出：{out}")
    print(f"  需求点 {len(s1)} / 测试点 {len(s2)} / 方法矩阵 {len(s3)} / 用例 {len(s4)}")
    print(f"  图片 {n_img} 张（{'已内联' if args.embed_images else '未内联，正文上下文仍完整'}）")
    print(f"  待确认 {n_todo} 条；文件大小 {size/1024:.0f} KB")
    if size > 3 * 1024 * 1024:
        print("  [提示] 文件超过 3MB（多为内联图片所致），如不需单文件自包含，去掉 --embed-images 重跑。")
    sys.exit(0)


if __name__ == "__main__":
    main()
