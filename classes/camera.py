import cv2

class WebCame:
    def __init__(self, cam_indices=(0, 2, 4, 6), width=2448, height=2048, fps=30,exposure=7000):
        self.cam_indices = cam_indices
        self.width = width
        self.height = height
        self.fps = fps
        self.exposure = exposure
        self.caps = []
        self.latest_frame = None
 
    def open(self):
        self.close()
        self.caps = []

        for index in self.cam_indices:
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)

            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                cap.set(cv2.CAP_PROP_FPS, self.fps)
                cap.set(cv2.CAP_PROP_EXPOSURE, self.exposure)

                print(f"✅ Camera opened: {index}")
                self.caps.append(cap)
            else:
                print(f"❌ Camera failed: {index}")
                cap.release()

        return len(self.caps) > 0

    def get_frame(self):
        frames = []

        for cap in self.caps:
            ret, frame = cap.read()
            if ret and frame is not None:
                frames.append(frame)

        if not frames:
            return None

        combined = cv2.hconcat(frames)
        self.latest_frame = combined.copy()
        return combined

    def get_latest_frame(self):
        return self.latest_frame

    def set_exposure(self, exposure):
        self.exposure = exposure
        for cap in self.caps:
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_EXPOSURE, self.exposure)

    def close(self):
        for cap in self.caps:
            cap.release()

        self.caps = []
        self.latest_frame = None
