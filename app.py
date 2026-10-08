# app.py
import sys
import json
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtCore import QUrl

from classes.bridge import Bridge
from classes.database import create_database_and_tables
from path import TEMPLATES_DIR,INDEX_PAGE,CONFIG_FILE
import os
import sys
os.environ["QT_QPA_PLATFORM"] = "xcb"

if getattr(sys, 'frozen', False):
    # PyInstaller bundle
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(sys._MEIPASS, "cv2", "qt", "plugins", "platforms")
    print("execute1")
else:
    # Running directly (venv)
    import cv2
    qt_plugin_path = os.path.join(os.path.dirname(cv2.__file__), "qt", "plugins", "platforms")
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = qt_plugin_path
    print("execute2")

def ensure_camera_settings():
    default_settings = {
        "camera_indexes": [0,2,4,6],

        "capture_step_mm": 20.0,

        "selected_job": {
            "Job_ID": "2903_black_jerscy",
            "roll_id": "13",
            "shift": "B",
            "operator_name": "Bala",
            "machine_number": "1",
            "fabric_type": "",
            "block_confidence": "128",
            "vertical_confidence": "189",
            "horizontal_confidence": "297",
            "new_vertical_confidence": "109",
            "new_horizontal_confidence": "134",
            "threshold_value": "100",
            "exposure": 20,
            "min_exposure": 0,
            "max_exposure": 15600
        }
    }

    try:
        # Make sure parent directory exists
        CONFIG_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        # If file already exists, don't overwrite it
        if CONFIG_FILE.exists():
            print(
                f"✅ Camera settings found: {CONFIG_FILE}"
            )
            return

        # Create default JSON
        with open(
            CONFIG_FILE,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                default_settings,
                file,
                indent=4
            )

        print(
            f"✅ Default camera settings created: "
            f"{CONFIG_FILE}"
        )

    except Exception as error:
        print(
            "❌ Camera settings creation error:",
            error
        )

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Table Inspection System")
        data = 1
        if data == 1:
            self.showMaximized()
        elif data == 2:
            self.resize(1200, 800)
        else:
            self.showFullScreen()

        # WebEngine View
        self.view = QWebEngineView()
        self.setCentralWidget(self.view)

        # Bridge & WebChannel
        self.bridge = Bridge(self)
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        # Load finished handler
        self.view.loadFinished.connect(self.on_load_finished)

        # Load initial page
        self.load_page(INDEX_PAGE)

    def load_page(self, page_name: str):
        print(f"Switching to page: {page_name}")

        file_path = (TEMPLATES_DIR / page_name).resolve()

        if file_path.exists():
            self.view.setUrl(QUrl("about:blank"))
            self.view.load(QUrl.fromLocalFile(str(file_path)))
        else:
            print(f"❌ Page not found: {file_path}")

    

    def closeEvent(self, event):
        self.bridge.stopCamera()  # Ask bridge to cleanup camera
        super().closeEvent(event)

    def on_load_finished(self, ok):
        print("✅ Page loaded successfully")


# ------------------- MAIN -------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    create_database_and_tables()
    ensure_camera_settings()
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
