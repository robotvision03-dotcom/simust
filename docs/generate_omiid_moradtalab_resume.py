#!/usr/bin/env python3
"""Generate Omiid Moradtalab CV/resume as a Word document.

Visual format matches docs/project-management-7sep-6oct
(SIMUST Project Management & Implementation Report): navy/gold palette,
Calibri, gold-underline section headings, styled tables, header/footer.
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


def body(doc, text, *, size=10, after=6, justify=True):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(after)
    pf.line_spacing = 1.15
    if justify:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(text)
    set_run(run, size=size, color=INK)
    return p


def bullets(doc, items, *, size=9.5):
    for text in items:
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Cm(0.4)
        pf.first_line_indent = Cm(-0.25)
        pf.space_before = Pt(1)
        pf.space_after = Pt(2)
        pf.line_spacing = 1.12
        run = p.add_run("•  " + text)
        set_run(run, size=size, color=INK)


def job_header(doc, company, role, dates):
    """Company / role line + dates, matching report meta emphasis."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(7)
    pf.space_after = Pt(1)
    pf.line_spacing = 1.1
    r1 = p.add_run(company)
    set_run(r1, size=10.5, bold=True, color=NAVY)
    r2 = p.add_run("  ·  ")
    set_run(r2, size=10, color=MUTED)
    r3 = p.add_run(role)
    set_run(r3, size=10, bold=True, color=INK)

    d = doc.add_paragraph()
    df = d.paragraph_format
    df.space_before = Pt(0)
    df.space_after = Pt(2)
    df.line_spacing = 1.05
    set_run(d.add_run(dates), size=9, italic=True, color=GOLD)


def edu_block(doc, school, degree, dates, extras=None):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(5)
    pf.space_after = Pt(1)
    set_run(p.add_run(school), size=10.5, bold=True, color=NAVY)
    r2 = p.add_run("  ·  ")
    set_run(r2, size=10, color=MUTED)
    set_run(p.add_run(dates), size=9, italic=True, color=GOLD)

    d = doc.add_paragraph()
    df = d.paragraph_format
    df.space_before = Pt(0)
    df.space_after = Pt(1 if extras else 3)
    set_run(d.add_run(degree), size=10, color=INK)

    if extras:
        for line in extras:
            e = doc.add_paragraph()
            ef = e.paragraph_format
            ef.space_before = Pt(0)
            ef.space_after = Pt(2)
            set_run(e.add_run(line), size=9, italic=True, color=MUTED)


def header_footer(doc):
    section = doc.sections[0]
    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    r1 = hp.add_run("OMIID MORADTALAB")
    set_run(r1, size=8, bold=True, color=NAVY)
    r2 = hp.add_run("     Curriculum Vitae  ·  AI & Robotics / Computer Vision Engineer")
    set_run(r2, size=8, color=MUTED)
    para_border(hp, sz="16", space="4")

    footer = section.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    r = fp.add_run("Confidential  ·  Curriculum Vitae  ·  Updated ")
    set_run(r, size=8, color=MUTED)
    set_run(fp.add_run(date.today().strftime("%B %Y")), size=8, color=MUTED)
    set_run(fp.add_run("  ·  Page "), size=8, color=MUTED)
    add_field(fp, " PAGE ")
    set_run(fp.add_run(" of "), size=8, color=MUTED)
    add_field(fp, " NUMPAGES ")
    para_border(fp, edge="top", sz="12", space="3")


def add_table(doc, headers, rows, widths, center_cols=None, font=9):
    center_cols = center_cols or set()
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        write_cell(
            table.rows[0].cells[i],
            h,
            size=8,
            bold=True,
            color=WHITE,
            align="center",
            fill=HEADER_BG,
        )
    for r_i, row in enumerate(rows):
        fill = ROW_ALT if r_i % 2 else "FFFFFF"
        prevent_row_split(table.rows[r_i + 1])
        for c_i, val in enumerate(row):
            align = "center" if c_i in center_cols else "left"
            write_cell(
                table.rows[r_i + 1].cells[c_i],
                str(val),
                size=font,
                bold=(c_i == 0),
                color=INK,
                align=align,
                fill=fill,
            )
    set_col_widths(table, widths)
    return table


def skill_rows(doc, rows):
    """Navy/gold label–value pairs like the PM report meta / sign-off tables."""
    table = doc.add_table(rows=len(rows), cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (k, v) in enumerate(rows):
        fill = ROW_ALT if i % 2 else "FFFFFF"
        write_cell(table.rows[i].cells[0], k, size=9, bold=True, color=NAVY, fill=fill)
        write_cell(table.rows[i].cells[1], v, size=9, color=INK, fill=fill)
    set_col_widths(table, [4.2, 13.6])
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

    # ------------------------------------------------------------------ Title
    t = doc.add_paragraph()
    t.paragraph_format.space_before = Pt(0)
    t.paragraph_format.space_after = Pt(2)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(t.add_run("OMIID MORADTALAB"), size=18, bold=True, color=NAVY)

    st = doc.add_paragraph()
    st.paragraph_format.space_before = Pt(0)
    st.paragraph_format.space_after = Pt(6)
    st.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(
        st.add_run(
            "AI & Robotics Engineer  ·  Computer Vision  ·  Perception Systems"
        ),
        size=11,
        italic=True,
        color=GOLD,
    )

    meta = [
        ["Location", "Yousef Abad, Tehran, Iran", "Phone", "+98 903 290 1549"],
        [
            "Email",
            "moradtalab.o@gmail.com",
            "Focus",
            "YOLO · OpenCV · ROS/ROS2 · Deep Learning",
        ],
        [
            "Document",
            "CV — Curriculum Vitae",
            "Issue date",
            date.today().strftime("%d %B %Y"),
        ],
        [
            "Classification",
            "Professional / Confidential",
            "Experience",
            "10+ years perception & robotics",
        ],
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
    set_col_widths(mt, [3.2, 6.2, 3.0, 5.4])

    # ------------------------------------------------------------------ Summary
    heading(doc, "1.  Professional summary")
    body(
        doc,
        "AI and Robotics Engineer with an MSc in Computer Vision & AI and 10+ years of experience "
        "developing perception systems. Expert in Python, OpenCV, YOLO, and deep learning for object "
        "detection and image segmentation. Proven track record in autonomous systems, computer vision "
        "research, and leading innovative robotics projects with multiple international awards and patents.",
    )

    # ------------------------------------------------------------------ Education
    heading(doc, "2.  Education")
    edu_block(
        doc,
        "University of Bourgogne | France",
        "Master's in Robotics and Computer Vision Engineering — Artificial Intelligence",
        "2014–2016",
        extras=[
            "World Education Services (WES) GPA: B+",
            'Thesis: "Automatic Detection of the Cardiac Contours on Delayed Enhanced MRI"',
        ],
    )
    edu_block(
        doc,
        "University of Tabriz | Iran",
        "Master of Science — Electrical Engineering",
        "2011–2013",
    )
    edu_block(
        doc,
        "Islamic Azad University (IAU) | Iran",
        "Bachelor of Science — Electrical Engineering",
        "2006–2010",
    )

    # ------------------------------------------------------------------ Skills
    heading(doc, "3.  Technical skills")
    skill_rows(
        doc,
        [
            (
                "Programming",
                "Python (Advanced), C++, MATLAB",
            ),
            (
                "Computer Vision & ML",
                "OpenCV (Advanced), YOLO (v5/v8/v9), Object Detection, Image Segmentation, "
                "Roboflow, Model Training & Optimization, Scikit-image, Keras, PyTorch, "
                "Scikit-learn, Pandas, NumPy, SciPy",
            ),
            (
                "Robotics & Perception",
                "ROS/ROS2, Sensor Fusion (LIDAR, IMU, Camera), Intel RealSense, 3D Perception, "
                "Navigation Stack, MoveIt, Gazebo",
            ),
            (
                "Tools & OS",
                "Linux (Ubuntu), Docker, Git/GitHub/GitLab, CI/CD, Jupyter, LaTeX",
            ),
            (
                "Hardware",
                "NVIDIA Xavier AGX, Arduino, Raspberry Pi, Schneider PLC, SIEMENS S7",
            ),
        ],
    )

    # ------------------------------------------------------------------ Honors
    heading(doc, "4.  Honors & awards")
    bullets(
        doc,
        [
            'Selected as one of Canada\'s 30 Best Startups with Potential for Massive Impact; '
            'Winner of 2022 Ocean Startup Challenge for "Intelligent ROV for Underwater Welding Operations"',
            'Selected as Top 5 Canadian Startup Owner at pitch competition for '
            '"Biofriendly Mining Robot for Seabed Applications" as CEO of Tesla Robotics Inc.',
            'Silver Medal for Invention: "Instrument for Putting on Socks with Fuzzy Control" '
            "at 6th International Exhibition in China, Certificate No. 06GJ02175",
            "Member of Iran's National Elites Foundation (INEF) since 2008",
            "Best Researcher Award, Young Researchers Club (2009, 2010)",
            "Country Representative, Mehrafarin Inventions Festival (2008)",
            "Invention Fellowship under Iran's Elites National Organization programs",
            'Provincially selected invention for "Automated Mosaic Construction Machine" '
            "at Kharazmi Festival (2009)",
        ],
    )

    # ------------------------------------------------------------------ Experience
    heading(doc, "5.  Professional experience")

    job_header(
        doc,
        "Stealth Startup | Netherlands (Remote)",
        "Computer Vision Engineer — Football Analysis",
        "2024 – Present",
    )
    bullets(
        doc,
        [
            "Developing computer vision systems for professional football analysis and player performance tracking",
            "Implementing YOLO-based object detection models (YOLOv8/v9) to track players, referees, and ball movements in match footage",
            "Managing an end-to-end dataset pipeline including data collection, annotation using Roboflow, and dataset versioning",
            "Training and fine-tuning custom YOLO detection models on large-scale football match datasets for high accuracy",
            "Optimizing detection algorithms for real-time processing of multiple camera feeds",
            "Collaborating with a remote international team to deliver advanced sports analytics solutions",
        ],
    )

    job_header(
        doc,
        "Intel Vision Technologies | Vancouver, Canada",
        "Co-Founder and Chief Technology Officer (CTO)",
        "2022 – 2024",
    )
    bullets(
        doc,
        [
            "Co-founded company focused on advanced robotic solutions for industrial underwater applications",
            "Spearheaded development of intelligent ROV for underwater welding operations",
            "Selected as one of Canada's 30 best startups in 2022 Ocean Startup Challenge",
        ],
    )

    job_header(
        doc,
        "Eleos Robotics Company | Vancouver, Canada",
        "Chief Technology Officer (CTO)",
        "Nov 2020 – Oct 2021",
    )
    bullets(
        doc,
        [
            "Led team developing RoboWeeder, an AI-powered weeding robot using patent-pending precision heating technology",
            "Implemented mapping using 2D Sick LIDAR and Google Cartographer for autonomous navigation",
            "Applied computer vision techniques for object detection using YOLO, Intel RealSense Camera, Python, and C++",
            "Developed robot arm using MoveIt and ClearPath Servomotors on Linux Kernel V5",
            "Integrated Xsens IMU and RoboteQ Drive Motors for enhanced robot performance",
        ],
    )

    job_header(
        doc,
        "Amazon / JLL Company | Vancouver, Canada",
        "Reliability and Maintenance Engineering (RME) Tech III",
        "2020 – 2022",
    )
    bullets(
        doc,
        [
            "Maintained and repaired conveyor systems and automated material handling equipment",
            "Attained over 25 professional certifications in reliability maintenance and technical skills",
        ],
    )

    job_header(
        doc,
        "Enerpro Systems | Vancouver, Canada",
        "IoT Control Panel Designer",
        "2019",
    )
    bullets(
        doc,
        [
            "Designed Energy Management System control panels",
            "Implemented remote databases using Python and MySQL for data management",
        ],
    )

    job_header(
        doc,
        "CNRS-Le2i (French National Research Center) | France",
        "Computer Vision Software Developer",
        "2016",
    )
    bullets(
        doc,
        [
            "Developed medical imaging software using Python, PyQt, OpenCV, and scikit-image on Linux",
            "Implemented image processing algorithms and data analysis pipelines for research applications",
        ],
    )

    job_header(
        doc,
        "Fraunhofer Institute | Germany",
        "Computer Vision Software Developer",
        "Jun 2015 – Sep 2015",
    )
    bullets(
        doc,
        [
            "Developed algorithms to detect thin cracks on road surfaces using C++, Linux, and ToolIP",
            "Optimized computer vision solutions for industrial infrastructure monitoring",
        ],
    )

    job_header(
        doc,
        "TurboTeck | Tehran, Iran",
        "Software Developer and Team Leader",
        "2018",
    )
    bullets(
        doc,
        [
            "Developed IIoT solutions using Python, Django, Linux, and ThingsBoard dashboards",
            "Managed SQL/NoSQL databases for industrial monitoring applications",
        ],
    )

    job_header(
        doc,
        "Green Energy Group — GDL | Tehran, Iran",
        "Technical and Sales Engineer",
        "2017",
    )
    bullets(
        doc,
        [
            "Provided technical expertise for solar panel system design and installation",
        ],
    )

    job_header(
        doc,
        "Pars Saman | Tehran, Iran",
        "Electrical and Control Leader",
        "Jan 2014 – Sep 2014",
    )
    bullets(
        doc,
        [
            "Automated oil and gas pipeline monitoring using Schneider PLC",
            "Designed industrial control panels",
        ],
    )

    job_header(
        doc,
        "Oil Turbo Compressors Group | Tehran, Iran",
        "Electrical and Control Engineer",
        "Jan 2013 – Dec 2013",
    )
    bullets(
        doc,
        [
            "Maintained and troubleshoot SIEMENS SGT Turbo Compressors",
            "Programmed SIEMENS S7 PLCs (200, 300, 400 series)",
            "Site supervisor for automation, maintenance, and installation of electrical and control equipment",
        ],
    )

    # ------------------------------------------------------------------ Projects
    heading(doc, "6.  Selected projects")
    add_table(
        doc,
        ["Project", "Stack / focus"],
        [
            [
                "Football Player Detection & Tracking",
                "Python, YOLOv8, Roboflow, OpenCV, Multi-camera fusion",
            ],
            [
                "Mobile Robot Navigation",
                "ROS, RVIZ, Gazebo, Python, C++",
            ],
            [
                "YOLO Object Detection for Robotics",
                "Python, YOLO, OpenCV, Intel RealSense, ROS",
            ],
            [
                "KURABot — Restaurant Assistant Robot",
                "ROS, Linux, OpenCV, Lidar, Python",
            ],
        ],
        [7.5, 10.3],
        font=9,
    )

    # ------------------------------------------------------------------ Patents
    heading(doc, "7.  Patents")
    add_table(
        doc,
        ["Patent", "Year", "Registration"],
        [
            [
                "Automatic Gearshift Bicycle for Inclines and Declines",
                "2008",
                "No. 53418",
            ],
            [
                "Intelligent Control of Car Overtaking by GPS",
                "2008",
                "No. 51636",
            ],
            ["Freezer Plastic Bag Opener Set", "2008", "No. 51509"],
            [
                "Counter Digital Data Checking by Wireless Remote Control",
                "2007",
                "No. 43884",
            ],
            [
                "Device for Assisting Disabled People in Removing Socks",
                "2005",
                "No. 32445",
            ],
            ["Electric Engine Intelligent Control", "2008", "No. 53413"],
            ["Robot Guidance by Fuzzy Control", "2008", "No. 51510"],
            ["2 US patents pending registration", "—", "Pending"],
        ],
        [11.5, 2.2, 4.1],
        center_cols={1, 2},
        font=8.5,
    )

    # ------------------------------------------------------------------ Publications
    heading(doc, "8.  Publications (selected from 15+)")
    bullets(
        doc,
        [
            'O. Moradtalab, A. Lalande, S. Bricq. "Automatic Detection of the Cardiac Contours on Delayed Enhanced MRI", Vibot Master\'s Day',
            'O. Moradtalab, R. Moradtalab. "New Approaches for Face Recognition Using Neural Networks", 8th WSEAS International Conference (Best Paper Award)',
            'K. Shafafi, E. Saremian, O. Moradtalab. "Optimizing Pictorial Compacted Data Detection in Noisy Environments", IEEE MWOC 2009',
            'O. Moradtalab, M.B.B. Sharifian, R. Moradtalab. "Uninterrupted Operation of Wind Power Plant After Grid Disconnection", 2nd Green Energy Conference',
            "Multiple publications in IEEE conferences, WSEAS proceedings, and national journals",
        ],
    )

    # ------------------------------------------------------------------ Memberships
    heading(doc, "9.  Professional memberships")
    bullets(
        doc,
        [
            "Member, Institute of Electrical and Electronics Engineers (IEEE)",
            "Member, Iran's Elites National Organization",
            "Member, Young Researchers Club",
            "Member, International Federation of Inventors' Associations",
            "Reviewer: IEEE Transactions, World Applied Sciences Journal, Springer NDT 2010",
        ],
    )

    # ------------------------------------------------------------------ Languages
    heading(doc, "10.  Languages")
    add_table(
        doc,
        ["Language", "Proficiency"],
        [
            ["Persian", "Native"],
            ["English", "Professional Working Proficiency (Advanced)"],
            ["Kurdish", "Conversational"],
        ],
        [5.0, 12.8],
        font=9,
    )

    # ------------------------------------------------------------------ References
    heading(doc, "11.  Academic references")
    refs = [
        [
            "Prof. Fabrice MERIAUDEAU",
            "UMR CNRS 6306, Le2i Laboratoire, Université de Bourgogne — I.U.T. Le Creusot, "
            "12 rue de la fonderie, 71200 Le Creusot, France — fabrice.meriaudeau@u-bourgogne.fr",
        ],
        [
            "Prof. Alain LALANDE",
            "Pôle Imagerie Médicale et Santé, LE2I, UMR CNRS 6306 — Faculté de Médecine, "
            "Université de Bourgogne — alain.lalande@u-bourgogne.fr",
        ],
        [
            "Dr. Olivier Morel",
            "Associate Professor, LE2I UMR6306, CNRS, ENSAM, Univ. Bourgogne Franche-Comté — "
            "IUT Le Creusot, 12 rue de la Fonderie, 71200 Le Creusot, France — "
            "olivier.morel@u-bourgogne.fr",
        ],
    ]
    rt = doc.add_table(rows=len(refs), cols=2)
    for i, (name, detail) in enumerate(refs):
        fill = ROW_ALT if i % 2 else "FFFFFF"
        write_cell(rt.rows[i].cells[0], name, size=9, bold=True, color=NAVY, fill=fill)
        write_cell(rt.rows[i].cells[1], detail, size=8.5, color=INK, fill=fill)
    set_col_widths(rt, [4.8, 13.0])

    close = doc.add_paragraph()
    close.alignment = WD_ALIGN_PARAGRAPH.CENTER
    close.paragraph_format.space_before = Pt(14)
    set_run(
        close.add_run(
            "End of curriculum vitae  ·  Omiid Moradtalab  ·  AI & Robotics / Computer Vision"
        ),
        size=9,
        italic=True,
        color=MUTED,
    )

    out = Path(__file__).resolve().parent / "Omiid_Moradtalab_CV.docx"
    doc.save(out)
    print(out)


if __name__ == "__main__":
    build()
