import cv2
import math
import sys

# لیست برای ذخیره‌ی نقاط کلیک‌شده
points = []
image = None
clone = None

def click_event(event, x, y, flags, param):
    global points, image, clone
    if event == cv2.EVENT_LBUTTONDOWN:
        points.append((x, y))
        # رسم نقطه روی تصویر
        cv2.circle(image, (x, y), 5, (0, 0, 255), -1)
        cv2.putText(image, f"({x}, {y})", (x + 10, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.imshow("Calibration", image)
        
        if len(points) == 2:
            # محاسبه‌ی فاصله‌ی پیکسلی
            x1, y1 = points[0]
            x2, y2 = points[1]
            pixel_dist = math.hypot(x2 - x1, y2 - y1)
            
            # فاصله‌ی واقعی (به متر) – اینجا ۱۲ متر فرض شده
            real_dist_meters = 12.0  # می‌توانید مقدار را تغییر دهید
            
            scale = real_dist_meters / pixel_dist  # متر بر پیکسل
            
            print("\n" + "="*50)
            print(f"نقطه ۱: ({x1}, {y1})")
            print(f"نقطه ۲: ({x2}, {y2})")
            print(f"فاصله‌ی پیکسلی: {pixel_dist:.2f} px")
            print(f"فاصله‌ی واقعی (متر): {real_dist_meters} m")
            print(f"ضریب تبدیل (متر بر پیکسل): {scale:.6f}")
            print("="*50)
            print("\nبرای استفاده در کد، این مقدار را در ثابت PIXEL_TO_METER_SCALE قرار دهید.")
            
            # نمایش فاصله روی تصویر
            cv2.line(image, (x1, y1), (x2, y2), (255, 0, 0), 2)
            cv2.putText(image, f"{pixel_dist:.1f} px", ((x1+x2)//2, (y1+y2)//2 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.imshow("Calibration", image)

def main():
    global image, clone
    if len(sys.argv) < 2:
        print("استفاده: python calibrate.py <path_to_image>")
        print("مثال: python calibrate.py frame.jpg")
        sys.exit(1)
    
    image_path = sys.argv[1]
    image = cv2.imread(image_path)
    if image is None:
        print(f"خطا: تصویر '{image_path}' یافت نشد.")
        sys.exit(1)
    
    clone = image.copy()
    cv2.imshow("Calibration", image)
    cv2.setMouseCallback("Calibration", click_event)
    
    print("روی تصویر کلیک کنید تا دو نقطه را انتخاب کنید.")
    print("نقطه‌ی اول و دوم باید نقاطی باشند که فاصله‌ی واقعی آن‌ها را می‌دانید.")
    print("پس از انتخاب دو نقطه، ضریب تبدیل محاسبه می‌شود.")
    print("برای خروج، کلید 'q' یا 'ESC' را فشار دهید.")
    
    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:  # q یا ESC
            break
        if len(points) == 2:
            # پس از محاسبه، می‌توانید دوباره کلیک کنید تا نقاط جدید انتخاب شوند
            # برای شروع مجدد، می‌توانید کلید 'r' را اضافه کنید (اختیاری)
            pass
    
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()