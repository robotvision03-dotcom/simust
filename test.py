import cv2

url = "rtsp://admin:majidAram2@192.168.2.1:554/Streaming/Channels/101/"
cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
if not cap.isOpened():
    print("Failed to open")
else:
    ret, frame = cap.read()
    if ret:
        print("Frame captured successfully")
        cv2.imshow("test", frame)
        cv2.waitKey(0)
    else:
        print("No frame")
cap.release()