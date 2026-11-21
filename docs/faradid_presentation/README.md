# ارائه فرادید هوش پژوه

فایل‌های ارائه حرفه‌ای ۱۲ اسلایدی (۱۶:۹، فارسی، راست‌چین).

## خروجی‌ها
- `Faradid_Hoosh_Industrial_AI_Presentation.pptx` — قابل ویرایش در PowerPoint / LibreOffice Impress
- `Faradid_Hoosh_Industrial_AI_Presentation.pdf` — نسخه مشاهده سریع

## بازتولید
```bash
pip install python-pptx Pillow
# فونت Vazirmatn در fonts/ttf موجود است؛ برای نمایش صحیح در سیستم عامل نصب شود.
python3 generate_presentation.py
libreoffice --headless --convert-to pdf Faradid_Hoosh_Industrial_AI_Presentation.pptx
```

## هویت بصری
- سرمه‌ای تیره / آبی تکنولوژیک / سفید / خاکستری
- فونت: Vazirmatn
- تصاویر صنعتی واقعی + Bounding Box برای اسلایدهای تشخیص هوشمند
- دیاگرام معماری: Camera → AI Engine → Event Detection → Alert → Dashboard
