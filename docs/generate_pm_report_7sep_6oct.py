#!/usr/bin/env python3
"""Generate a true four-page SIMUST Phase 3 PM Word report (7 Sep – 6 Oct 2026).

Vision-based sport analysis. Uses explicit page breaks so Word always shows 4 pages.
"""

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
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


def set_cell_margins(cell, top=40, bottom=40, left=40, right=40):
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
    pf.line_spacing = 1.05
    return p


def write_cell(cell, text, *, size=9, bold=False, color=INK, align="left", fill=None):
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


def page_break(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run()
    run.add_break(WD_BREAK.PAGE)


def heading(doc, text):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(10)
    pf.space_after = Pt(4)
    pf.line_spacing = 1.05
    run = p.add_run(text.upper())
    set_run(run, size=12, bold=True, color=NAVY)
    para_border(p)
    return p


def body(doc, text, *, size=10, after=6):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(after)
    pf.line_spacing = 1.15
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(text)
    set_run(run, size=size, color=INK)
    return p


def bullets(doc, items, *, size=10):
    for text in items:
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Cm(0.4)
        pf.first_line_indent = Cm(-0.25)
        pf.space_before = Pt(1)
        pf.space_after = Pt(3)
        pf.line_spacing = 1.12
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


def add_table(doc, headers, rows, widths, center_cols=None, font=9):
    center_cols = center_cols or set()
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        write_cell(table.rows[0].cells[i], h, size=8, bold=True, color=WHITE, align="center", fill=HEADER_BG)
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
    section.left_margin = Cm(1.6)
    section.right_margin = Cm(1.6)
    section.top_margin = Cm(1.9)
    section.bottom_margin = Cm(1.6)
    section.header_distance = Cm(0.5)
    section.footer_distance = Cm(0.5)
    header_footer(doc)

    # ------------------------------------------------------------------ PAGE 1
    t = doc.add_paragraph()
    t.paragraph_format.space_before = Pt(0)
    t.paragraph_format.space_after = Pt(2)
    set_run(t.add_run("PROJECT MANAGEMENT & IMPLEMENTATION REPORT"), size=16, bold=True, color=NAVY)

    st = doc.add_paragraph()
    st.paragraph_format.space_before = Pt(0)
    st.paragraph_format.space_after = Pt(8)
    set_run(
        st.add_run("Vision-based sport analysis  ·  SIMUST software  ·  pay period 7 Sep – 6 Oct 2026"),
        size=11,
        italic=True,
        color=GOLD,
    )

    meta = [
        ["Document", "FHP-PM-2026-P3", "Classification", "Internal / Client"],
        ["Project", "SIMUST — vision-based training", "Repository", "robotvision03-dotcom/simust"],
        ["Period", "7 September 2026 – 6 October 2026", "Contract window", "4 weeks (Phase 3 technical delivery)"],
        ["Status", "All milestones 99% or 100% done", "Issue date", date.today().strftime("%d %B %Y")],
        ["Pages", "4 (forced layout)", "Commits reviewed", "~70 across all feature branches"],
    ]
    mt = doc.add_table(rows=len(meta), cols=4)
    for i, row in enumerate(meta):
        fill = "0B1E36" if i % 2 == 0 else "122A48"
        for j, val in enumerate(row):
            write_cell(
                mt.rows[i].cells[j],
                val,
                size=9,
                bold=(j % 2 == 0),
                color=GOLD if j % 2 == 0 else WHITE,
                fill=fill,
            )
    set_col_widths(mt, [3.2, 5.8, 3.4, 5.4])

    heading(doc, "1.  Purpose, governance and objectives")
    body(
        doc,
        "This four-page report is the project-management record for SIMUST vision-based sport analysis "
        "in the payment period 7 September – 6 October 2026. SIMUST uses pitch cameras, YOLOv8 "
        "detection and pose, homography calibration, and image-cue screens (teammate flash and "
        "Foundation SF sets) to classify PASS, GOAL, PRESS and TARGET. Physical tags on the pitch are "
        "not part of the product; the vision pipeline and image cues define each action block.",
    )
    body(
        doc,
        "Phase 3 continues after the Phase 2 close-out (teams, security, VPS, portal, payment step). "
        "This window delivered dual Field A/B realtime vision, cue-driven keypoint timing (17-frame "
        "appear delay, On hold, clear), booking-gated play, Foundation → Entry → World Class score "
        "unlock, coach/operator reservations, My SIMUST Android (Google Play bundle), phone-first "
        "operator UX, finish-balls coaching films, pause-freeze accuracy, and live RESULTS while a "
        "session runs.",
    )
    body(
        doc,
        "Governance used weekly work packages on GitHub feature branches, verified on the lab PC and "
        "on my.simust.com. Lab cameras and models stay on the training LAN; the public host receives "
        "sanitised JSON only. About seventy developer commits across all branches were reviewed for "
        "this close-out.",
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
        [1.3, 3.4, 3.4, 8.0, 1.5],
        center_cols={0, 2, 4},
        font=9,
    )

    page_break(doc)

    # ------------------------------------------------------------------ PAGE 2
    heading(doc, "3.  Master project activity sheet (part A)")
    body(
        doc,
        "Detailed register of developer activities. Sources: main and feature branches Field_A_B*, "
        "image_based_player*, version3*, entry, version4, finish_balls, centralization, keypoint-sync "
        "lab branches, and cursor/* PRs. Percentages: 100% closed; 99% = accepted production residual.",
        size=10,
        after=5,
    )
    add_table(
        doc,
        ["WBS", "Activity (implemented) — detail", "Stream", "Start", "Finish", "%"],
        [
            ["1.1", "Dual Field A/B realtime vision: shared action index, synced session start/end, combined A+B results", "Dual field", "07 Sep", "16 Sep", "100%"],
            ["1.2", "Single-field A or B from remote operator; inactive half blacked out; no YOLO/pose on idle field", "Dual field", "13 Sep", "26 Sep", "100%"],
            ["1.3", "Arena screens renamed 1–6 per field; display content centered with saved homography calibration", "Dual field", "26 Sep", "27 Sep", "100%"],
            ["1.4", "Operator Instagram-live button; keypoints drawn on renamed field screens during image-cue play", "Dual field", "27 Sep", "27 Sep", "100%"],
            ["2.1", "Gate Realtime Play to live booking window only; dual-field calendars; hide other players' names", "Booking", "13 Sep", "16 Sep", "100%"],
            ["2.2", "Staff Reservation tab: week grid Field A/B, gold booked cells, multi-select 1–3×30 min, Add/Cancel", "Booking", "15 Sep", "05 Oct", "100%"],
            ["2.3", "Coach/admin play-without-reservation checkbox + password after selecting Field A/B players", "Booking", "16 Sep", "05 Oct", "100%"],
            ["2.4", "Coach role: reservation + level unlock/lock; hide Arena/On/Gap and visualisation for coaches", "Booking", "05 Oct", "05 Oct", "100%"],
            ["3.1", "Vision image-cue player: teammate-flash / SF pass images; cue JSON drives keypoints (tag path off)", "Player", "22 Sep", "25 Sep", "100%"],
            ["3.2", "Per-pass 17-frame keypoint appear; On hold then clear; 20 FPS display / 30 FPS record; no S2/S3 slip", "Player", "18 Sep", "25 Sep", "100%"],
            ["3.3", "SF-30N labeled action / filler / gap image player; Foundation cognitive & math playlists", "Player", "22 Sep", "25 Sep", "100%"],
            ["3.4", "Mixed Foundation remote start; per-field opening cards; stop video after last pass", "Player", "23 Sep", "26 Sep", "100%"],
            ["3.5", "Finish-balls: clock = On × actions; advance on goal; matching coach film on final results", "Player", "03 Oct", "03 Oct", "100%"],
        ],
        [1.3, 9.8, 2.0, 1.6, 1.6, 1.3],
        center_cols={0, 3, 4, 5},
        font=8.5,
    )

    heading(doc, "3.1  Activity notes — dual field and booking")
    bullets(
        doc,
        [
            "Dual field: Field A (left) and Field B (right) share one timeline when both are active; each keeps its own recognition folder and coach slice.",
            "Single-field start: staff can open only A or only B from the remote/public operator; the idle half is solid black and skipped by detection.",
            "Booking gate: Realtime Play is refused before/after the paid window; calendars show both fields; other players’ names stay hidden for privacy.",
            "Reservations: coaches and admins manage gold cells; up to three consecutive 30-minute slots; coach password for cancel and for no-booking play.",
        ],
    )

    page_break(doc)

    # ------------------------------------------------------------------ PAGE 3
    heading(doc, "3.  Master project activity sheet (part B)")
    add_table(
        doc,
        ["WBS", "Activity (implemented) — detail", "Stream", "Start", "Finish", "%"],
        [
            ["4.1", "Paid 30-min unlock credits; score opens next set; A-T4 opens next band (Entry→Activated→…→WC)", "Progress", "10 Sep", "05 Oct", "100%"],
            ["4.2", "Entry dual-field unlock flow; Elite/World Class ordered play; unlock-to-World-Class simulators", "Progress", "26 Sep", "05 Oct", "100%"],
            ["5.1", "My SIMUST Android (com.simust.mysimust): login/dashboard, admin waiver, signed Play AAB pipeline", "Mobile", "10 Sep", "11 Sep", "100%"],
            ["5.2", "Operator Android SIMUST 2.4→2.13: lab online status, WebView cache bust, phone-fit controls", "Mobile", "08 Sep", "05 Oct", "100%"],
            ["6.1", "my.simust.com production hostname; update-vps.sh branch argument; update-all.ps1 lab+VPS+APK", "Ops", "08 Sep", "26 Sep", "100%"],
            ["6.2", "Remote coach login harden on VPS; surface Realtime Play failures when lab does not start", "Ops", "08 Sep", "05 Oct", "100%"],
            ["7.1", "Vision accuracy: GOAL corner near-miss→Miss; PRESS reach→Correct (no Miss); tempo-aware late window", "Analysis", "08 Sep", "10 Sep", "100%"],
            ["7.2", "SF-30N T1.2 all result labels restored; displacement aggregation; flicker extras cleaned", "Analysis", "09 Sep", "10 Sep", "100%"],
            ["7.3", "Pause: freeze keypoint countdown, session clocks, late-analysis remaining; resume shifts by pause dt", "Analysis", "09 Sep", "05 Oct", "100%"],
            ["7.4", "Homography in git; SF-60N displacement + recognition replay tests; wrong action on own screen", "Analysis", "09 Sep", "28 Sep", "100%"],
            ["8.1", "Portal/operator i18n repair; stop dashboard freeze (N+1 reports / i18n loop); live RESULTS tab", "UI", "08 Sep", "15 Sep", "100%"],
            ["8.2", "Phone operator: Select player field A/B, coach password only, ☰ logout, Reservation, online blink", "UI", "05 Oct", "05 Oct", "100%"],
            ["9.1", "Simulators: unlock, dual-field, pause freeze; PRs #13–#18; Phase 3 acceptance + this Word report", "QA / PM", "09 Sep", "06 Oct", "100%"],
            ["9.2", "Live card-acquirer API keys / settlement on production accounts (accepted residual)", "Payment", "07 Sep", "06 Oct", "99%"],
        ],
        [1.3, 9.8, 2.0, 1.6, 1.6, 1.3],
        center_cols={0, 3, 4, 5},
        font=8.5,
    )

    heading(doc, "4.  Implementation details — software delivered")
    body(
        doc,
        "SIMUST is a vision-based soccer decision trainer. Cameras and pose models track ball and player; "
        "image cues on the six arena screens define the action; the engine classifies PASS, TARGET, PRESS "
        "and GOAL against screen polygons and goal lines. Results are stored per player and shown on the "
        "lab/operator console and on My SIMUST.",
    )

    heading(doc, "4.1  Dual Field A/B and remote / phone operator")
    bullets(
        doc,
        [
            "Synced dual realtime vision; staff start Field A, Field B, or both; inactive half masked.",
            "Remote operator: mixed Foundation, Entry A-T labels, play-without-reservation, hardened coach login.",
            "Phone-first index.html: Select player field A/B; coach password checkbox; Reservation 1–3 slots; logout in ☰; slow blink online / fast blink during Realtime Play.",
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

    page_break(doc)

    # ------------------------------------------------------------------ PAGE 4
    heading(doc, "5.  Increasing vision analysis accuracy")
    body(
        doc,
        "Accuracy this period focused on vision decisions and timing integrity:",
        after=3,
    )
    bullets(
        doc,
        [
            "GOAL: near-miss exits counted as Miss; aim toward goal corners for projection.",
            "PRESS: reach scored Correct without Miss when the player arrives in the press zone.",
            "Late search: tempo-aware for short/fast SF-30N so the late window matches the gap.",
            "SF-30N T1.2: all result labels restored (not only the last action).",
            "Displacement aggregation and flicker extras cleaned for stable tables.",
            "Pause: analysis timers cancelled; remaining delay restored; keypoint On countdown frozen; resume shifts clocks by pause duration so Correct/Late ignore pause wall-clock.",
            "Homography calibration tracked in git; SF-60N displacement and recognition replay tests added.",
            "Simulators (unlock-to-World-Class, dual-field, pause freeze) confirm the gates before handover.",
        ],
    )
    body(
        doc,
        "Residual at 99%: live payment-acquirer credentials on production accounts only. Vision "
        "classification and pause math for this period are closed at 100%.",
        after=6,
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
            ["M10", "06 Oct 2026", "Pause accuracy simulators; Phase 3 PM report (4 pages); handover", "100%", "Done"],
            ["M11", "06 Oct 2026", "Live acquirer keys — accepted residual", "99%", "Done"],
        ],
        [1.4, 2.7, 9.6, 1.5, 1.6],
        center_cols={0, 1, 3, 4},
        font=9,
    )

    heading(doc, "7.  Deliverables, closed risks and sign-off")
    body(
        doc,
        "Artefacts: dual-field vision realtime engine; image-cue smart player; phone operator "
        "(index.html); My SIMUST portal + Android; operator Android; VPS deploy scripts; unlock/pause/"
        "dual-field tests; this four-page Word report on branch docs/project-management-7sep-6oct. "
        "Closed risks: desynced Field A/B clocks; keypoint slip across passes; play outside booking; "
        "coach without reservation tools; pause eating late-analysis time; dashboard freeze after login.",
        after=6,
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
        write_cell(stbl.rows[i].cells[0], k, size=9, bold=True, color=NAVY, fill=fill)
        write_cell(stbl.rows[i].cells[1], v, size=9, color=INK, fill=fill)
    set_col_widths(stbl, [4.6, 13.2])

    close = doc.add_paragraph()
    close.alignment = WD_ALIGN_PARAGRAPH.CENTER
    close.paragraph_format.space_before = Pt(12)
    set_run(
        close.add_run("End of four-page report  ·  SIMUST Play It Smart  ·  closed 6 October 2026"),
        size=9,
        italic=True,
        color=MUTED,
    )

    out = Path(__file__).resolve().parent / "SIMUST_Project_Management_Implementation_Report-7Sep-6Oct.docx"
    doc.save(out)
    print(out)


if __name__ == "__main__":
    build()
