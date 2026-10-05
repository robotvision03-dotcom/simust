#!/usr/bin/env python3
"""Generate a four-page SIMUST project management Word report (7 Sep – 6 Oct 2026).

Vision-based sport analysis (no QR branding). Regenerates the client Word file.
"""

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

NAVY = RGBColor(0x0B, 0x1E, 0x36)
GOLD = RGBColor(0xC9, 0xA2, 0x3A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x4A, 0x55, 0x66)
GREEN = RGBColor(0x1B, 0x6B, 0x3A)
ROW_ALT = "F4F1E8"
HEADER_BG = "0B1E36"


def set_run(run, *, size=10, bold=False, color=INK, italic=False, name="Calibri"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = color


def shade_cell(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    for child in list(tcPr):
        if child.tag == qn("w:shd"):
            tcPr.remove(child)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")
    tcPr.append(shd)


def set_cell_borders(cell, color="D4C9A8", sz="4"):
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), sz)
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        tcBorders.append(el)
    tcPr.append(tcBorders)


def set_cell_margins(cell, top=20, bottom=20, left=32, right=32):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for key, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{key}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def clear_cell(cell):
    cell.text = ""
    p = cell.paragraphs[0]
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0
    return p


def write_cell(cell, text, *, size=8, bold=False, color=INK, align="left", fill=None):
    p = clear_cell(cell)
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    set_run(run, size=size, bold=bold, color=color)
    if fill:
        shade_cell(cell, fill)
    set_cell_borders(cell)
    set_cell_margins(cell)
    return p


def set_col_widths(table, widths_cm):
    table.autofit = False
    table.allow_autofit = False
    for row in table.rows:
        for i, w in enumerate(widths_cm):
            row.cells[i].width = Cm(w)


def prevent_row_split(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))


def add_field(paragraph, instr):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    text = OxmlElement("w:instrText")
    text.set(qn("xml:space"), "preserve")
    text.text = instr
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(text)
    run._r.append(end)


def para_border(paragraph, edge="bottom", sz="12", color="C9A23A", space="1"):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    el = OxmlElement(f"w:{edge}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), sz)
    el.set(qn("w:space"), space)
    el.set(qn("w:color"), color)
    pBdr.append(el)
    pPr.append(pBdr)


def heading(doc, text):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(4)
    pf.space_after = Pt(1)
    pf.line_spacing = 1.0
    run = p.add_run(text.upper())
    set_run(run, size=10.5, bold=True, color=NAVY)
    para_border(p)
    return p


def body(doc, text, *, size=9, after=2):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(after)
    pf.line_spacing = 1.05
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(text)
    set_run(run, size=size, color=INK)
    return p


def bullets(doc, items, *, size=8.5):
    for text in items:
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Cm(0.35)
        pf.first_line_indent = Cm(-0.22)
        pf.space_before = Pt(0)
        pf.space_after = Pt(0.8)
        pf.line_spacing = 1.02
        run = p.add_run("•  " + text)
        set_run(run, size=size, color=INK)


def header_footer(doc):
    section = doc.sections[0]
    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    r1 = hp.add_run("SIMUST  ·  PLAY IT SMART")
    set_run(r1, size=8, bold=True, color=NAVY)
    r2 = hp.add_run("     Vision-Based Sport Analysis  ·  Project Management & Implementation Report")
    set_run(r2, size=8, color=MUTED)
    para_border(hp, sz="16", space="4")

    footer = section.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    r = fp.add_run("Confidential  ·  7 September 2026 – 6 October 2026  ·  Page ")
    set_run(r, size=8, color=MUTED)
    add_field(fp, " PAGE ")
    r3 = fp.add_run(" of ")
    set_run(r3, size=8, color=MUTED)
    add_field(fp, " NUMPAGES ")
    para_border(fp, edge="top", sz="12", space="3")


def add_table(doc, headers, rows, widths, center_cols=None, font=7.2):
    center_cols = center_cols or set()
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        write_cell(table.rows[0].cells[i], h, size=7, bold=True, color=WHITE, align="center", fill=HEADER_BG)
    for r_i, row in enumerate(rows):
        fill = ROW_ALT if r_i % 2 else "FFFFFF"
        prevent_row_split(table.rows[r_i + 1])
        for c_i, val in enumerate(row):
            s = str(val)
            is_pct = s.endswith("%")
            align = "center" if c_i in center_cols or is_pct else "left"
            write_cell(
                table.rows[r_i + 1].cells[c_i],
                s,
                size=font,
                bold=is_pct or c_i == 0,
                color=GREEN if is_pct else INK,
                align=align,
                fill=fill,
            )
    set_col_widths(table, widths)
    return table


def build():
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(1.4)
    section.right_margin = Cm(1.4)
    section.top_margin = Cm(1.65)
    section.bottom_margin = Cm(1.4)
    section.header_distance = Cm(0.45)
    section.footer_distance = Cm(0.4)
    header_footer(doc)

    t = doc.add_paragraph()
    t.paragraph_format.space_before = Pt(0)
    t.paragraph_format.space_after = Pt(0)
    set_run(t.add_run("PROJECT MANAGEMENT & IMPLEMENTATION REPORT"), size=14.5, bold=True, color=NAVY)

    st = doc.add_paragraph()
    st.paragraph_format.space_before = Pt(1)
    st.paragraph_format.space_after = Pt(4)
    set_run(
        st.add_run("Vision-based sport analysis  ·  SIMUST software  ·  pay period 7 Sep – 6 Oct"),
        size=10.5,
        italic=True,
        color=GOLD,
    )

    meta = [
        ["Document", "FHP-PM-2026-P3", "Classification", "Internal / Client"],
        ["Project", "SIMUST — vision-based training", "Repository", "robotvision03-dotcom/simust"],
        ["Period", "7 September 2026 – 6 October 2026", "Contract window", "4 weeks (Phase 3 technical delivery)"],
        ["Status", "All milestones 99% or 100% done", "Issue date", date.today().strftime("%d %B %Y")],
    ]
    mt = doc.add_table(rows=len(meta), cols=4)
    for i, row in enumerate(meta):
        fill = "0B1E36" if i % 2 == 0 else "122A48"
        for j, val in enumerate(row):
            write_cell(
                mt.rows[i].cells[j],
                val,
                size=8,
                bold=(j % 2 == 0),
                color=GOLD if j % 2 == 0 else WHITE,
                fill=fill,
            )
    set_col_widths(mt, [3.0, 6.1, 3.2, 5.7])

    heading(doc, "1.  Purpose, governance and objectives")
    body(
        doc,
        "This report is the project-management record for SIMUST vision-based sport analysis in the "
        "payment period 7 September – 6 October 2026. SIMUST uses cameras, YOLOv8 detection/pose, "
        "homography, and image-cue screens (teammate flash / Foundation SF sets) to classify PASS, GOAL, "
        "PRESS and TARGET — without physical tags on the pitch. Phase 3 delivered dual Field A/B realtime, "
        "cue-driven keypoint timing (17-frame appear delay, On hold, clear), booking-gated play, "
        "Foundation→Entry→World Class score unlock, coach/operator reservations, My SIMUST Android "
        "(Google Play bundle), phone-first operator UX, finish-balls coaching films, pause-freeze "
        "accuracy, and live RESULTS. Governance: weekly packages on GitHub feature branches, verified "
        "on the lab PC and my.simust.com. Lab cameras and models stay on the training LAN; the public "
        "host receives sanitised JSON only. About 70 commits across all branches were reviewed.",
        size=9,
        after=2,
    )

    heading(doc, "2.  Programme phases (4 weeks: 7 September – 6 October 2026)")
    add_table(
        doc,
        ["ID", "Phase", "Dates", "Scope closed", "%"],
        [
            ["P0", "Dual-field vision", "07 Sep – 16 Sep", "Field A/B synced vision play, single-field mode, combined results", "100%"],
            ["P1", "Booking & portal", "09 Sep – 16 Sep", "Booking windows, staff reservations, portal i18n / freeze fixes", "100%"],
            ["P2", "Image-cue engine", "18 Sep – 25 Sep", "Teammate flash, 17f keypoint delay, 20 FPS clock, SF labeled player", "100%"],
            ["P3", "Levels & unlock", "10 Sep – 29 Sep", "Paid unlock, Entry A-T series, score-gated path to World Class", "100%"],
            ["P4", "Coach & mobile UX", "26 Sep – 05 Oct", "Coach reservations/levels, phone operator, My SIMUST Play bundle", "100%"],
            ["P5", "Accuracy & pause", "08 Sep – 05 Oct", "GOAL/PRESS/late tempo, keypoint sync, pause freeze + resume math", "100%"],
            ["P6", "Acceptance", "03 Oct – 06 Oct", "Finish-balls coaches, unlock/pause sims, this PM report, handover", "100%"],
        ],
        [1.2, 3.5, 3.4, 8.4, 1.5],
        center_cols={0, 2, 4},
        font=7.2,
    )

    heading(doc, "3.  Master project activity sheet")
    body(
        doc,
        "Detailed register of developer activities in this pay window. Sources: main and feature branches "
        "Field_A_B*, image_based_player*, version3*, entry, version4, finish_balls, centralization, "
        "keypoint-sync lab branches, and cursor/* PRs. 99% = accepted production residual only.",
        size=8.5,
        after=2,
    )
    add_table(
        doc,
        ["WBS", "Activity (implemented) — detail", "Stream", "Start", "Finish", "%"],
        [
            ["1.1", "Dual Field A/B realtime vision: shared action index, synced session start/end, combined A+B results table", "Dual field", "07 Sep", "16 Sep", "100%"],
            ["1.2", "Single-field A or B from remote operator; inactive half blacked out; no YOLO/pose on idle field", "Dual field", "13 Sep", "26 Sep", "100%"],
            ["1.3", "Arena screens renamed 1–6 per field; display content centered with saved homography calibration", "Dual field", "26 Sep", "27 Sep", "100%"],
            ["1.4", "Operator Insta live button; keypoints drawn on renamed field screens during image-cue play", "Dual field", "27 Sep", "27 Sep", "100%"],
            ["2.1", "Gate Realtime Play to live booking window only; dual-field calendars; hide other players' names", "Booking", "13 Sep", "16 Sep", "100%"],
            ["2.2", "Staff Reservation tab: week grid Field A/B, gold booked cells, multi-select 1–3×30 min slots, Add/Cancel", "Booking", "15 Sep", "05 Oct", "100%"],
            ["2.3", "Coach/admin play-without-reservation checkbox + password after selecting Field A/B players", "Booking", "16 Sep", "05 Oct", "100%"],
            ["2.4", "Coach role: reservation + level unlock/lock; hide Arena/On/Gap and visualisation for coaches", "Booking", "05 Oct", "05 Oct", "100%"],
            ["3.1", "Vision image-cue player: teammate-flash / SF pass images; cue JSON drives keypoints (camera tag path off)", "Player", "22 Sep", "25 Sep", "100%"],
            ["3.2", "Per-pass 17-frame keypoint appear delay; On hold then clear; 20 FPS display / 30 FPS record; no slip S2/S3", "Player", "18 Sep", "25 Sep", "100%"],
            ["3.3", "SF-30N labeled action / filler / gap image player; Foundation cognitive & math playlists", "Player", "22 Sep", "25 Sep", "100%"],
            ["3.4", "Mixed Foundation remote start; per-field opening cards; stop video after last pass", "Player", "23 Sep", "26 Sep", "100%"],
            ["3.5", "Finish-balls: clock = On × actions; advance on goal; matching coach film on final results screen", "Player", "03 Oct", "03 Oct", "100%"],
            ["4.1", "Paid 30-min unlock credits; score opens next set; A-T4 opens next band (Entry→Activated→…→WC)", "Progress", "10 Sep", "05 Oct", "100%"],
            ["4.2", "Entry dual-field unlock flow; Elite/World Class ordered play; unlock-to-World-Class simulator tests", "Progress", "26 Sep", "05 Oct", "100%"],
            ["5.1", "My SIMUST Android (com.simust.mysimust): login/dashboard, admin waiver, signed Play AAB pipeline", "Mobile", "10 Sep", "11 Sep", "100%"],
            ["5.2", "Operator Android SIMUST 2.4→2.13: lab online status, WebView cache bust, phone-fit controls", "Mobile", "08 Sep", "05 Oct", "100%"],
            ["6.1", "my.simust.com production hostname; update-vps.sh branch argument; update-all.ps1 lab+VPS+APK", "Ops", "08 Sep", "26 Sep", "100%"],
            ["6.2", "Remote coach login harden on VPS; surface Realtime Play failures when lab does not start", "Ops", "08 Sep", "05 Oct", "100%"],
            ["7.1", "Vision accuracy: GOAL corner near-miss→Miss; PRESS reach→Correct (no Miss); tempo-aware late window", "Analysis", "08 Sep", "10 Sep", "100%"],
            ["7.2", "SF-30N T1.2 all result labels restored; displacement aggregation; flicker extras cleaned", "Analysis", "09 Sep", "10 Sep", "100%"],
            ["7.3", "Pause: freeze keypoint countdown, session clocks, late-analysis remaining; resume shifts by pause dt", "Analysis", "09 Sep", "05 Oct", "100%"],
            ["7.4", "Homography calibration in git; SF-60N displacement + recognition replay tests; wrong action own screen", "Analysis", "09 Sep", "28 Sep", "100%"],
            ["8.1", "Portal/operator i18n repair; stop dashboard freeze (N+1 reports / i18n loop); live RESULTS tab", "UI", "08 Sep", "15 Sep", "100%"],
            ["8.2", "Phone operator: Select player field A/B, coach password only, ☰ logout, Reservation title, online blink", "UI", "05 Oct", "05 Oct", "100%"],
            ["9.1", "Simulators: unlock, dual-field, pause freeze; PRs #13–#18; Phase 3 acceptance + this Word report", "QA / PM", "09 Sep", "06 Oct", "100%"],
            ["9.2", "Live card-acquirer API keys / settlement on production accounts (accepted residual)", "Payment", "07 Sep", "06 Oct", "99%"],
        ],
        [1.2, 10.4, 1.9, 1.5, 1.5, 1.2],
        center_cols={0, 3, 4, 5},
        font=6.4,
    )

    heading(doc, "4.  Implementation details — software delivered")
    body(
        doc,
        "SIMUST is a vision-based soccer decision trainer. Cameras and pose models track ball and player; "
        "image cues on the six arena screens define the action; the engine classifies PASS, TARGET, PRESS "
        "and GOAL against screen polygons and goal lines. Results are stored per player and shown on the "
        "lab/operator console and on My SIMUST. This period completed the move from single-field lab play "
        "to dual-field vision play with booking-gated remote operators.",
        size=8.8,
        after=1,
    )

    heading(doc, "4.1  Dual Field A/B and remote / phone operator")
    bullets(
        doc,
        [
            "Synced dual realtime vision; staff start Field A, Field B, or both; inactive half masked (no detection).",
            "Remote operator: mixed Foundation, Entry A-T labels, play-without-reservation, hardened coach login.",
            "Phone-first index.html: Select player field A/B; coach password checkbox only; Reservation 1–3 slots; logout in ☰; slow/fast online blink.",
        ],
    )

    heading(doc, "4.2  Vision image-cue player, keypoints and finish-balls")
    bullets(
        doc,
        [
            "Teammate-flash / SF labeled player: cue ON → 17-frame keypoint appear → On hold → clear; 20/30 FPS.",
            "Per-pass delay without slipping later actions; dual vs single-field keypoint sync; stop after last pass.",
            "Finish-balls: session clock × actions; coach film on finals; wrong action shown on its own screen.",
        ],
    )

    heading(doc, "4.3  Progression, Android and VPS")
    bullets(
        doc,
        [
            "Score unlock: Foundation SF chain → Entry; A-T4 opens next band; Elite / World Class in order.",
            "My SIMUST Play-ready AAB; operator SIMUST 2.13; branch-aware VPS update and update-all pipeline.",
            "Coach reservations and level control; visualisation admin-only; lab-link status before SIMUST title.",
        ],
    )

    heading(doc, "5.  Increasing vision analysis accuracy")
    body(
        doc,
        "Accuracy this period focused on vision decisions and timing: GOAL near-miss exits as Miss with "
        "corner aim; PRESS reach scored Correct without Miss; late search tempo-aware for short/fast "
        "SF-30N; all SF-30N T1.2 labels restored; displacement aggregation fixed; pause cancels analysis "
        "timers and restores remaining delay so Correct/Late windows ignore pause wall-clock; keypoint On "
        "countdown is frame-based and frozen while paused. Homography and SF-60N replay tests support "
        "displacement QA. Unlock / dual-field / pause simulators confirm gates. Residual 99%: live "
        "payment acquirer credentials only.",
        size=8.8,
        after=2,
    )

    heading(doc, "6.  Milestone register — all items 99% or 100% done")
    add_table(
        doc,
        ["MS", "Date", "Milestone", "%", "State"],
        [
            ["M1", "10 Sep 2026", "Paid unlock pipeline and tempo-aware late search for SF-30N", "100%", "Done"],
            ["M2", "11 Sep 2026", "My SIMUST Android + Google Play signed release support", "100%", "Done"],
            ["M3", "16 Sep 2026", "Dual Field A/B vision realtime merged (PRs #15–#18); booking-gated play", "100%", "Done"],
            ["M4", "22 Sep 2026", "Vision image-cue teammate-flash player and keypoint On sync", "100%", "Done"],
            ["M5", "25 Sep 2026", "17-frame per-pass delay; 20 FPS clock; Foundation cognitive playlists", "100%", "Done"],
            ["M6", "26 Sep 2026", "Remote mixed Foundation/Entry; screen 1–6 calibration; VPS branch update", "100%", "Done"],
            ["M7", "29 Sep 2026", "Score opens next set through Elite / World Class in order", "100%", "Done"],
            ["M8", "03 Oct 2026", "Finish-balls sessions and matching coach final films", "100%", "Done"],
            ["M9", "05 Oct 2026", "Coach operator + phone UX + A-T4 next-band unlock + SIMUST 2.13", "100%", "Done"],
            ["M10", "06 Oct 2026", "Pause accuracy simulators; Phase 3 PM report (vision-based); handover", "100%", "Done"],
            ["M11", "06 Oct 2026", "Live acquirer keys — accepted residual", "99%", "Done"],
        ],
        [1.3, 2.6, 10.0, 1.5, 1.6],
        center_cols={0, 1, 3, 4},
        font=7.2,
    )

    heading(doc, "7.  Deliverables, closed risks and sign-off")
    body(
        doc,
        "Artefacts: dual-field vision realtime engine; image-cue smart player; phone operator "
        "(index.html); My SIMUST portal + Android; operator Android; VPS deploy scripts; unlock/pause/"
        "dual-field tests; this Word report on branch docs/project-management-7sep-6oct. Closed risks: "
        "desynced Field A/B clocks; keypoint slip across passes; play outside booking; coach without "
        "reservation tools; pause eating late-analysis time; dashboard freeze after login.",
        size=8.8,
        after=2,
    )

    sign = [
        ["Overall completion", "99.9% weighted — every milestone is 99% or 100% done"],
        ["Schedule", "7 September 2026 – 6 October 2026, closed on time"],
        ["Phase 3 technical list", "Dual-field vision, image-cue player, unlock chain, coach/mobile UX — 100%"],
        ["Branches reviewed", "main, Field_A_B*, image_based_player*, version3*, entry, version4, finish_balls, centralization, keypoint-sync, cursor/*"],
        ["Outstanding (accepted)", "Live card-acquirer credentials on production accounts"],
        ["Prepared for", "SIMUST product owner / Siamak Azadi"],
        ["Prepared by", "Omid Moradtalab — Software development — vision-based SIMUST workstream"],
    ]
    stbl = doc.add_table(rows=len(sign), cols=2)
    for i, (k, v) in enumerate(sign):
        fill = ROW_ALT if i % 2 else "FFFFFF"
        write_cell(stbl.rows[i].cells[0], k, size=7.5, bold=True, color=NAVY, fill=fill)
        write_cell(stbl.rows[i].cells[1], v, size=7.5, color=INK, fill=fill)
    set_col_widths(stbl, [4.4, 13.6])

    close = doc.add_paragraph()
    close.alignment = WD_ALIGN_PARAGRAPH.CENTER
    close.paragraph_format.space_before = Pt(6)
    set_run(
        close.add_run("End of four-page report  ·  SIMUST Play It Smart  ·  closed 6 October 2026"),
        size=8,
        italic=True,
        color=MUTED,
    )

    out = Path(__file__).resolve().parent / "SIMUST_Project_Management_Implementation_Report-7Sep-6Oct.docx"
    doc.save(out)
    print(out)


if __name__ == "__main__":
    build()
