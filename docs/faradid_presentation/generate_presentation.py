#!/usr/bin/env python3
"""Generate Faradid Hoosh Pazhooh professional Persian RTL PowerPoint (16:9)."""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
OUT_PPTX = ROOT / "Faradid_Hoosh_Industrial_AI_Presentation.pptx"
OUT_PDF = ROOT / "Faradid_Hoosh_Industrial_AI_Presentation.pdf"

FONT = "Vazirmatn"
FONT_REG = str(ROOT / "fonts/ttf/Vazirmatn-Regular.ttf")
FONT_BOLD = str(ROOT / "fonts/ttf/Vazirmatn-Bold.ttf")

NAVY = RGBColor(0x0B, 0x1E, 0x36)
NAVY_DEEP = RGBColor(0x07, 0x14, 0x26)
CYAN = RGBColor(0x00, 0xA8, 0xE8)
CYAN_SOFT = RGBColor(0x4F, 0xC3, 0xF7)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY = RGBColor(0xB8, 0xC4, 0xD4)
MUTED = RGBColor(0x8A, 0x9A, 0xAE)
LIGHT_BG = RGBColor(0xF4, 0xF7, 0xFB)
CARD = RGBColor(0x12, 0x2A, 0x48)
ACCENT_LINE = RGBColor(0x00, 0xA8, 0xE8)


def has_persian(text: str) -> bool:
    return any("\u0600" <= c <= "\u06FF" for c in text)


def set_run_font(run, size_pt, bold=False, color=WHITE):
    run.font.name = FONT
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    # Complex-script / east-asia font for Persian viewers (PowerPoint/LibreOffice)
    for tag in ("a:latin", "a:cs", "a:ea"):
        el = rPr.find(qn(tag))
        if el is None:
            el = OxmlElement(tag)
            rPr.append(el)
        el.set("typeface", FONT)


def set_rtl(paragraph, enabled=True):
    """Mark paragraph as RTL so PowerPoint shapes Persian correctly (logical Unicode)."""
    pPr = paragraph._p.get_or_add_pPr()
    if enabled:
        pPr.set("rtl", "1")
        if pPr.find(qn("a:rtl")) is None:
            pPr.append(OxmlElement("a:rtl"))
    else:
        if "rtl" in pPr.attrib:
            del pPr.attrib["rtl"]


def add_textbox(slide, left, top, width, height, text, *, size=18, bold=False,
                color=WHITE, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.TOP, rtl=None):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    try:
        tf._txBody.bodyPr.set(
            "anchor",
            {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor],
        )
    except Exception:
        pass
    p = tf.paragraphs[0]
    p.alignment = align
    use_rtl = has_persian(text) if rtl is None else rtl
    set_rtl(p, use_rtl)
    run = p.add_run()
    run.text = text  # logical Unicode — editable & correct with rtl=1
    set_run_font(run, size, bold=bold, color=color)
    return box


def add_bullets(slide, left, top, width, height, items, *, size=15, color=WHITE, spacing=6):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.RIGHT
        set_rtl(p, True)
        p.space_after = Pt(spacing)
        run = p.add_run()
        run.text = "•  " + item
        set_run_font(run, size, color=color)
    return box


def rect(slide, left, top, width, height, fill, line=None):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(1.25)
    return sh


def round_rect(slide, left, top, width, height, fill, line=None):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
    return sh


def accent_bar(slide, left, top, width=Inches(0.08), height=Inches(0.55)):
    return rect(slide, left, top, width, height, CYAN)


def footer(slide, page, total=12):
    add_textbox(
        slide, Inches(0.4), Inches(7.05), Inches(6), Inches(0.35),
        "فرادید هوش پژوه  |  Faradid Hoosh Pazhooh",
        size=10, color=MUTED, align=PP_ALIGN.RIGHT,
    )
    add_textbox(
        slide, Inches(10.5), Inches(7.05), Inches(2.4), Inches(0.35),
        f"{page} / {total}",
        size=10, color=MUTED, align=PP_ALIGN.LEFT, rtl=False,
    )


def section_title(slide, title, subtitle=None, y=Inches(0.28)):
    accent_bar(slide, Inches(12.85), y, Inches(0.1), Inches(0.55))
    add_textbox(
        slide, Inches(0.5), y, Inches(12.2), Inches(0.55),
        title, size=26, bold=True, color=WHITE, align=PP_ALIGN.RIGHT,
    )
    if subtitle:
        add_textbox(
            slide, Inches(0.5), y + Inches(0.5), Inches(12.2), Inches(0.4),
            subtitle, size=14, color=CYAN_SOFT, align=PP_ALIGN.RIGHT,
        )


def add_picture_safe(slide, path, left, top, width=None, height=None):
    path = Path(path)
    if not path.exists():
        return None
    kwargs = {"left": left, "top": top}
    if width:
        kwargs["width"] = width
    if height:
        kwargs["height"] = height
    return slide.shapes.add_picture(str(path), **kwargs)


def dark_bg(slide):
    rect(slide, Inches(0), Inches(0), Inches(13.333), Inches(7.5), NAVY_DEEP)


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------

def slide_01(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_picture_safe(s, ASSETS / "title_bg.jpg", Inches(0), Inches(0), width=Inches(13.333), height=Inches(7.5))
    rect(s, Inches(0), Inches(0), Inches(7.2), Inches(7.5), NAVY)
    # translucent strip
    rect(s, Inches(7.0), Inches(0), Inches(0.08), Inches(7.5), CYAN)

    add_textbox(s, Inches(0.6), Inches(1.6), Inches(6.2), Inches(0.9),
                "فرادید هوش پژوه", size=40, bold=True, color=WHITE)
    add_textbox(s, Inches(0.6), Inches(2.45), Inches(6.2), Inches(0.4),
                "Faradid Hoosh Pazhooh", size=16, color=CYAN)
    add_textbox(s, Inches(0.6), Inches(3.1), Inches(6.2), Inches(1.1),
                "نسل جدید سامانه‌های هوشمند پایش تصویری و ایمنی صنعتی مبتنی بر هوش مصنوعی",
                size=18, color=GRAY)
    add_textbox(s, Inches(0.6), Inches(4.4), Inches(6.2), Inches(0.4),
                "Computer Vision  |  Artificial Intelligence  |  Smart Cameras  |  Industrial Safety",
                size=12, color=MUTED, align=PP_ALIGN.RIGHT)
    rect(s, Inches(5.9), Inches(5.1), Inches(0.9), Inches(0.05), CYAN)
    add_textbox(s, Inches(0.6), Inches(5.35), Inches(6.2), Inches(0.35),
                "ارائه‌دهنده: امید مرادطلب", size=16, bold=True, color=WHITE)
    add_textbox(s, Inches(0.6), Inches(5.75), Inches(6.2), Inches(0.35),
                "رئیس شرکت فرادید هوش پژوه", size=14, color=CYAN_SOFT)
    footer(s, 1)


def slide_02(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "درباره فرادید هوش پژوه", "معرفی شرکت")
    add_picture_safe(s, ASSETS / "hero.jpg", Inches(0.4), Inches(1.35), width=Inches(5.4), height=Inches(5.2))
    rect(s, Inches(0.4), Inches(5.7), Inches(5.4), Inches(0.85), NAVY)
    add_textbox(s, Inches(0.55), Inches(5.8), Inches(5.1), Inches(0.65),
                "هوش مصنوعی · بینایی ماشین · رباتیک", size=13, color=CYAN, align=PP_ALIGN.CENTER)

    add_textbox(s, Inches(6.1), Inches(1.35), Inches(6.8), Inches(1.3),
                "فرادید هوش پژوه یک مجموعه فناور در حوزه طراحی و توسعه راهکارهای هوشمند مبتنی بر هوش مصنوعی، بینایی ماشین و رباتیک است.",
                size=15, color=GRAY)
    add_textbox(s, Inches(6.1), Inches(2.55), Inches(6.8), Inches(0.9),
                "تمرکز اصلی شرکت، تبدیل داده‌های تصویری و اطلاعات محیطی به ابزارهای هوشمند برای تصمیم‌گیری، پایش، تشخیص و کنترل است.",
                size=14, color=MUTED)

    round_rect(s, Inches(6.1), Inches(3.5), Inches(6.8), Inches(3.0), CARD, CYAN)
    add_textbox(s, Inches(6.3), Inches(3.65), Inches(6.4), Inches(0.4),
                "حوزه‌های تخصصی", size=16, bold=True, color=CYAN)
    add_bullets(s, Inches(6.3), Inches(4.1), Inches(6.4), Inches(2.2), [
        "طراحی و توسعه الگوریتم‌های هوش مصنوعی",
        "پردازش تصویر و تحلیل هوشمند ویدئو",
        "طراحی سامانه‌های دوربین هوشمند",
        "تشخیص خودکار رخدادها و شرایط غیرعادی",
        "تحلیل رفتار انسان و تجهیزات",
        "توسعه سامانه‌های نرم‌افزاری و داشبوردهای مدیریتی",
    ], size=13)
    footer(s, 2)


def slide_03(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "از مشاهده تصاویر تا درک هوشمند محیط", "تحول از دوربین نظارتی به دوربین هوشمند")
    add_picture_safe(s, ASSETS / "traditional_vs_smart.jpg", Inches(0.4), Inches(1.3),
                     width=Inches(12.5), height=Inches(2.55))

    add_textbox(s, Inches(0.5), Inches(4.0), Inches(12.3), Inches(0.55),
                "دوربین‌های نظارتی سنتی صرفاً تصاویر را ثبت می‌کنند؛ سامانه‌های هوشمند فرادید تصاویر را تحلیل کرده و رخدادهای مهم را شناسایی می‌کنند.",
                size=14, color=GRAY)

    # comparison table as cards
    left_items = ["ضبط و نمایش تصویر", "نیازمند مشاهده مداوم اپراتور", "واکنش پس از مشاهده انسان",
                  "جست‌وجوی دستی فیلم", "اطلاعات تصویری خام"]
    right_items = ["تحلیل محتوای تصویر", "تشخیص خودکار رخداد", "هشدار خودکار",
                   "جست‌وجوی رخدادمحور", "داده و گزارش تحلیلی"]

    round_rect(s, Inches(0.4), Inches(4.6), Inches(6.0), Inches(1.95), CARD)
    add_textbox(s, Inches(0.55), Inches(4.7), Inches(5.7), Inches(0.35),
                "دوربین سنتی", size=14, bold=True, color=MUTED, align=PP_ALIGN.CENTER)
    add_bullets(s, Inches(0.55), Inches(5.1), Inches(5.7), Inches(1.35), left_items, size=12, color=GRAY, spacing=2)

    round_rect(s, Inches(6.9), Inches(4.6), Inches(6.0), Inches(1.95), CARD, CYAN)
    add_textbox(s, Inches(7.05), Inches(4.7), Inches(5.7), Inches(0.35),
                "دوربین هوشمند", size=14, bold=True, color=CYAN, align=PP_ALIGN.CENTER)
    add_bullets(s, Inches(7.05), Inches(5.1), Inches(5.7), Inches(1.35), right_items, size=12, color=WHITE, spacing=2)

    footer(s, 3)


def slide_04(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "معماری هوشمند تحلیل تصویر", "معماری دوربین هوشمند فرادید")
    add_picture_safe(s, ASSETS / "architecture.png", Inches(0.35), Inches(1.15),
                     width=Inches(12.6), height=Inches(2.75))

    add_textbox(s, Inches(0.5), Inches(3.95), Inches(12.3), Inches(0.4),
                "راهکار فرادید می‌تواند با دوربین‌های موجود یا دوربین‌های هوشمند اختصاصی، تصاویر محیط را به‌صورت پیوسته تحلیل کند.",
                size=13, color=GRAY)

    steps = [
        "دریافت تصویر از دوربین‌های صنعتی و نظارتی",
        "پردازش تصویر و استخراج اطلاعات",
        "شناسایی اشیا، افراد و تجهیزات",
        "تحلیل رفتار و تشخیص رخدادهای غیرعادی",
        "تولید هشدار و ثبت رویداد",
        "ارسال اطلاعات به داشبورد مرکزی",
    ]
    for i, step in enumerate(steps):
        col = i % 3
        row = i // 3
        x = Inches(0.4 + col * 4.25)
        y = Inches(4.45 + row * 1.05)
        round_rect(s, x, y, Inches(4.05), Inches(0.9), CARD, CYAN)
        add_textbox(s, x + Inches(0.15), y + Inches(0.12), Inches(0.45), Inches(0.6),
                    str(i + 1), size=20, bold=True, color=CYAN, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        add_textbox(s, x + Inches(0.6), y + Inches(0.2), Inches(3.3), Inches(0.55),
                    step, size=12, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)

    footer(s, 4)


def slide_05(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "پایش تصویری هوشمند شرایط خطرناک", "تشخیص هوشمند آتش، دود و نشانه‌های نشت")
    add_picture_safe(s, ASSETS / "fire_detection.jpg", Inches(0.35), Inches(1.25),
                     width=Inches(6.4), height=Inches(3.6))

    round_rect(s, Inches(7.0), Inches(1.25), Inches(5.9), Inches(3.6), CARD, CYAN)
    add_textbox(s, Inches(7.2), Inches(1.4), Inches(5.5), Inches(0.4),
                "قابلیت‌های قابل توسعه", size=15, bold=True, color=CYAN)
    add_bullets(s, Inches(7.2), Inches(1.9), Inches(5.5), Inches(2.7), [
        "تشخیص شعله و آتش",
        "شناسایی دود و افزایش غیرعادی آن",
        "تشخیص بخار یا ابرهای قابل مشاهده",
        "شناسایی تغییرات غیرعادی در محیط",
        "تعیین موقعیت تقریبی رخداد در تصویر",
        "ارسال هشدار همراه با تصویر و زمان وقوع",
    ], size=13)

    round_rect(s, Inches(0.35), Inches(5.05), Inches(6.4), Inches(1.5), CARD)
    add_textbox(s, Inches(0.5), Inches(5.15), Inches(6.1), Inches(0.35),
                "کاربردها", size=13, bold=True, color=CYAN)
    add_bullets(s, Inches(0.5), Inches(5.5), Inches(6.1), Inches(1.0), [
        "پالایشگاه‌ها · واحدهای پتروشیمی · مخازن و تأسیسات ذخیره‌سازی",
        "خطوط انتقال و ایستگاه‌های صنعتی",
    ], size=12, spacing=3)

    round_rect(s, Inches(7.0), Inches(5.05), Inches(5.9), Inches(1.5), RGBColor(0x2A, 0x1A, 0x14), RGBColor(0xE0, 0x80, 0x40))
    add_textbox(s, Inches(7.2), Inches(5.2), Inches(5.5), Inches(1.15),
                "نکته فنی: تشخیص تصویری بخار یا نشانه‌های قابل مشاهده نشت، جایگزین حسگرهای تخصصی گاز و سامانه‌های اعلام حریق تأییدشده نیست.",
                size=12, color=RGBColor(0xFF, 0xC8, 0xA0))
    footer(s, 5)


def slide_06(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "نظارت هوشمند بر رعایت الزامات ایمنی", "پایش تجهیزات حفاظت فردی (PPE)")
    add_picture_safe(s, ASSETS / "ppe_detection.jpg", Inches(0.35), Inches(1.25),
                     width=Inches(6.5), height=Inches(5.2))

    round_rect(s, Inches(7.1), Inches(1.25), Inches(5.8), Inches(2.55), CARD, CYAN)
    add_textbox(s, Inches(7.3), Inches(1.4), Inches(5.4), Inches(0.35),
                "موارد قابل تشخیص", size=14, bold=True, color=CYAN)
    add_bullets(s, Inches(7.3), Inches(1.85), Inches(5.4), Inches(1.8), [
        "کلاه ایمنی",
        "جلیقه ایمنی و لباس کار",
        "عینک محافظ",
        "ماسک و تجهیزات تنفسی قابل مشاهده",
        "دستکش ایمنی در محدوده دید مناسب",
    ], size=13, spacing=3)

    round_rect(s, Inches(7.1), Inches(4.0), Inches(5.8), Inches(2.45), CARD)
    add_textbox(s, Inches(7.3), Inches(4.15), Inches(5.4), Inches(0.35),
                "خروجی سامانه", size=14, bold=True, color=CYAN)
    add_bullets(s, Inches(7.3), Inches(4.55), Inches(5.4), Inches(1.7), [
        "تشخیص مورد عدم انطباق",
        "نمایش موقعیت فرد در تصویر",
        "ثبت زمان و محل رخداد",
        "تولید گزارش آماری",
        "ارسال هشدار به مسئول ایمنی",
    ], size=13, spacing=3)
    footer(s, 6)


def slide_07(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "تحلیل هوشمند رفتار و وضعیت افراد", "تشخیص رفتارهای پرخطر و حوادث انسانی")
    add_picture_safe(s, ASSETS / "behavior_detection.jpg", Inches(0.35), Inches(1.25),
                     width=Inches(6.4), height=Inches(4.0))

    round_rect(s, Inches(7.0), Inches(1.25), Inches(5.9), Inches(4.0), CARD, CYAN)
    add_textbox(s, Inches(7.2), Inches(1.4), Inches(5.5), Inches(0.35),
                "سناریوهای قابل توسعه", size=14, bold=True, color=CYAN)
    add_bullets(s, Inches(7.2), Inches(1.85), Inches(5.5), Inches(3.2), [
        "تشخیص سقوط افراد",
        "تشخیص بی‌حرکتی غیرعادی",
        "شناسایی ورود به محدوده‌های خطرناک",
        "تشخیص حضور غیرمجاز",
        "شناسایی تجمع غیرعادی افراد",
        "پایش عبور از مسیرهای ممنوعه",
        "تشخیص برخی رفتارهای ناایمن",
    ], size=13, spacing=4)

    round_rect(s, Inches(0.35), Inches(5.45), Inches(12.55), Inches(1.1), CARD)
    add_textbox(s, Inches(0.55), Inches(5.65), Inches(12.15), Inches(0.7),
                "ارزش عملیاتی: کاهش وابستگی به پایش دائمی انسانی و افزایش سرعت اطلاع‌رسانی درباره رخدادهای مهم.",
                size=14, color=CYAN_SOFT)
    footer(s, 7)


def slide_08(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "کنترل هوشمند دسترسی و تردد", "پایش مناطق حساس و محدوده‌های ممنوعه")
    add_picture_safe(s, ASSETS / "zone_detection.jpg", Inches(0.35), Inches(1.25),
                     width=Inches(6.5), height=Inches(3.7))

    round_rect(s, Inches(7.1), Inches(1.25), Inches(5.8), Inches(3.7), CARD, CYAN)
    add_textbox(s, Inches(7.3), Inches(1.4), Inches(5.4), Inches(0.35),
                "قابلیت‌ها", size=14, bold=True, color=CYAN)
    add_bullets(s, Inches(7.3), Inches(1.85), Inches(5.4), Inches(2.9), [
        "تعریف محدوده‌های حساس روی تصویر",
        "تشخیص ورود غیرمجاز",
        "تشخیص عبور از خطوط مجازی",
        "پایش حضور افراد در مناطق خطرناک",
        "ثبت مسیر و زمان ورود و خروج",
        "هشدار فوری به اتاق کنترل",
    ], size=13)

    round_rect(s, Inches(0.35), Inches(5.15), Inches(12.55), Inches(1.4), CARD)
    add_textbox(s, Inches(0.55), Inches(5.25), Inches(12.15), Inches(0.3),
                "کاربردها", size=13, bold=True, color=CYAN)
    add_textbox(s, Inches(0.55), Inches(5.6), Inches(12.15), Inches(0.75),
                "اتاق‌های برق · محدوده تجهیزات دوار · مخازن و واحدهای فرایندی · محوطه‌های عملیاتی · مناطق دارای خطر سقوط یا تماس با مواد خطرناک",
                size=13, color=GRAY)
    footer(s, 8)


def slide_09(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "بینایی ماشین برای نظارت بر وضعیت تجهیزات", "پایش هوشمند تجهیزات و فرایندهای صنعتی")
    add_picture_safe(s, ASSETS / "equipment_detection.jpg", Inches(0.35), Inches(1.25),
                     width=Inches(6.4), height=Inches(3.5))

    round_rect(s, Inches(7.0), Inches(1.25), Inches(5.9), Inches(3.5), CARD, CYAN)
    add_textbox(s, Inches(7.2), Inches(1.4), Inches(5.5), Inches(0.35),
                "سناریوهای قابل توسعه", size=14, bold=True, color=CYAN)
    add_bullets(s, Inches(7.2), Inches(1.85), Inches(5.5), Inches(2.7), [
        "تشخیص تغییرات ظاهری غیرعادی تجهیزات",
        "شناسایی دود یا بخار غیرمعمول",
        "پایش وضعیت ظاهری شیرها و اتصالات",
        "تشخیص حضور اشیا در محدوده‌های حساس",
        "نظارت بر وضعیت برخی نشانگرها و نمایشگرها",
        "تشخیص تغییرات قابل مشاهده در محیط عملیاتی",
    ], size=12)

    round_rect(s, Inches(0.35), Inches(4.95), Inches(6.4), Inches(1.55), CARD)
    add_textbox(s, Inches(0.5), Inches(5.15), Inches(6.1), Inches(1.15),
                "مزیت: افزودن یک لایه تحلیل تصویری به فرایندهای پایش و نگهداری تجهیزات.",
                size=14, color=CYAN_SOFT)

    round_rect(s, Inches(7.0), Inches(4.95), Inches(5.9), Inches(1.55), RGBColor(0x2A, 0x1A, 0x14), RGBColor(0xE0, 0x80, 0x40))
    add_textbox(s, Inches(7.2), Inches(5.1), Inches(5.5), Inches(1.25),
                "توجه: تشخیص دما، فشار، ترکیب شیمیایی یا نشتی نامرئی به حسگرهای تخصصی نیاز دارد و صرفاً از تصاویر دوربین معمولی قابل استنتاج قطعی نیست.",
                size=12, color=RGBColor(0xFF, 0xC8, 0xA0))
    footer(s, 9)


def slide_10(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "یک مرکز هوشمند برای مدیریت رخدادها", "داشبورد مرکزی و مدیریت هشدارها")
    add_picture_safe(s, ASSETS / "control_dashboard.jpg", Inches(0.35), Inches(1.2),
                     width=Inches(7.0), height=Inches(3.95))

    round_rect(s, Inches(7.55), Inches(1.2), Inches(5.35), Inches(3.95), CARD, CYAN)
    add_textbox(s, Inches(7.7), Inches(1.35), Inches(5.05), Inches(0.35),
                "امکانات داشبورد", size=14, bold=True, color=CYAN)
    add_bullets(s, Inches(7.7), Inches(1.8), Inches(5.05), Inches(3.1), [
        "نمایش زنده دوربین‌ها",
        "نمایش هشدارهای فعال",
        "دسته‌بندی رخدادها بر اساس نوع خطر",
        "نمایش محل و زمان وقوع",
        "ذخیره تصاویر و ویدئوهای مرتبط",
        "گزارش‌گیری روزانه و ماهانه",
        "تعیین سطح اولویت هشدارها",
    ], size=12, spacing=3)

    # sample alerts strip
    alerts = [
        "مشاهده دود در محدوده مشخص",
        "ورود فرد بدون کلاه ایمنی",
        "ورود غیرمجاز به محدوده ممنوعه",
        "تشخیص سقوط فرد",
        "مشاهده شعله در محیط عملیاتی",
    ]
    add_textbox(s, Inches(0.4), Inches(5.3), Inches(12.5), Inches(0.3),
                "نمونه هشدارها", size=13, bold=True, color=CYAN)
    for i, a in enumerate(alerts):
        x = Inches(0.35 + (i % 5) * 2.55)
        y = Inches(5.7)
        round_rect(s, x, y, Inches(2.4), Inches(0.85), CARD, RGBColor(0xE0, 0x80, 0x40) if i % 2 else CYAN)
        add_textbox(s, x + Inches(0.08), y + Inches(0.15), Inches(2.24), Inches(0.6),
                    a, size=11, color=WHITE, align=PP_ALIGN.CENTER)
    footer(s, 10)


def slide_11(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark_bg(s)
    section_title(s, "توسعه ایمنی و هوشمندسازی با تحلیل تصویر",
                  "مزیت‌های راهکار فرادید برای صنایع نفت، گاز و پتروشیمی")
    add_picture_safe(s, ASSETS / "smart_camera_plant.jpg", Inches(0.35), Inches(1.25),
                     width=Inches(5.6), height=Inches(4.0))

    benefits = [
        "استفاده از زیرساخت دوربین‌های موجود در صورت سازگاری",
        "کاهش نیاز به مشاهده مداوم تصاویر توسط اپراتور",
        "افزایش سرعت شناسایی رخدادهای تصویری",
        "ثبت مستندات تصویری حوادث و موارد عدم انطباق",
        "امکان طراحی مدل‌های اختصاصی برای هر واحد صنعتی",
        "قابلیت توسعه و افزودن سناریوهای جدید",
        "امکان پردازش محلی و کاهش وابستگی به اینترنت",
    ]
    round_rect(s, Inches(6.2), Inches(1.25), Inches(6.7), Inches(4.0), CARD, CYAN)
    add_textbox(s, Inches(6.4), Inches(1.4), Inches(6.3), Inches(0.35),
                "مزیت‌های کلیدی", size=15, bold=True, color=CYAN)
    add_bullets(s, Inches(6.4), Inches(1.9), Inches(6.3), Inches(3.1), benefits, size=13, spacing=4)

    round_rect(s, Inches(0.35), Inches(5.45), Inches(12.55), Inches(1.1), CARD)
    add_textbox(s, Inches(0.55), Inches(5.65), Inches(12.15), Inches(0.7),
                "هدف نهایی: تبدیل تصاویر دوربین‌های نظارتی به اطلاعات قابل استفاده برای مدیریت ایمنی و عملیات صنعتی.",
                size=15, bold=True, color=CYAN_SOFT)
    footer(s, 11)


def slide_12(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_picture_safe(s, ASSETS / "night.jpg", Inches(0), Inches(0), width=Inches(13.333), height=Inches(7.5))
    rect(s, Inches(0), Inches(0), Inches(13.333), Inches(7.5), NAVY)  # overlay base
    # soften: use navy panel
    add_picture_safe(s, ASSETS / "circuit.jpg", Inches(8.2), Inches(0), width=Inches(5.2), height=Inches(7.5))
    rect(s, Inches(8.0), Inches(0), Inches(0.08), Inches(7.5), CYAN)
    rect(s, Inches(0), Inches(0), Inches(8.15), Inches(7.5), NAVY)

    add_textbox(s, Inches(0.5), Inches(0.7), Inches(7.3), Inches(0.7),
                "فرادید هوش پژوه؛ هوشمندسازی محیط واقعی با هوش مصنوعی",
                size=22, bold=True, color=WHITE)
    add_textbox(s, Inches(0.5), Inches(1.5), Inches(7.3), Inches(0.7),
                "تمرکز فرادید بر توسعه فناوری‌هایی است که بتوانند محیط واقعی را مشاهده، تحلیل و به اطلاعات قابل تصمیم‌گیری تبدیل کنند.",
                size=14, color=GRAY)

    axes = [
        "توسعه نسل جدید دوربین‌های هوشمند",
        "گسترش الگوریتم‌های تشخیص خطر و رخداد",
        "تحلیل رفتار انسان و تجهیزات",
        "توسعه سامانه‌های یکپارچه مدیریت هشدار",
        "پردازش هوشمند در لبه شبکه (Edge AI)",
        "توسعه راهکارهای اختصاصی برای صنایع مختلف",
    ]
    add_textbox(s, Inches(0.5), Inches(2.35), Inches(7.3), Inches(0.35),
                "محورهای توسعه", size=15, bold=True, color=CYAN)
    for i, ax in enumerate(axes):
        y = Inches(2.8 + i * 0.48)
        round_rect(s, Inches(0.5), y, Inches(7.3), Inches(0.42), CARD)
        add_textbox(s, Inches(0.65), y + Inches(0.05), Inches(0.4), Inches(0.32),
                    str(i + 1), size=13, bold=True, color=CYAN, align=PP_ALIGN.CENTER)
        add_textbox(s, Inches(1.15), y + Inches(0.05), Inches(6.4), Inches(0.32),
                    ax, size=13, color=WHITE)

    add_textbox(s, Inches(8.5), Inches(2.4), Inches(4.5), Inches(0.5),
                "فرادید هوش پژوه", size=22, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    add_textbox(s, Inches(8.5), Inches(3.0), Inches(4.5), Inches(0.7),
                "Computer Vision | AI | Robotics\nSmart Industrial Monitoring",
                size=13, color=CYAN, align=PP_ALIGN.CENTER)
    rect(s, Inches(10.0), Inches(3.9), Inches(1.4), Inches(0.05), CYAN)
    add_textbox(s, Inches(8.5), Inches(4.2), Inches(4.5), Inches(0.4),
                "امید مرادطلب", size=16, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    add_textbox(s, Inches(8.5), Inches(4.65), Inches(4.5), Inches(0.4),
                "رئیس شرکت فرادید هوش پژوه", size=13, color=CYAN_SOFT, align=PP_ALIGN.CENTER)
    footer(s, 12)


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    slide_01(prs)
    slide_02(prs)
    slide_03(prs)
    slide_04(prs)
    slide_05(prs)
    slide_06(prs)
    slide_07(prs)
    slide_08(prs)
    slide_09(prs)
    slide_10(prs)
    slide_11(prs)
    slide_12(prs)

    prs.save(OUT_PPTX)
    print(f"Saved: {OUT_PPTX}")
    return OUT_PPTX


if __name__ == "__main__":
    build()
