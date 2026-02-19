import cv2
import time
import threading

profiles = [
    ("1080p 120fps", 1920, 1080, 120),
    ("720p 120fps",   1280, 720,  120),
    ("1080p 60fps",  1920, 1080, 60),
    ("720p 60fps",   1280, 720,  60),
    ("1080p 30fps",  1920, 1080, 30),
    ("720p 30fps",   1280, 720,  30),
]

TEST_DURATION = 3
FPS_TOLERANCE = 0.9
READ_TIMEOUT = 2.0 

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error opening webcam")
    exit()

def read_frame_with_timeout(cap, timeout=READ_TIMEOUT):
    """Read a frame with timeout to prevent hanging"""
    frame_data = {'ret': None, 'frame': None}
    
    def read_thread():
        try:
            frame_data['ret'], frame_data['frame'] = cap.read()
        except Exception as e:
            frame_data['ret'] = False
            print(f"Error reading frame: {e}")
    
    thread = threading.Thread(target=read_thread, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        print(f"Warning: Frame read timeout ({timeout}s) - camera may be unresponsive")
        return False, None
    
    return frame_data['ret'], frame_data['frame']

def test_profile(name, width, height, target_fps):
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, target_fps)

    time.sleep(1)

    frames = 0
    start = time.time()

    while time.time() - start < TEST_DURATION:
        ret, frame = read_frame_with_timeout(cap, READ_TIMEOUT)
        if not ret:
            break
        frames += 1

    elapsed = time.time() - start
    measured_fps = frames / elapsed if elapsed > 0 else 0

    success = measured_fps >= target_fps * FPS_TOLERANCE

    return success, measured_fps


best = None

for name, w, h, fps in profiles:
    ok, real_fps = test_profile(name, w, h, fps)
    if ok:
        best = (name, w, h, fps, real_fps)
        break

cap.release()

if best:
    name, w, h, fps, real_fps = best
    print(f"{name}")
    print("Actual: {:.2f}fps".format(real_fps))
else:
    print("Nenhum resultado esperado foi antingido (< 720p, < 30 FPS).")
