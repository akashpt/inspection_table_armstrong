import sys
import cv2

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QPushButton,
    QHBoxLayout
)

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
import os
import sys

os.environ.pop("QT_PLUGIN_PATH", None)
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)

pyqt_plugin_path = (
    f"{sys.prefix}/lib/python3.10/site-packages/PyQt5/Qt5/plugins"
)

os.environ["QT_PLUGIN_PATH"] = pyqt_plugin_path
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = (
    pyqt_plugin_path + "/platforms"
)

print("QT_PLUGIN_PATH =", os.environ["QT_PLUGIN_PATH"])
print(
    "QT_QPA_PLATFORM_PLUGIN_PATH =",
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"]
)

import cv2
from PyQt5.QtWidgets import QApplication

# =========================================================
# YOUR CAMERA CLASS
# =========================================================
class WebCame:
    def __init__(
        self,
        cam_indices=(0, 2, 4),
        width=2448,
        height=2048,
        fps=10,
        exposure=1
    ):
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

        print("\n==========================================")
        print("       OPENING E-CON CAMERAS")
        print("==========================================")

        for index in self.cam_indices:

            print(f"\n🔍 Trying camera index: {index}")
            print(f"Device: /dev/video{index}")

            cap = cv2.VideoCapture(
                index,
                cv2.CAP_V4L2
            )

            if not cap.isOpened():

                print(
                    f"❌ Camera failed: "
                    f"index={index}"
                )

                cap.release()
                continue

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

            print("✅ Camera opened")
            print(f"Index      : {index}")
            print(
                f"Resolution : "
                f"{actual_width} x {actual_height}"
            )
            print(f"FPS        : {actual_fps}")
            print(f"Exposure   : {actual_exposure}")

            self.caps.append(
                (index, cap)
            )

        print("\n==========================================")
        print(
            f"Connected cameras: "
            f"{len(self.caps)} / "
            f"{len(self.cam_indices)}"
        )
        print("==========================================\n")

        return len(self.caps) > 0


    def get_frame(self):

        frames = []

        for index, cap in self.caps:

            if not cap.isOpened():
                continue

            ret, frame = cap.read()

            if not ret or frame is None:

                print(
                    f"❌ Frame read failed: "
                    f"Camera {index}"
                )

                continue

            # Add camera index text on image
            cv2.putText(
                frame,
                f"CAMERA INDEX : {index}",
                (50, 100),
                cv2.FONT_HERSHEY_SIMPLEX,
                2,
                (0, 255, 0),
                4,
                cv2.LINE_AA
            )

            frames.append(frame)

        if not frames:
            return None

        try:

            combined = cv2.hconcat(frames)

        except cv2.error as e:

            print(
                "❌ hconcat error:",
                e
            )

            return None

        self.latest_frame = combined.copy()

        return combined


    def get_latest_frame(self):
        return self.latest_frame


    def set_exposure(self, exposure):

        self.exposure = exposure

        for index, cap in self.caps:

            if cap.isOpened():

                cap.set(
                    cv2.CAP_PROP_EXPOSURE,
                    exposure
                )

                actual = cap.get(
                    cv2.CAP_PROP_EXPOSURE
                )

                print(
                    f"Camera {index} "
                    f"Exposure: {actual}"
                )


    def close(self):

        for index, cap in self.caps:

            try:

                if cap.isOpened():
                    cap.release()

                print(
                    f"✅ Camera {index} released"
                )

            except Exception as e:

                print(
                    f"❌ Camera {index} close error:",
                    e
                )

        self.caps = []
        self.latest_frame = None


# =========================================================
# CAMERA LIVE UI
# =========================================================
class CameraUI(QWidget):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "E-con 3 Camera Live View"
        )

        self.resize(
            1600,
            650
        )

        # -------------------------------------------------
        # CAMERA
        # -------------------------------------------------
        self.camera = WebCame(
            cam_indices=(0, 2, 3),
            width=2448,
            height=2048,
            fps=10,
            exposure=10
        )

        # -------------------------------------------------
        # CAMERA DISPLAY
        # -------------------------------------------------
        self.camera_label = QLabel()

        self.camera_label.setAlignment(
            Qt.AlignCenter
        )

        self.camera_label.setMinimumSize(
            1200,
            400
        )

        self.camera_label.setStyleSheet("""
            QLabel {
                background-color: black;
                border: 2px solid #555;
            }
        """)

        self.camera_label.setText(
            "Camera not started"
        )

        # -------------------------------------------------
        # BUTTONS
        # -------------------------------------------------
        self.start_button = QPushButton(
            "START CAMERA"
        )

        self.stop_button = QPushButton(
            "STOP CAMERA"
        )

        self.start_button.setMinimumHeight(
            45
        )

        self.stop_button.setMinimumHeight(
            45
        )

        self.start_button.clicked.connect(
            self.start_camera
        )

        self.stop_button.clicked.connect(
            self.stop_camera
        )

        # -------------------------------------------------
        # BUTTON LAYOUT
        # -------------------------------------------------
        button_layout = QHBoxLayout()

        button_layout.addWidget(
            self.start_button
        )

        button_layout.addWidget(
            self.stop_button
        )

        # -------------------------------------------------
        # MAIN LAYOUT
        # -------------------------------------------------
        layout = QVBoxLayout()

        layout.addWidget(
            self.camera_label
        )

        layout.addLayout(
            button_layout
        )

        self.setLayout(
            layout
        )

        # -------------------------------------------------
        # TIMER
        # -------------------------------------------------
        self.timer = QTimer()

        self.timer.timeout.connect(
            self.update_frame
        )

        # Around 30 FPS
        self.timer.setInterval(
            33
        )


    # =====================================================
    # START CAMERA
    # =====================================================
    def start_camera(self):

        print("\n🎥 Starting cameras...")

        success = self.camera.open()

        if success:

            self.timer.start()

            self.camera_label.setText(
                "Starting live camera..."
            )

        else:

            self.camera_label.setText(
                "❌ No camera connected"
            )


    # =====================================================
    # UPDATE LIVE FRAME
    # =====================================================
    def update_frame(self):

        frame = self.camera.get_frame()

        if frame is None:
            return

        # ---------------------------------------------
        # OpenCV BGR -> RGB
        # ---------------------------------------------
        rgb_frame = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB
        )

        height, width, channels = (
            rgb_frame.shape
        )

        bytes_per_line = (
            channels * width
        )

        qimage = QImage(
            rgb_frame.data,
            width,
            height,
            bytes_per_line,
            QImage.Format_RGB888
        )

        pixmap = QPixmap.fromImage(
            qimage
        )

        # ---------------------------------------------
        # Scale only for UI display.
        #
        # Original combined frame stays:
        # 7344 x 2048
        # ---------------------------------------------
        pixmap = pixmap.scaled(
            self.camera_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        self.camera_label.setPixmap(
            pixmap
        )


    # =====================================================
    # STOP CAMERA
    # =====================================================
    def stop_camera(self):

        print("\n🛑 Stopping cameras...")

        self.timer.stop()

        self.camera.close()

        self.camera_label.clear()

        self.camera_label.setText(
            "Camera stopped"
        )


    # =====================================================
    # WINDOW CLOSE
    # =====================================================
    def closeEvent(self, event):

        self.timer.stop()

        self.camera.close()

        event.accept()


# =========================================================
# RUN APPLICATION
# =========================================================
if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )

    window = CameraUI()

    window.show()

    sys.exit(
        app.exec_()
    )