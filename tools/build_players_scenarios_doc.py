"""Generate docs/players_scenarios.html from live playlist builders.

Includes seat formations for every Players band and C1/C5 sub-level (T1–T5).
"""
from __future__ import annotations

import html
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as p  # noqa: E402


OUT = os.path.join(ROOT, "docs", "players_scenarios.html")
A_ORDER = ["A1", "A2", "A3", "A4", "A5", "A6"]
B_ORDER = ["B1", "B2", "B3", "B4", "B5", "B6"]
ACTIVE = ["A", "B"]


def esc(s) -> str:
    return html.escape(str(s or ""))


def web_uri(path: str) -> str:
    """Map a repo file under static/ to a browser URL served by FastAPI."""
    if not path:
        return ""
    abs_path = os.path.abspath(path)
    static_root = os.path.abspath(os.path.join(ROOT, "static"))
    try:
        rel = os.path.relpath(abs_path, static_root)
    except ValueError:
        return ""
    if rel.startswith(".."):
        return ""
    return "/static/" + rel.replace("\\", "/")


def img_tag(path: str) -> str:
    if not path or not os.path.isfile(path):
        return f'<div class="miss">{esc(path)}</div>'
    src = web_uri(path) or path
    return (
        f'<figure><img src="{esc(src)}" '
        f'alt="{esc(os.path.basename(path))}"/>'
        f"<figcaption>{esc(os.path.basename(path))}</figcaption></figure>"
    )


def media_tag(path: str, embed: bool = True) -> str:
    if not path:
        return '<div class="meta">empty</div>'
    name = os.path.basename(path)
    if not embed:
        return f'<div class="meta">{esc(name)}</div>'
    low = str(path).lower()
    if low.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
        if not os.path.isfile(path):
            return f'<div class="miss">{esc(name)}</div>'
        src = web_uri(path) or path
        return (
            f'<video src="{esc(src)}" muted playsinline controls preload="metadata"></video>'
            f'<div class="meta">{esc(name)}</div>'
        )
    return img_tag(path)


def goal_seat_set(field_screens: dict) -> set:
    """Seats marked as goals (strip L/R mouth suffixes for grid highlight)."""
    seats = set()
    for fid in ("A", "B"):
        for raw in (field_screens or {}).get(fid) or []:
            g = str(raw or "").strip().upper()
            if not g:
                continue
            seats.add(g)
            if len(g) >= 2 and g[-1] in "LR" and g[-2].isdigit():
                seats.add(g[:-1])
    return seats


def field_grid(imgs: dict, goals: set, order: list, embed: bool = True) -> str:
    chunks = ['<div class="grid">']
    for sid in order:
        path = imgs.get(sid)
        base = sid.upper()
        is_goal = base in goals or sid in goals
        cls = "cell goal" if is_goal else ("cell" if path else "cell empty")
        g = " GOAL" if is_goal else ""
        chunks.append(
            f'<div class="{cls}"><div class="role">{sid}{g}</div>'
            f"{media_tag(path, embed=embed)}</div>"
        )
    chunks.append("</div>")
    return "".join(chunks)


def render_action(entry: dict, heading: str, embed: bool = True) -> str:
    imgs = entry.get("screen_images") or {}
    goals = goal_seat_set(entry.get("field_screens") or {})
    goal_label = ",".join(
        sorted(
            {
                str(g)
                for fid in ("A", "B")
                for g in ((entry.get("field_screens") or {}).get(fid) or [])
            }
        )
    )
    bits = [
        f"<h4>{esc(heading)} — goals {esc(goal_label)} — "
        f"require_all={entry.get('require_all_goals')} — "
        f"on={entry.get('on_ms')}ms</h4>",
        '<p class="meta">Field A</p>',
        field_grid(imgs, goals, A_ORDER, embed=embed),
        '<p class="meta">Field B</p>',
        field_grid(imgs, goals, B_ORDER, embed=embed),
    ]
    return "".join(bits)


def render_playlist(
    playlist: list,
    *,
    embed: bool = True,
    group_by_test: bool = True,
) -> str:
    if not playlist:
        return '<p class="miss">No actions generated.</p>'
    parts = []
    current_test = None
    for entry in playlist:
        if not isinstance(entry, dict):
            continue
        test_num = int(entry.get("test_num") or 0)
        action_n = int(entry.get("action_in_set") or entry.get("action_num") or 0)
        if group_by_test and test_num != current_test:
            current_test = test_num
            parts.append(f"<h3>In-set test {test_num}</h3>")
        heading = f"a{action_n}"
        if entry.get("action"):
            heading = f"a{action_n} — {entry.get('action')}"
        if entry.get("ap_action") or entry.get("aep_dual_pass"):
            heading += " (AP)"
        parts.append(render_action(entry, heading, embed=embed))
    return "".join(parts)


def timing_row(label: str, on_ms: int, gap_ms: int) -> str:
    return (
        f"<tr><td>{esc(label)}</td><td>{on_ms}</td><td>{gap_ms}</td></tr>"
    )


def main() -> None:
    # Stabilize unseeded procedural packs for a reproducible snapshot.
    random.seed(20261127)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    parts = []
    parts.append(
        """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>SIMUST Players scenarios</title>
<style>
body{font-family:Segoe UI,system-ui,sans-serif;margin:24px;background:#0f172a;color:#e2e8f0;line-height:1.45}
h1,h2,h3,h4{color:#f8fafc} a{color:#93c5fd}
.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:12px 0}
.cell{background:#1e293b;border:1px solid #334155;border-radius:8px;min-height:110px;padding:6px;text-align:center}
.cell.goal{outline:2px solid #f59e0b}
.cell.empty{opacity:.45}
.cell img,.cell figure img{max-width:100%;max-height:90px;object-fit:contain}
figure{margin:0} figcaption{font-size:10px;word-break:break-all;color:#94a3b8}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;margin:2px;background:#334155}
.role{font-weight:700;font-size:12px}
.meta{color:#94a3b8;font-size:13px}
.section{margin:28px 0;padding:16px;background:#111827;border-radius:12px;border:1px solid #1f2937}
.sub{margin:20px 0;padding:12px;background:#0b1220;border-radius:10px;border:1px solid #1f2937}
table{border-collapse:collapse;width:100%;font-size:13px}
td,th{border:1px solid #334155;padding:6px 8px;text-align:left}
th{background:#1e293b}
.toc a{display:block;margin:4px 0}
.toc .subtoc{margin-left:16px}
.miss{font-size:11px;color:#f87171}
video{max-width:100%;max-height:90px}
code{color:#fde68a}
</style></head><body>
<h1>SIMUST Players scenarios</h1>
<p class="meta">Auto-generated from live playlist builders. Amber outline = goal seat
(including sided L/R mouths). Empty seats have no media. Procedural bands
(Entry / Activated / HP / Elite 1) show a seeded snapshot; re-runs may differ
where builders use unseeded random.</p>
"""
    )

    toc = [
        ("#entry", "Entry Players (C1) — warehouse stills"),
        ("#activated", "Activated Players (C1)"),
        ("#hp", "High Performance Players (C1)"),
        ("#elite1", "Elite Players 1 (C1)"),
        ("#elite2", "Elite Players 2 (C5) — scripted 5×9 stills"),
        ("#wc", "World Class Players (C1) — scripted 5×9 videos"),
    ]
    parts.append('<div class="section"><h2>Contents</h2><div class="toc">')
    for href, label in toc:
        parts.append(f'<a href="{href}">{esc(label)}</a>')
        if href in ("#entry", "#activated", "#hp", "#elite1", "#elite2", "#wc"):
            for tn in range(1, 6):
                parts.append(
                    f'<a class="subtoc" href="{href}-t{tn}">'
                    f"{esc(label.split('(')[0].strip())} T{tn}</a>"
                )
    parts.append("</div></div>")

    # --- Entry catalog + formations ---
    parts.append('<div class="section" id="entry"><h2>Entry Players (C1)</h2>')
    parts.append(
        "<p>Images from <code>static/Players-Images</code>. "
        "Goals = Teammate-PL-*-02-B (Pass and Rebound). AP second = another "
        "Teammate-PL. Distractors = opponents (+ teammate from T3). Unique "
        "person # per action. 4 lit screens. Formations below: each "
        "operator sub-level C1.T1–T5 (5 in-set tests × 10 actions).</p>"
    )
    cat = p._players_warehouse_catalog()
    parts.append(
        "<table><tr><th>Role</th><th>Folder / rule</th><th>Count</th>"
        "<th>Samples</th></tr>"
    )
    role_help = {
        "rebound": "Pass and Rebound — Teammate-PL-*-02/05 (center / AP goals)",
        "cross_left": "Crossball — left (sided pass L)",
        "cross_right": "Crossball — right (sided pass R)",
        "asking": "Pass and Rebound — Asking-Ball",
        "teammate": "Players neutral — Teammate-PL (never a goal)",
        "opponent": "Players neutral — Opponent-PL (never a goal)",
        "defender": "Players-Defending (never a goal)",
    }
    for role, help_txt in role_help.items():
        pool = cat.get(role) or []
        samples = " ".join(esc(os.path.basename(x[0])) for x in pool[:3])
        parts.append(
            f'<tr><td><span class="badge">{esc(role)}</span></td>'
            f"<td>{esc(help_txt)}</td><td>{len(pool)}</td><td>{samples}</td></tr>"
        )
    parts.append("</table>")

    for series in range(1, 6):
        on_ms, gap_ms = p._entry_series_timing_ms(series)
        pl = p._build_entry_s0_playlist(series, ACTIVE)
        parts.append(
            f'<div class="sub" id="entry-t{series}">'
            f"<h3>Entry C1.T{series} — on={on_ms}ms gap={gap_ms}ms — "
            f"{len(pl)} actions</h3>"
        )
        parts.append(render_playlist(pl, embed=True))
        parts.append("</div>")
    parts.append("</div>")

    # --- Activated ---
    parts.append(
        '<div class="section" id="activated"><h2>Activated Players (C1)</h2>'
        "<p>Stills from <code>static/Players-Images</code> warehouse "
        "(not <code>static/players/Activated</code>). "
        "5 lit screens; center goals = Teammate-PL-*-02-B; AP second = another "
        "Teammate-PL. No pass-left/right. C1.T1–T2: 30% AP; C1.T3–T5: 50% AP.</p>"
    )
    for series in range(1, 6):
        on_ms, gap_ms = p._entry_series_timing_ms(series)
        pl = p._build_activated_s0_playlist(series, ACTIVE)
        parts.append(
            f'<div class="sub" id="activated-t{series}">'
            f"<h3>Activated C1.T{series} — on={on_ms}ms gap={gap_ms}ms — "
            f"{len(pl)} actions</h3>"
        )
        parts.append(render_playlist(pl, embed=True))
        parts.append("</div>")
    parts.append("</div>")

    # --- High Performance ---
    parts.append(
        '<div class="section" id="hp"><h2>High Performance Players (C1)</h2>'
        "<p>Stills from <code>static/Players-Images</code>. "
        "Goals = Teammate-PL-*-02-B; AP second = Teammate-PL; traps = OffSide-Trap "
        "+ posts at warehouse root. Field B mirrors Field A.</p>"
    )
    for series in range(1, 6):
        on_ms, gap_ms = p._entry_series_timing_ms(series)
        pl = p._build_high_performance_s0_playlist(series, ACTIVE)
        parts.append(
            f'<div class="sub" id="hp-t{series}">'
            f"<h3>High Performance C1.T{series} — on={on_ms}ms gap={gap_ms}ms — "
            f"{len(pl)} actions</h3>"
        )
        parts.append(render_playlist(pl, embed=True))
        parts.append("</div>")
    parts.append("</div>")

    # --- Elite Players 1 ---
    parts.append(
        '<div class="section" id="elite1"><h2>Elite Players 1 (C1 / S0)</h2>'
        "<p>Dual-field pack from <code>static/Players-Images</code> "
        "(Teammate-PL-*-02-B / AP Teammate-PL / Crossball L-R from T3 / "
        "SIMUST-ASking-Ball). Lit count grows with sub-level (3→4→6 per field). "
        "Not the scripted Players 2 pack.</p>"
    )
    for series in range(1, 6):
        on_ms, gap_ms = p._entry_series_timing_ms(series)
        pl = p._build_elite_s0_playlist(series)
        parts.append(
            f'<div class="sub" id="elite1-t{series}">'
            f"<h3>Elite Players 1 C1.T{series} — on={on_ms}ms gap={gap_ms}ms — "
            f"{len(pl)} actions</h3>"
        )
        parts.append(render_playlist(pl, embed=True))
        parts.append("</div>")
    parts.append("</div>")

    # --- Elite Players 2 (scripted; seats identical across series) ---
    parts.append(
        '<div class="section" id="elite2"><h2>Elite Players 2 (C5 / S4)</h2>'
        "<p>Stills from <code>static/players/Elite/players2</code>. "
        "Tests 2–5 rotate actions 1–7 clockwise on A1…A6→B1…B6; "
        "actions 8–9 fixed (posts on Field B). Seat plans are identical for "
        "C5.T1–T5; only On/Gap shortens (−5% per sub-level).</p>"
    )
    parts.append(
        "<table><tr><th>Sub-level</th><th>On (ms)</th><th>Gap (ms)</th></tr>"
    )
    for series in range(1, 6):
        on_ms, gap_ms = p._wc_players_series_timing_ms(series)
        parts.append(timing_row(f"C5.T{series}", on_ms, gap_ms))
    parts.append("</table>")
    for series in range(1, 6):
        parts.append(f'<div id="elite2-t{series}"></div>')
    pl_e2 = p._build_elite_players2_playlist(1)
    parts.append(
        f"<h3>Seat formations (C5.T1–T5 share these layouts) — "
        f"{len(pl_e2)} actions</h3>"
    )
    parts.append(render_playlist(pl_e2, embed=True))
    parts.append("</div>")

    # --- World Class ---
    parts.append(
        '<div class="section" id="wc"><h2>World Class Players (C1 / S0) — videos</h2>'
        "<p>Same seat plans as Elite Players 2. Media from "
        "<code>static/Players-Videos</code>. Center goals = Teammate-AskingForBall "
        "(folder 02, never pass.png / opponents). Cross L/R = any Left/Right clip "
        "from folder 03 (correct only if ball enters goal). Posts stay stills. "
        "a8: B2 Neutral-Duo, B5 OffSide-Trap-Right, goals A1 or B7. "
        "a9: B1 Neutral-Duo, B6 defender-Neutral-06, goal B7. "
        "No duplicate video in an action; tests reuse the same clips. "
        "C1.T1 On/Gap ×2.4. Dual require_all (e.g. a7): first hit clears that seat only. "
        "Timing −5% per sub-level after T1 baseline.</p>"
    )
    parts.append(
        "<table><tr><th>Sub-level</th><th>On (ms)</th><th>Gap (ms)</th></tr>"
    )
    for series in range(1, 6):
        on_ms, gap_ms = p._wc_players_series_timing_ms(series)
        if series == 1:
            scale = float(p.WC_PLAYERS_C1T1_TIME_SCALE)
            on_ms, _ = p._snap_ms_to_display_fps(float(on_ms) * scale)
            gap_ms, _ = p._snap_ms_to_display_fps(float(gap_ms) * scale)
        parts.append(timing_row(f"C1.T{series}", on_ms, gap_ms))
    parts.append("</table>")

    # Full video formations for each sub-level (person picks can vary by series).
    for series in range(1, 6):
        pl = p._build_world_class_s0_playlist(series)
        on_ms = pl[0].get("on_ms") if pl else "?"
        gap_ms = pl[0].get("gap_ms") if pl else "?"
        parts.append(
            f'<div class="sub" id="wc-t{series}">'
            f"<h3>World Class C1.T{series} — on={on_ms}ms gap={gap_ms}ms — "
            f"{len(pl)} actions</h3>"
        )
        parts.append(render_playlist(pl, embed=True))
        parts.append("</div>")
    parts.append("</div>")

    parts.append(
        '<p class="meta">Generated by tools/build_players_scenarios_doc.py</p>'
        "</body></html>"
    )

    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("".join(parts))
    print(f"Wrote {OUT} ({os.path.getsize(OUT)} bytes)")


if __name__ == "__main__":
    main()
