import sys
from pathlib import Path
IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

# =====================================================
# CORE PATH HELPERS
# =====================================================
def app_path() -> Path:
    """
    Read-only application path
    - Normal run   → project root
    - PyInstaller  → _MEIPASS
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


# def run_path() -> Path:
#     """
#     Read/write runtime path
#     - Normal run   → project root
#     - PyInstaller  → exe folder
#     """
#     if getattr(sys, "frozen", False):
#         return Path(sys.executable).parent
#     return Path.cwd()

def run_path() -> Path:
    """
    Read/write runtime path
    - Normal run   → project root
    - PyInstaller  → exe folder
    """
    if IS_WINDOWS:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent

        return Path.cwd()

    elif IS_LINUX:
        path = Path.home() / "Documents"
        path.mkdir(parents=True, exist_ok=True)
        return path

    return Path.cwd()


# =====================================================
# READ-ONLY (BUNDLED) PATHS
# =====================================================

APP_DIR = app_path()

# CLASSES
CLASSES_DIR = APP_DIR / "classes"

# STATIC FILES
STATIC_DIR = APP_DIR / "static"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "script"
IMG_DIR = STATIC_DIR / "img"
FONTS_DIR = STATIC_DIR / "fonts"
WEBFONTS_DIR = STATIC_DIR / "webfonts"
LOGO_PATH = STATIC_DIR / "/logo / logo.png"

# TEMPLATES
TEMPLATES_DIR = APP_DIR / "templates"

INDEX_PAGE = TEMPLATES_DIR / "index.html"
TRAINING_PAGE = TEMPLATES_DIR / "traning.html"
CONTROLLER_PAGE = TEMPLATES_DIR / "controller.html"
REPORT_PAGE = TEMPLATES_DIR / "report.html"
SETTINGS_PAGE = TEMPLATES_DIR / "settings.html"




# =====================================================
# READ / WRITE (RUNTIME) PATHS
# =====================================================

RUN_DIR = run_path()

# App-specific runtime folder
RUN_DIR = RUN_DIR / "Table_data"
RUN_DIR.mkdir(parents=True, exist_ok=True)

# DATA DIRECTORIES
DATA_DIR = RUN_DIR / "data"
TRAINING_IMAGES_DIR = DATA_DIR / "training_images"
PREDICTION_IMAGES_DIR = DATA_DIR / "prediction_images"

# MODELS
MODELS_DIR = RUN_DIR / "models"
DEFAULT_MODEL = MODELS_DIR / "best.pt"

#CONFIG & DB
CONFIG_FILE = RUN_DIR / "camera_settings.json"
DB_PATH = RUN_DIR / "main_db.db"
BAD_IMG_SAVE = RUN_DIR / "bad_images"


LENGTH_FILE = RUN_DIR / "length.txt"

DEFECT_MAPPED_DIR= RUN_DIR / "defect_mapped"
DEFECT_RAW_DIR= RUN_DIR / "defect_raw"
REPORT_PATH= RUN_DIR /"reports"

# =====================================================
# ENSURE DIRECTORIES
# =====================================================

DATA_DIR.mkdir(parents=True, exist_ok=True)
TRAINING_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
PREDICTION_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)
DEFECT_MAPPED_DIR.mkdir(parents=True, exist_ok=True)
DEFECT_RAW_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH.mkdir(parents=True, exist_ok=True)
