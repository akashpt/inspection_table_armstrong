import cv2
import platform


class WebCame:
    def __init__(
        self,
        cam_indices=(0, 2, 0, 0),
        width=2448,
        height=2048,
        fps=30,
        exposure=7000
    ):
        self.cam_indices = cam_indices
        self.width = width
        self.height = height
        self.fps = fps
        self.exposure = exposure

        self.caps = []
        self.latest_frame = None

        # E-con camera
        self.econ_cap = None
        self.econ_index = None


    # =========================================================
    # NORMAL CAMERAS
    # =========================================================
    def open(self):
        self.close()

        self.caps = []

        for index in self.cam_indices:

            cap = cv2.VideoCapture(
                index,
                cv2.CAP_DSHOW
            )

            if cap.isOpened():

                cap.set(
                    cv2.CAP_PROP_FRAME_WIDTH,
                    self.width
                )

                cap.set(
                    cv2.CAP_PROP_FRAME_HEIGHT,
                    self.height
                )

                cap.set(
                    cv2.CAP_PROP_FPS,
                    self.fps
                )

                cap.set(
                    cv2.CAP_PROP_EXPOSURE,
                    self.exposure
                )

                print(f"✅ Camera opened: {index}")

                self.caps.append(cap)

            else:

                print(f"❌ Camera failed: {index}")

                cap.release()

        return len(self.caps) > 0


    # =========================================================
    # E-CON CAMERA CONNECT
    # =========================================================
    # def open_econ(
    #     self,
    #     index=0,
    #     width=1920,
    #     height=1080,
    #     fps=60,
    #     exposure=-7
    # ):

    #     # Close previous E-con camera
    #     self.close_econ()

    #     print(f"🔍 Connecting E-con camera index: {index}")

    #     # Windows
    #     if platform.system() == "Windows":

    #         self.econ_cap = cv2.VideoCapture(
    #             index,
    #             cv2.CAP_DSHOW
    #         )

    #     # Linux
    #     else:

    #         self.econ_cap = cv2.VideoCapture(
    #             index,
    #             cv2.CAP_V4L2
    #         )

    #     if not self.econ_cap.isOpened():

    #         print(
    #             f"❌ E-con camera failed to open: {index}"
    #         )

    #         self.econ_cap.release()
    #         self.econ_cap = None

    #         return False

    #     # Use MJPG for high resolution / high FPS
    #     self.econ_cap.set(
    #         cv2.CAP_PROP_FOURCC,
    #         cv2.VideoWriter_fourcc(
    #             'M', 'J', 'P', 'G'
    #         )
    #     )

    #     self.econ_cap.set(
    #         cv2.CAP_PROP_FRAME_WIDTH,
    #         width
    #     )

    #     self.econ_cap.set(
    #         cv2.CAP_PROP_FRAME_HEIGHT,
    #         height
    #     )

    #     self.econ_cap.set(
    #         cv2.CAP_PROP_FPS,
    #         fps
    #     )

    #     self.econ_cap.set(
    #         cv2.CAP_PROP_EXPOSURE,
    #         exposure
    #     )

    #     self.econ_index = index

    #     # Read actual values
    #     actual_width = self.econ_cap.get(
    #         cv2.CAP_PROP_FRAME_WIDTH
    #     )

    #     actual_height = self.econ_cap.get(
    #         cv2.CAP_PROP_FRAME_HEIGHT
    #     )

    #     actual_fps = self.econ_cap.get(
    #         cv2.CAP_PROP_FPS
    #     )

    #     actual_exposure = self.econ_cap.get(
    #         cv2.CAP_PROP_EXPOSURE
    #     )

    #     print("======================================")
    #     print("✅ E-con camera connected")
    #     print(f"Camera Index : {index}")
    #     print(
    #         f"Resolution   : "
    #         f"{int(actual_width)} x {int(actual_height)}"
    #     )
    #     print(f"Requested FPS: {fps}")
    #     print(f"Actual FPS   : {actual_fps}")
    #     print(f"Exposure     : {actual_exposure}")
    #     print("======================================")

    #     return True

    def open(self):
        self.close()
        self.caps = []

        for index in self.cam_indices:
            print(f"🔍 Opening E-con camera: /dev/video{index}")

            cap = cv2.VideoCapture(
                index,
                cv2.CAP_V4L2
            )

            if not cap.isOpened():
                print(f"❌ Camera failed: {index}")
                cap.release()
                continue

            # Important for E-con high-resolution cameras
            cap.set(
                cv2.CAP_PROP_FOURCC,
                cv2.VideoWriter_fourcc(
                    "M", "J", "P", "G"
                )
            )

            cap.set(
                cv2.CAP_PROP_FRAME_WIDTH,
                self.width
            )

            cap.set(
                cv2.CAP_PROP_FRAME_HEIGHT,
                self.height
            )

            cap.set(
                cv2.CAP_PROP_FPS,
                self.fps
            )

            # Linux/V4L2 exposure support depends on camera
            cap.set(
                cv2.CAP_PROP_EXPOSURE,
                self.exposure
            )

            # Read one frame to verify
            ret, frame = cap.read()

            if not ret or frame is None:
                print(
                    f"❌ Camera {index} opened "
                    "but frame capture failed"
                )
                cap.release()
                continue

            actual_width = int(
                cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            )

            actual_height = int(
                cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            )

            actual_fps = cap.get(
                cv2.CAP_PROP_FPS
            )

            actual_exposure = cap.get(
                cv2.CAP_PROP_EXPOSURE
            )

            print(f"✅ E-con camera opened: {index}")
            print(
                f"   Resolution: "
                f"{actual_width}x{actual_height}"
            )
            print(f"   FPS: {actual_fps}")
            print(f"   Exposure: {actual_exposure}")

            self.caps.append(cap)

        print(
            f"📷 Connected cameras: "
            f"{len(self.caps)}/{len(self.cam_indices)}"
        )

        return len(self.caps) > 0


    # =========================================================
    # GET NORMAL CAMERA FRAMES
    # =========================================================
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


    # =========================================================
    # GET E-CON FRAME
    # =========================================================
    def get_econ_frame(self):

        if self.econ_cap is None:

            return None

        if not self.econ_cap.isOpened():

            return None

        ret, frame = self.econ_cap.read()

        if not ret or frame is None:

            print("❌ E-con frame capture failed")

            return None

        self.latest_frame = frame.copy()

        return frame


    # =========================================================
    # GET LATEST FRAME
    # =========================================================
    def get_latest_frame(self):

        return self.latest_frame


    # =========================================================
    # SET NORMAL CAMERA EXPOSURE
    # =========================================================
    def set_exposure(self, exposure):

        self.exposure = exposure

        for cap in self.caps:

            if cap.isOpened():

                cap.set(
                    cv2.CAP_PROP_EXPOSURE,
                    self.exposure
                )


    # =========================================================
    # SET E-CON EXPOSURE
    # =========================================================
    def set_econ_exposure(self, exposure):

        if (
            self.econ_cap is not None
            and self.econ_cap.isOpened()
        ):

            self.econ_cap.set(
                cv2.CAP_PROP_EXPOSURE,
                exposure
            )

            actual = self.econ_cap.get(
                cv2.CAP_PROP_EXPOSURE
            )

            print(
                f"📷 E-con exposure: {actual}"
            )

            return actual

        return None


    # =========================================================
    # CLOSE NORMAL CAMERAS
    # =========================================================
    def close(self):

        for cap in self.caps:

            if cap is not None:

                cap.release()

        self.caps = []

        self.latest_frame = None


    # =========================================================
    # CLOSE E-CON CAMERA
    # =========================================================
    def close_econ(self):

        if self.econ_cap is not None:

            self.econ_cap.release()

            self.econ_cap = None

        self.econ_index = None

        print("🛑 E-con camera closed")


    # =========================================================
    # CLOSE ALL CAMERAS
    # =========================================================
    def close_all(self):

        self.close()

        self.close_econ()

        print("🛑 All cameras closed")