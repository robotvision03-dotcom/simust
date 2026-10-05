#!/usr/bin/env python3
"""Generate a four-page SIMUST project management Word report (7 Sep – 6 Oct 2026)."""

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


def set_cell_margins(cell, top=22, bottom=22, left=36, right=36):
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
    pf.space_before = Pt(5)
    pf.space_after = Pt(1)
    pf.line_spacing = 1.0
    run = p.add_run(text.upper())
    set_run(run, size=11, bold=True, color=NAVY)
    para_border(p)
    return p


def body(doc, text, *, size=9.5, after=3):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(after)
    pf.line_spacing = 1.05
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(text)
    set_run(run, size=size, color=INK)
    return p


def bullets(doc, items, *, size=9):
    for text in items:
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Cm(0.35)
        pf.first_line_indent = Cm(-0.22)
        pf.space_before = Pt(0)
        pf.space_after = Pt(1)
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
    r2 = hp.add_run("     QR-Code Sport Analysis  ·  Project Management & Implementation Report")
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


def add_table(doc, headers, rows, widths, center_cols=None, font=7.5):
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
    section.left_margin = Cm(1.45)
    section.right_margin = Cm(1.45)
    section.top_margin = Cm(1.7)
    section.bottom_margin = Cm(1.45)
    section.header_distance = Cm(0.45)
    section.footer_distance = Cm(0.4)
    header_footer(doc)

    t = doc.add_paragraph()
    t.paragraph_format.space_before = Pt(0)
    t.paragraph_format.space_after = Pt(0)
    set_run(t.add_run("PROJECT MANAGEMENT & IMPLEMENTATION REPORT"), size=15, bold=True, color=NAVY)

    st = doc.add_paragraph()
    st.paragraph_format.space_before = Pt(1)
    st.paragraph_format.space_after = Pt(5)
    set_run(
        st.add_run("qr-code-sport-analysis  ·  SIMUST software  ·  pay period 7 Sep – 6 Oct"),
        size=10.5,
        italic=True,
        color=GOLD,
    )

    meta = [
        ["Document", "FHP-PM-2026-P3", "Classification", "Internal / Client"],
        ["Project", "SIMUST", "Repository", "robotvision03-dotcom/simust"],
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
        "This report is the project-management record for SIMUST QR-code sport analysis in the payment "
        "period 7 September – 6 October 2026. It continues Phase 2 close-out and records Phase 3 delivery: "
        "dual Field A/B realtime, image-cue keypoint sync (17-frame delay, 20/30 FPS), booking-gated play, "
        "Foundation→Entry→World Class unlock, coach/operator reservations, My SIMUST Android (Google Play "
        "bundle), phone-first operator UX, finish-balls coaching films, pause-freeze accuracy, and live "
        "RESULTS. Governance used GitHub feature branches (Field_A_B, image_based_player, version3, entry, "
        "version4, finish_balls, centralization, qr_sync) merged to main after lab and my.simust.com checks. "
        "About 70 developer commits across all branches in this window were reviewed for this close-out.",
        size=9.5,
        after=3,
    )

    heading(doc, "2.  Programme phases (4 weeks: 7 September – 6 October 2026)")
    add_table(
        doc,
        ["ID", "Phase", "Dates", "Scope closed", "%"],
        [
            ["P0", "Dual-field realtime", "07 Sep – 16 Sep", "Field A/B synced play, single-field mode, combined results", "100%"],
            ["P1", "Booking & portal", "09 Sep – 16 Sep", "Booking windows, staff reservations, portal i18n/freeze fixes", "100%"],
            ["P2", "Image-cue player", "18 Sep – 25 Sep", "Teammate flash, 17f keypoint delay, 20 FPS clock, SF labeled player", "100%"],
            ["P3", "Levels & unlock", "10 Sep – 29 Sep", "Paid unlock, Entry A-T series, score-gated next set to World Class", "100%"],
            ["P4", "Coach & mobile UX", "26 Sep – 05 Oct", "Coach reservations/levels, phone operator, My SIMUST Play bundle", "100%"],
            ["P5", "Accuracy & pause", "08 Sep – 05 Oct", "GOAL/PRESS/late tempo, keypoint sync, pause freeze + resume math", "100%"],
            ["P6", "Acceptance", "03 Oct – 06 Oct", "Finish-balls coaches, unlock sims, this PM report, handover", "100%"],
        ],
        [1.2, 3.6, 3.4, 8.3, 1.5],
        center_cols={0, 2, 4},
        font=7.5,
    )

    heading(doc, "3.  Master project activity sheet")
    body(
        doc,
        "Complete register of developer activities in this pay window. Reviewed from all active branches "
        "(main, Field_A_B*, image_based_player*, version3*, entry, version4, finish_balls, centralization, "
        "qr_sync, cursor/*). 99% items are accepted residuals only.",
        size=9,
        after=3,
    )
    add_table(
        doc,
        ["WBS", "Activity (implemented)", "Stream", "Start", "Finish", "%"],
        [
            ["1.1", "Dual Field A/B realtime: synced sessions, combined results, active-only detection/labels", "Dual field", "07 Sep", "16 Sep", "100%"],
            ["1.2", "Single-field A or B start from remote operator; inactive half masked; B coach slices", "Dual field", "13 Sep", "26 Sep", "100%"],
            ["1.3", "Screens renamed 1–6 per field; content centered with saved calibration; Insta button", "Dual field", "26 Sep", "27 Sep", "100%"],
            ["2.1", "Gate Realtime Play to live booking windows; dual calendars; hide other players' names", "Booking", "13 Sep", "16 Sep", "100%"],
            ["2.2", "Staff reservation management tab; coach password cancel/add; multi-slot calendar UX", "Booking", "15 Sep", "05 Oct", "100%"],
            ["2.3", "Admin/coach play-without-reservation (test password) after player select", "Booking", "16 Sep", "05 Oct", "100%"],
            ["3.1", "Image-based teammate-flash player; cue-driven keypoints; SF-30N labeled action/gap", "Player", "22 Sep", "25 Sep", "100%"],
            ["3.2", "17-frame keypoint delay per pass; 20 FPS clock; stop video after last pass; QR sync tune", "Player", "18 Sep", "25 Sep", "100%"],
            ["3.3", "Foundation cognitive/math playlists; mixed Foundation remote start; opening cards A/B", "Player", "23 Sep", "26 Sep", "100%"],
            ["4.1", "Paid 30-minute unlock pipeline; score opens next set; A-T4 opens next band (Entry→Activated…)", "Progress", "10 Sep", "05 Oct", "100%"],
            ["4.2", "Entry dual-field unlock; Elite/World Class order; finish-balls clock + coach films", "Progress", "26 Sep", "03 Oct", "100%"],
            ["5.1", "My SIMUST Android (com.simust.mysimust): login/dashboard, waiver, Play signed AAB", "Mobile", "10 Sep", "11 Sep", "100%"],
            ["5.2", "Operator Android SIMUST 2.4→2.13: lab-link status, cache bust, phone-first operator UI", "Mobile", "08 Sep", "05 Oct", "100%"],
            ["6.1", "my.simust.com production hostname; VPS update script branch arg; deploy pipeline docs", "Ops", "08 Sep", "26 Sep", "100%"],
            ["6.2", "Remote coach login harden; hide visualisation for coaches; lab failure surfacing", "Ops", "08 Sep", "05 Oct", "100%"],
            ["7.1", "Accuracy: GOAL corner Miss, PRESS Correct no Miss, tempo-aware late search, SF-30N labels", "Analysis", "08 Sep", "10 Sep", "100%"],
            ["7.2", "Pause freeze: countdown/session/analysis clocks + player action timers; resume shift math", "Analysis", "09 Sep", "05 Oct", "100%"],
            ["7.3", "Homography in git; SF-60N displacement/replay tests; wrong-action own-screen results", "Analysis", "09 Sep", "28 Sep", "100%"],
            ["8.1", "Portal/operator i18n repair; dashboard freeze fixes; live RESULTS while session runs", "UI", "08 Sep", "15 Sep", "100%"],
            ["8.2", "Phone operator: coach password checkbox, select player Field A/B, hamburger logout, Reservation", "UI", "05 Oct", "05 Oct", "100%"],
            ["9.1", "Unlock / dual-field / pause simulators and reports; PR merges #13–#18; acceptance handover", "QA / PM", "09 Sep", "06 Oct", "100%"],
            ["9.2", "Live card-acquirer credentials on production (accepted residual from Phase 2)", "Payment", "07 Sep", "06 Oct", "99%"],
        ],
        [1.3, 10.2, 2.0, 1.6, 1.6, 1.3],
        center_cols={0, 3, 4, 5},
        font=6.8,
    )

    heading(doc, "4.  Implementation details — software delivered")
    body(
        doc,
        "In this period SIMUST moved from single-field lab play to dual-field image-cue training with "
        "booking-gated remote operators. Cameras and pose stay on the lab LAN; my.simust.com and Android "
        "apps drive play and reservations. Classification of PASS/GOAL/PRESS/TARGET remains the core "
        "accuracy product, now with tempo-aware late windows and pause-safe clocks.",
        size=9.5,
        after=2,
    )

    heading(doc, "4.1  Dual Field A/B and remote operator")
    bullets(
        doc,
        [
            "Synced dual realtime; staff can start Field A, Field B, or both; inactive half blacked out.",
            "Remote operator: mixed Foundation, Entry A-T display, play-without-reservation, coach login.",
            "Phone-first index.html: Select player field A/B, coach password checkbox, Reservation multi-slot calendar, logout in ☰.",
        ],
    )

    heading(doc, "4.2  Image-cue player, keypoints and finish-balls")
    bullets(
        doc,
        [
            "Teammate-flash / SF labeled player: cue ON → 17-frame keypoint appear, On hold, clear; 20/30 FPS recording.",
            "Per-pass delay without slipping later actions; QR sync for dual vs single field.",
            "Finish-balls: session clock × actions; matching coach film on final results; wrong action on own screen.",
        ],
    )

    heading(doc, "4.3  Progression, Android and VPS")
    bullets(
        doc,
        [
            "Score unlock: Foundation SF chain → Entry; A-T4 opens next band; Elite/World Class ordered.",
            "My SIMUST Play-ready AAB; operator SIMUST 2.13; update-all.ps1 / update-vps.sh branch-aware.",
            "Coach reservations and level control; visualisation admin-only; lab-link online blinking status.",
        ],
    )

    heading(doc, "5.  Increasing analysis accuracy")
    body(
        doc,
        "Accuracy work this period: GOAL near-miss exits as Miss with corner aim; PRESS reach scored Correct "
        "without Miss; late search tempo-aware for short/fast SF-30N; SF-30N T1.2 result labels restored; "
        "displacement aggregation and QR flicker extras fixed; pause cancels analysis timers and restores "
        "remaining delay so Correct/Late windows do not consume pause wall-clock; keypoint On countdown is "
        "frame-based and frozen while paused. Simulator tests (unlock-to-World-Class, dual-field, pause) "
        "confirm the gates. Residual 99%: live payment acquirer credentials only.",
        size=9.5,
        after=3,
    )

    heading(doc, "6.  Milestone register — all items 99% or 100% done")
    add_table(
        doc,
        ["MS", "Date", "Milestone", "%", "State"],
        [
            ["M1", "10 Sep 2026", "Paid unlock pipeline and tempo-aware late search for SF-30N", "100%", "Done"],
            ["M2", "11 Sep 2026", "My SIMUST Android + Google Play signed release support", "100%", "Done"],
            ["M3", "16 Sep 2026", "Dual Field A/B realtime merged (PRs #15–#18); booking-gated play", "100%", "Done"],
            ["M4", "22 Sep 2026", "Image-based teammate-flash player and keypoint On sync", "100%", "Done"],
            ["M5", "25 Sep 2026", "17-frame per-pass delay; 20 FPS clock; Foundation cognitive playlists", "100%", "Done"],
            ["M6", "26 Sep 2026", "Remote mixed Foundation/Entry; screen 1–6 calibration; VPS branch update", "100%", "Done"],
            ["M7", "29 Sep 2026", "Score opens next set through Elite / World Class in order", "100%", "Done"],
            ["M8", "03 Oct 2026", "Finish-balls sessions and matching coach final films", "100%", "Done"],
            ["M9", "05 Oct 2026", "Coach operator + phone UX + A-T4 next-band unlock + SIMUST 2.13", "100%", "Done"],
            ["M10", "06 Oct 2026", "Pause accuracy simulators; this Phase 3 PM report; handover", "100%", "Done"],
            ["M11", "06 Oct 2026", "Live acquirer keys — accepted residual", "99%", "Done"],
        ],
        [1.3, 2.6, 10.0, 1.5, 1.6],
        center_cols={0, 1, 3, 4},
        font=7.5,
    )

    heading(doc, "7.  Deliverables, closed risks and sign-off")
    body(
        doc,
        "Artefacts: dual-field realtime engine; image-cue smart player; index.html phone operator; "
        "my_simust.html booking/portal; My SIMUST + SIMUST Android; VPS deploy scripts; unlock/pause/"
        "dual-field tests; this Word report on branch docs/project-management-7sep-6oct. Closed risks: "
        "desynced Field A/B clocks; keypoint slip across passes; play outside booking; coach without "
        "reservation tools; pause eating late-analysis time; dashboard freeze after login.",
        size=9.5,
        after=3,
    )

    sign = [
        ["Overall completion", "99.9% weighted — every milestone is 99% or 100% done"],
        ["Schedule", "7 September 2026 – 6 October 2026, closed on time"],
        ["Phase 3 technical list", "Dual field, image-cue player, unlock chain, coach/mobile UX — 100%"],
        ["Branches reviewed", "main, Field_A_B*, image_based_player*, version3*, entry, version4, finish_balls, centralization, qr_sync, cursor/*"],
        ["Outstanding (accepted)", "Live card-acquirer credentials on production accounts"],
        ["Prepared for", "SIMUST product owner / Siamak Azadi"],
        ["Prepared by", "Omid Moradtalab - Software development — qr-code-sport-analysis workstream"],
    ]
    stbl = doc.add_table(rows=len(sign), cols=2)
    for i, (k, v) in enumerate(sign):
        fill = ROW_ALT if i % 2 else "FFFFFF"
        write_cell(stbl.rows[i].cells[0], k, size=8, bold=True, color=NAVY, fill=fill)
        write_cell(stbl.rows[i].cells[1], v, size=8, color=INK, fill=fill)
    set_col_widths(stbl, [4.4, 13.6])

    close = doc.add_paragraph()
    close.alignment = WD_ALIGN_PARAGRAPH.CENTER
    close.paragraph_format.space_before = Pt(8)
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
