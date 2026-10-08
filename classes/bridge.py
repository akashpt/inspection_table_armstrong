import cv2
import base64
import json
import numpy as np
import shutil
import sqlite3
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QThread
from ultralytics import settings
from path import (
    CONFIG_FILE,
    CONTROLLER_PAGE,
    DB_PATH,
    INDEX_PAGE,
    MODELS_DIR,
    REPORT_PAGE,
    SETTINGS_PAGE,
    TRAINING_IMAGES_DIR,
    TRAINING_PAGE,
    LENGTH_FILE,
)

import time
import os
from pathlib import Path
from datetime import datetime
# from classes.camera import WebCame as Camera
from classes.camera_manager import WebCame as Camera
from classes.plc import PLCController
from classes.prediction import VisionProcessor
from classes.report_generator import generate_defect_report_pdf

POLYGON_CONFIG_KEYS = {
    "polygon_points",
    "polygon_image_width",
    "polygon_image_height",
    "polygon_roi",
    "polygon_columns",
    "polygon_rows",
    "polygon_total_blocks",
}

def get_camera_settings():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    return {
        "camera_indexes": tuple(config.get("camera_indexes", [0, 2, 4, 6])),
        "exposure": int(config.get("exposure", 7000)),
        "min_exposure": int(config.get("min_exposure", 0)),
        "max_exposure": int(config.get("max_exposure", 15600)),
    }


class MultiCamWorker(QObject):
    frame_signal = pyqtSignal(str,object)
    status_signal = pyqtSignal(bool, str)

    def __init__(self, cam_indices=(0, 1, 4, 0), exposure=7000, fps=20):
        super().__init__()
        self.running = False
        self.camera = Camera(cam_indices=cam_indices,exposure=exposure,fps=fps)


    @pyqtSlot()
    def run(self):
        self.running = True

        if not self.camera.open():
            self.status_signal.emit(False, "No camera connected")
            return

        self.status_signal.emit(True, "Cameras started")

        delay_ms = int(1000 / self.camera.fps)

        while self.running:
            frame = self.camera.get_frame()

            if frame is not None:
                # print("📸 Combined camera frame:", frame.shape)
                ok, buffer = cv2.imencode(".jpg", frame)

                if ok:
                    jpg = base64.b64encode(buffer).decode("utf-8")
                    self.frame_signal.emit(jpg,frame)

            QThread.msleep(delay_ms)

        self.camera.close()
        self.status_signal.emit(False, "Cameras stopped")

    @pyqtSlot()
    def stop(self):
        self.running = False

    def get_latest_combined(self):
        return self.camera.get_latest_frame()

    def set_exposure(self, exposure):
        self.camera.set_exposure(exposure)


class ModelTrainingWorker(QObject):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, job_id, filenames=None):
        super().__init__()
        self.job_id = str(job_id or "").strip()
        self.filenames = list(filenames or [])

    @pyqtSlot()
    def run(self):
        try:
            from classes.training_effi_b2 import EffB2Trainer

            trainer = EffB2Trainer()
            # if self.filenames:
            #     threshold = trainer.train_from_files(
            #         self.job_id,
            #         self.filenames,
            #         progress_callback=self.progress_signal.emit,
            #     )
            # else:
            threshold = trainer.train_from_folder(self.job_id, progress_callback=self.progress_signal.emit)
            self.finished_signal.emit(True, f"Model trained: {self.job_id} ({threshold:.2f})")
        except Exception as e:
            self.finished_signal.emit(False, str(e))
            
    # @pyqtSlot()
    # def run(self):
    #     try:
    #         from classes.training_rgb import TrainingProcess

    #         trainer = TrainingProcess(self.job_id)
    #         trainer.run(progress_callback=self.progress_signal.emit)

    #         self.finished_signal.emit(True, f"Training completed: {self.job_id}")

    #     except Exception as e:
    #         self.finished_signal.emit(False, str(e))
    
class PredictionWorker(QObject):
    result_signal = pyqtSignal(str, str, object, object, object, object)
    error_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.vision = None

    @pyqtSlot(object, str)
    def process_frame(self, frame, job_id):
        if not self.running:
            return

        try:
            # Initialize inside prediction thread
            if self.vision is None:
                print("⏳ Loading VisionProcessor...")
                self.vision = VisionProcessor()
                print("✅ VisionProcessor loaded")

            if frame is None or frame.size == 0:
                self.error_signal.emit(
                    "Empty prediction frame"
                )
                return

            print(
                "🔍 Prediction worker received:",
                frame.shape,
            )
            

            status, code, image_path, defect_info, score, threshold = (
                self.vision.process_image(
                    frame=frame,
                    job_id=job_id,
                )
            )

            self.result_signal.emit(
                status,
                code,
                image_path,
                defect_info,
                score,
                threshold,
            )
        except Exception as e:
            self.error_signal.emit(str(e))

    def stop(self):
        self.running = False

class LengthWorker(QObject):
    length_signal = pyqtSignal(float)
    error_signal = pyqtSignal(str)

    def __init__(self, plc):
        super().__init__()
        self.plc = plc
        self.running = False
        self.last_value = None

    @pyqtSlot()
    def run(self):
        self.running = True

        print("✅ Encoder continuous checking started")

        while self.running:
            try:
                value = self.plc.read_length()

                if value is not None:
                    value = float(value)

                    # Emit only when encoder changes
                    if value != self.last_value:
                        self.last_value = value
                        self.length_signal.emit(value)

            except Exception as e:
                self.error_signal.emit(str(e))

            # Very small pause to avoid 100% CPU
            QThread.msleep(5)

    def stop(self):
        self.running = False
        
        
class Bridge(QObject):

    frame_signal = pyqtSignal(str)
    defect_signal = pyqtSignal(str)
    camera_status_signal = pyqtSignal(bool, str)
    model_training_signal = pyqtSignal(int, str, bool)
    prediction_request_signal = pyqtSignal(object, str)

    def __init__(self, app_ref):
        super().__init__()
        self.app_ref = app_ref

        self.last_frame = None  

        self.training_running = False
        self.current_training_job = ""
        self.capture_interval = 0.2   # 5 FPS
        self.last_capture_time = 0
        self.training_count = 0
        self.detection_running = False   

        self.camera_thread = None
        self.camera_worker = None
        
        self.predict_thread = None
        self.predict_worker = None
        self.model_training_thread = None
        self.model_training_worker = None
        
        self.last_prediction_time = 0
        self.prediction_interval = 5.0
        self.prediction_busy = False
        self.current_detection_job = ""
        self.last_polygon_config_warning_job = ""
        
        self.defect_popup_shown = False
        
        self.polygon_norm = None   # or load from settings/json
        
        self.plc = PLCController()
        self.plc.connect()
        self.last_length_value = None

        # ==============================
        # ENCODER D0 CONTINUOUS WORKER
        # ==============================
        self.length_thread = QThread()
        self.length_worker = LengthWorker(self.plc)

        self.length_worker.moveToThread(
            self.length_thread
        )

        self.length_thread.started.connect(
            self.length_worker.run
        )

        self.length_worker.length_signal.connect(
            self.handleLengthValue
        )

        self.length_worker.error_signal.connect(
            self.handleLengthError
        )

        self.length_thread.start()

        print("✅ Encoder D0 monitoring started")


        
    # ------------------- CAMERA -------------------
    @pyqtSlot()
    def startCamera(self):
        print("START clicked -> bridge camera start")

        # 6) Start 4 camera thread
        if self.camera_thread is not None:
            print("Camera already running")
            return

        self.camera_thread = QThread()
        settings = get_camera_settings()

        self.camera_worker = MultiCamWorker(
            cam_indices=settings["camera_indexes"],
            exposure=settings["exposure"]
        )
        # print(settings["exposure"])
        self.camera_worker.moveToThread(self.camera_thread)

        self.camera_thread.started.connect(self.camera_worker.run)
        self.camera_worker.frame_signal.connect(self._handle_camera_frame)
        self.camera_worker.status_signal.connect(self.camera_status_signal)

        self.camera_thread.start()

        print("✅ Camera thread started")
        
    def resize_frame_to_polygon_size(self, frame, job_id):
        if frame is None or frame.size == 0:
            print("❌ Empty frame")
            return None

        polygon_config = self._find_polygon_config(job_id)

        if not polygon_config:
            message = f"Polygon configuration not found: {job_id}"
            print("❌", message)
            safe_job = str(job_id or "").strip()
            if safe_job and self.last_polygon_config_warning_job != safe_job:
                self.last_polygon_config_warning_job = safe_job
                self.camera_status_signal.emit(False, message)
            return None

        try:
            polygon_width = int(
                float(
                    polygon_config.get(
                        "polygon_width",
                        0,
                    )
                )
            )

            polygon_height = int(
                float(
                    polygon_config.get(
                        "polygon_height",
                        0,
                    )
                )
            )

        except (TypeError, ValueError) as e:
            print("❌ Invalid polygon size:", e)
            return None

        if polygon_width <= 0 or polygon_height <= 0:
            print(
                "❌ Polygon width or height is invalid:",
                polygon_width,
                polygon_height,
            )
            return None

        resized_frame = cv2.resize(
            frame,
            (polygon_width, polygon_height),
            interpolation=cv2.INTER_AREA,
        )

        print("📷 Original frame:", frame.shape)
        print(
            "📐 Polygon size:",
            polygon_width,
            "x",
            polygon_height,
        )
        print("✅ Resized frame:", resized_frame.shape)

        return resized_frame
    
    def _start_prediction_worker(self):
        if self.predict_thread is not None:
            print("⚠️ Prediction worker already running")
            return

        self.predict_thread = QThread()
        self.predict_worker = PredictionWorker()

        self.predict_worker.moveToThread(
            self.predict_thread
        )

        self.prediction_request_signal.connect(
            self.predict_worker.process_frame
        )

        self.predict_worker.result_signal.connect(
            self._handle_prediction_result
        )

        self.predict_worker.error_signal.connect(
            self._handle_prediction_error
        )

        self.predict_thread.finished.connect(
            self.predict_worker.deleteLater
        )

        self.predict_thread.finished.connect(
            self.predict_thread.deleteLater
        )

        self.predict_thread.start()

        print("✅ Prediction worker started")
        
    @pyqtSlot(str, str, object, object, object, object)
    def _handle_prediction_result(
        self,
        status,
        code,
        image_path,
        defect_info,
        score,
        threshold,
    ):
        self.prediction_busy = False

        is_defect = str(status).strip().upper() in (
            "DEFECT",
            "BAD",
        )

        result_text = "BAD" if is_defect else "GOOD"

        print("\n" + "=" * 55)
        print("🔍 PREDICTION RESULT")
        print("=" * 55)
        print(f"Result          : {result_text}")
        print(f"Image Score     : {float(score):.4f}")
        print(f"Model Threshold : {float(threshold):.4f}")

        if is_defect:
            print(
                f"❌ BAD  -> Score {float(score):.4f} "
                f"> Threshold {float(threshold):.4f}"
            )
        else:
            print(
                f"✅ GOOD -> Score {float(score):.4f} "
                f"<= Threshold {float(threshold):.4f}"
            )

        print("=" * 55 + "\n")

        result = {
            "status": status,
            "code": code,
            "image_path": str(image_path or ""),
            "image_data": self._image_data_url(image_path),
            "defect_info": defect_info or [],
            "score": score,
            "threshold": threshold,
        }

        self.defect_signal.emit(json.dumps(result))

        if is_defect:
            # 1. Stop machine immediately
            try:
                self.plc.stop_machine()
                print("🛑 DEFECT detected -> Machine STOP D514 = 1")
            except Exception as error:
                print("❌ Machine stop error:", error)

            # 2. Stop camera
            self.stopCamera()

            self._save_defects_to_database(
                status=status,
                code=code,
                image_path=image_path,
                defect_info=defect_info,
            )

            self.camera_status_signal.emit(
                False,
                "Defect detected",
            )

    # def _save_defects_to_database(
    #         self,
    #         status,
    #         code,
    #         image_path,
    #         defect_info,
    #     ):
    #         connection = None

    #         try:
    #             settings = self._read_config()
    #             selected_job = settings.get("selected_job", {})

    #             job_id = selected_job.get("Job_ID")
    #             roll_id = selected_job.get("roll_id")
    #             machine_number = selected_job.get("machine_number")

    #             # Dummy value. Replace with PLC D0 meter later.
    #             defect_meter = 0

    #             result = str(status).strip().upper()
    #             saved_image_path = str(image_path or "")
    #             created_time = datetime.now().strftime(
    #                 "%Y-%m-%d %H:%M:%S"
    #             )

    #             if not isinstance(defect_info, list):
    #                 defect_info = [defect_info] if defect_info else []

    #             # Save one UNKNOWN row when result is defective,
    #             # but no defect details were returned.
    #             if not defect_info:
    #                 defect_info = [{
    #                     "defect_code": code,
    #                     "defect_type": "UNKNOWN",
    #                 }]

    #             connection = sqlite3.connect(DB_PATH)
    #             cursor = connection.cursor()

    #             inserted_count = 0

    #             for defect in defect_info:

    #                 if isinstance(defect, dict):
    #                     row_defect_code = (
    #                         defect.get("defect_code")
    #                         or defect.get("code")
    #                         or code
    #                         or ""
    #                     )

    #                     row_defect_type = (
    #                         defect.get("defect_type")
    #                         or defect.get("type")
    #                         or defect.get("name")
    #                         or defect.get("class_name")
    #                         or "UNKNOWN"
    #                     )
    #                 else:
    #                     row_defect_code = code or ""
    #                     row_defect_type = str(defect)

    #                 # Keep x and y as SQL NULL for now
    #                 defect_x = None
    #                 defect_y = None

    #                 cursor.execute("""
    #                     INSERT INTO defect_report_table (
    #                         job_id,
    #                         result,
    #                         defect_meter,
    #                         roll_id,
    #                         machine_number,
    #                         defect_code,
    #                         defect_type,
    #                         x,
    #                         y,
    #                         timestamp,
    #                         image_path
    #                     )
    #                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    #                 """, (
    #                     job_id,
    #                     result,
    #                     defect_meter,
    #                     roll_id,
    #                     machine_number,
    #                     str(row_defect_code),
    #                     str(row_defect_type),
    #                     defect_x,
    #                     defect_y,
    #                     created_time,
    #                     saved_image_path,
    #                 ))

    #                 inserted_count += 1

    #             connection.commit()

    #             print(
    #                 f"✅ Saved {inserted_count} defect row(s) "
    #                 f"to database"
    #             )

    #         except Exception as error:
    #             if connection:
    #                 connection.rollback()

    #             print("❌ Defect database insert error:", error)

    #         finally:
    #             if connection:
    #                 connection.close()

    def _save_defects_to_database(
        self,
        status,
        code,
        image_path,
        defect_info,
    ):
        connection = None

        try:
            settings = self._read_config()
            selected_job = settings.get("selected_job", {})

            job_id = selected_job.get("Job_ID")
            roll_id = selected_job.get("roll_id")
            machine_number = selected_job.get("machine_number")

            # =====================================================
            # GET DEFECT METER FROM length.txt
            # length.txt value is in mm
            # Example: 9840.0 mm -> 9.840 m
            # =====================================================
            try:
                with open(LENGTH_FILE, "r", encoding="utf-8") as file:
                    length_text = file.read().strip()

                length_mm = float(length_text) if length_text else 0.0
                defect_meter = round(length_mm / 1000.0, 3)

                print(
                    f"📏 Defect position: "
                    f"{length_mm:.1f} mm -> {defect_meter:.3f} m"
                )

            except Exception as error:
                print(
                    f"⚠️ Unable to read length file {LENGTH_FILE}:",
                    error
                )
                defect_meter = 0.0
            # =====================================================

            result = str(status).strip().upper()
            saved_image_path = str(image_path or "")

            created_time = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            if not isinstance(defect_info, list):
                defect_info = [defect_info] if defect_info else []

            if not defect_info:
                defect_info = [{
                    "defect_code": code,
                    "defect_type": "UNKNOWN",
                }]

            connection = sqlite3.connect(DB_PATH)
            cursor = connection.cursor()

            inserted_count = 0

            for defect in defect_info:

                if isinstance(defect, dict):

                    row_defect_code = (
                        defect.get("defect_code")
                        or defect.get("code")
                        or code
                        or ""
                    )

                    row_defect_type = (
                        defect.get("defect_type")
                        or defect.get("type")
                        or defect.get("name")
                        or defect.get("class_name")
                        or "UNKNOWN"
                    )

                else:
                    row_defect_code = code or ""
                    row_defect_type = str(defect)

                defect_x = None
                defect_y = None

                cursor.execute("""
                    INSERT INTO defect_report_table (
                        job_id,
                        result,
                        defect_meter,
                        roll_id,
                        machine_number,
                        defect_code,
                        defect_type,
                        x,
                        y,
                        timestamp,
                        image_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job_id,
                    result,
                    defect_meter,
                    roll_id,
                    machine_number,
                    str(row_defect_code),
                    str(row_defect_type),
                    defect_x,
                    defect_y,
                    created_time,
                    saved_image_path,
                ))

                inserted_count += 1

            connection.commit()

            print(
                f"✅ Saved {inserted_count} defect row(s) "
                f"at {defect_meter:.3f} m to database"
            )

        except Exception as error:

            if connection:
                connection.rollback()

            print("❌ Defect database insert error:", error)

        finally:

            if connection:
                connection.close()
                    
    def _image_data_url(self, image_path):
        safe_path = str(image_path or "").strip()
        if not safe_path:
            return ""

        path = Path(safe_path)
        if not path.is_absolute():
            path = Path.cwd() / path

        if not path.exists() or not path.is_file():
            return ""

        suffix = path.suffix.lower().lstrip(".") or "jpeg"
        mime = "jpeg" if suffix == "jpg" else suffix

        try:
            encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
            return f"data:image/{mime};base64,{encoded}"
        except Exception as e:
            print("Defect image encode failed:", e)
            return ""

    @pyqtSlot(str)
    def _handle_prediction_error(self, message):
        self.prediction_busy = False
        print("❌ Prediction failed:", message)
        
    # @pyqtSlot(str, object)
    # def _handle_camera_frame(self, jpg, frame):
    #     self.last_frame = jpg
    #     self.frame_signal.emit(jpg)
    #     data = self._read_config()
    #     print(
    #     "Frame received | Detection:",
    #     self.detection_running,
    # )
    #     # ==========================
    #     # DETECTION
    #     # ==========================
    #     if self.detection_running:
    #         if frame is None or frame.size == 0:
    #             print("❌ Empty prediction frame")
    #         elif not self.prediction_busy:
    #             now = time.time()

    #             if (
    #                 now - self.last_prediction_time
    #                 >= self.prediction_interval
    #             ):
    #                 # prediction_frame = (
    #                 #     self.resize_frame_to_polygon_size(
    #                 #         frame,
    #                 #         self.current_detection_job,
    #                 #     )
    #                 # )
    #                 self.current_detection_job = data['selected_job']['Job_ID']
    #                 # print('checking',)
    #                 polygon_config = self._find_polygon_config(self.current_detection_job)
                    
    #                 prediction_frame = self._crop_frame_to_polygon(frame, polygon_config)
    #                 if prediction_frame is None or prediction_frame.size == 0:
    #                     return 

    #                 if prediction_frame is not None:
    #                     self.last_prediction_time = now
    #                     self.prediction_busy = True

    #                     self.prediction_request_signal.emit(
    #                         prediction_frame,
    #                         self.current_detection_job,
    #                     )

    #     # ==========================
    #     # TRAINING
    #     # ==========================
    #     if not self.training_running or not self.current_training_job:
    #         return

    #     now = time.time()

    #     if now - self.last_capture_time < self.capture_interval:
    #         return

    #     self.last_capture_time = now
    #     self.training_count += 1

    #     job_dir = (
    #         TRAINING_IMAGES_DIR
    #         / self.current_training_job
    #     )
    #     job_dir.mkdir(parents=True, exist_ok=True)

    #     filename = (
    #         time.strftime("%Y%m%d_%H%M%S")
    #         + f"_{self.training_count:04d}.jpg"
    #     )

    #     save_path = job_dir / filename

    #     try:
    #         save_path.write_bytes(
    #             self._training_image_bytes(jpg)
    #         )
    #     except Exception as e:
    #         print("Training image save failed:", e)

    @pyqtSlot(str, object)
    def _handle_camera_frame(self, jpg, frame):

        # ==========================================
        # LIVE CAMERA FRAME
        # ==========================================
        self.last_frame = jpg
        self.frame_signal.emit(jpg)

        # ==========================================
        # DETECTION
        # ==========================================
        if self.detection_running:

            if frame is None or frame.size == 0:
                print("❌ Empty prediction frame")

            elif not self.prediction_busy:

                # Latest D0 encoder value
                current_length = self.last_length_value

                if current_length is None:
                    print("⚠️ Waiting for D0 encoder value")

                else:
                    try:
                        current_length = float(current_length)

                        # ==========================================
                        # FIRST D0 VALUE = START REFERENCE
                        # ==========================================
                        if self.last_capture_length is None:

                            self.last_capture_length = current_length

                            print(
                                f"📏 Prediction start position: "
                                f"{current_length:.2f} mm"
                            )

                        else:

                            travelled_mm = abs(
                                current_length
                                - self.last_capture_length
                            )

                            # ======================================
                            # CAPTURE EVERY capture_step_mm
                            # ======================================
                            if travelled_mm >= self.capture_step_mm:

                                print(
                                    f"📸 Capture step reached | "
                                    f"D0: {current_length:.2f} mm | "
                                    f"Travelled: {travelled_mm:.2f} mm | "
                                    f"Step: {self.capture_step_mm:.2f} mm"
                                )

                                polygon_config = (
                                    self._find_polygon_config(
                                        self.current_detection_job
                                    )
                                )

                                if polygon_config:

                                    prediction_frame = (
                                        self._crop_frame_to_polygon(
                                            frame,
                                            polygon_config
                                        )
                                    )

                                    if (
                                        prediction_frame is not None
                                        and prediction_frame.size > 0
                                    ):

                                        # Update position only when
                                        # frame is actually sent
                                        self.last_capture_length = (
                                            current_length
                                        )

                                        self.prediction_busy = True

                                        print(
                                            f"🔍 Sending prediction frame | "
                                            f"D0: {current_length:.2f} mm"
                                        )

                                        self.prediction_request_signal.emit(
                                            prediction_frame,
                                            self.current_detection_job,
                                        )

                                    else:
                                        print(
                                            "❌ Invalid prediction crop"
                                        )

                                else:
                                    print(
                                        "❌ Polygon configuration "
                                        "not found"
                                    )

                    except (TypeError, ValueError) as e:
                        print(
                            "❌ Invalid D0 encoder value:",
                            e
                        )

        # ==========================================
        # TRAINING
        # ==========================================
        if not self.training_running or not self.current_training_job:
            return

        now = time.time()

        if now - self.last_capture_time < self.capture_interval:
            return

        self.last_capture_time = now
        self.training_count += 1

        job_dir = (
            TRAINING_IMAGES_DIR
            / self.current_training_job
        )

        job_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        filename = (
            time.strftime("%Y%m%d_%H%M%S")
            + f"_{self.training_count:04d}.jpg"
        )

        save_path = job_dir / filename

        try:
            save_path.write_bytes(
                self._training_image_bytes(jpg)
            )

        except Exception as e:
            print(
                "Training image save failed:",
                e
            )

    def _training_image_bytes(self, jpg):
        raw = base64.b64decode(str(jpg).split(",", 1)[-1])
        config = self._current_training_config()

        if not config:
            return raw

        frame_array = np.frombuffer(raw, dtype=np.uint8)
        frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
        if frame is None:
            return raw

        cropped = self._crop_frame_to_polygon(frame, config)
        if cropped is None or cropped.size == 0:
            return raw

        ok, buffer = cv2.imencode(".jpg", cropped)
        if not ok:
            return raw

        return buffer.tobytes()

    def _current_training_config(self):
        # print(self.current_training_job)
        polygon_config = self._find_polygon_config(self.current_training_job)
        if polygon_config:
            return polygon_config

        data = self._read_config()
        return self._find_config(data, self.current_training_job)

    def _scaled_polygon_points(self, config, frame_width, frame_height):
        points = config.get("polygon_points", [])
        if not isinstance(points, list) or len(points) < 3:
            return None

        source_width = float(config.get("polygon_image_width") or frame_width)
        source_height = float(config.get("polygon_image_height") or frame_height)
        if source_width <= 0 or source_height <= 0:
            source_width = frame_width
            source_height = frame_height

        scaled = []
        for point in points:
            if not isinstance(point, dict):
                continue
            try:
                x = int(round(float(point.get("x", 0)) * frame_width / source_width))
                y = int(round(float(point.get("y", 0)) * frame_height / source_height))
            except (TypeError, ValueError):
                continue
            x = max(0, min(frame_width - 1, x))
            y = max(0, min(frame_height - 1, y))
            scaled.append([x, y])

        if len(scaled) < 3:
            return None

        return np.array(scaled, dtype=np.int32)

    def _crop_frame_to_polygon(self, frame, config):
        frame_height, frame_width = frame.shape[:2]
        points = self._scaled_polygon_points(config, frame_width, frame_height)

        if points is not None:
            mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
            cv2.fillPoly(mask, [points], 255)
            masked = cv2.bitwise_and(frame, frame, mask=mask)
            x, y, width, height = cv2.boundingRect(points)
            return masked[y:y + height, x:x + width]

        return self._crop_frame_to_roi(frame, config)

    def _crop_frame_to_roi(self, frame, config):
        roi = config.get("polygon_roi", {})
        if not isinstance(roi, dict):
            return frame

        frame_height, frame_width = frame.shape[:2]
        source_width = float(config.get("polygon_image_width") or frame_width)
        source_height = float(config.get("polygon_image_height") or frame_height)
        if source_width <= 0 or source_height <= 0:
            source_width = frame_width
            source_height = frame_height

        try:
            x1 = int(round(float(roi.get("x1", 0)) * frame_width / source_width))
            x2 = int(round(float(roi.get("x2", frame_width)) * frame_width / source_width))
            y1 = int(round(float(roi.get("y1", 0)) * frame_height / source_height))
            y2 = int(round(float(roi.get("y2", frame_height)) * frame_height / source_height))
        except (TypeError, ValueError):
            return frame

        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        x1 = max(0, min(frame_width - 1, x1))
        x2 = max(1, min(frame_width, x2))
        y1 = max(0, min(frame_height - 1, y1))
        y2 = max(1, min(frame_height, y2))

        if x2 <= x1 or y2 <= y1:
            return frame

        return frame[y1:y2, x1:x2]
    
    def _stop_prediction_worker(self):
        if self.predict_worker is not None:
            self.predict_worker.stop()

        if self.predict_thread is not None:
            self.predict_thread.quit()
            self.predict_thread.wait()

        self.predict_worker = None
        self.predict_thread = None
        self.prediction_busy = False

        print("✅ Prediction worker stopped")

    @pyqtSlot()
    def stopCamera(self):
        self.detection_running = False
        self.prediction_busy = False

        if self.camera_worker:
                self.camera_worker.stop()

        if self.camera_thread:
            self.camera_thread.quit()
            self.camera_thread.wait()

        self.camera_worker = None
        self.camera_thread = None
        
        if self.predict_worker:
            self.predict_worker.stop()

        self._stop_prediction_worker()
        self.frame_signal.emit("")
        print("✅ Camera thread stopped")
        

    # @pyqtSlot()
    # def resetSystem(self):
    #     # self.stopCamera()

    #     self.frame_signal.emit("")
    #     self.camera_status_signal.emit(False, "System reset")

    #     self.last_machine_state = None
    #     self.last_length_value = None
    #     self.last_capture_length = None
    #     self.capture_count = 0
    #     self.machine_stop_sent = False

    #     if self.plc is not None:
    #         if self.plc.reset_stop():
    #             print("✅ Reset: D514 = 0")
    #         else:
    #             print("❌ Reset: failed to clear D514")
                
    #     if self.predict_worker:
    #         self.predict_worker.machine_stop_sent = False
    #         self.predict_worker.last_capture_length = None
    #         self.predict_worker.capture_count = 0

    #     print("RESET button pressed")

    @pyqtSlot()
    def resetSystem(self):
        print("🔄 RESET button pressed")

        try:
            if self.plc is None:
                print("❌ PLC object is None")
                return

            print("➡️ Writing D514 = 0...")

            result = self.plc.reset_stop()

            print("PLC reset_stop() result:", result)

            if result:
                print("✅ Reset: D514 = 0")
            else:
                print("❌ Reset: write_register returned False/None")

        except Exception as error:
            print("❌ Reset PLC error:", error)

        self.last_machine_state = None
        self.last_length_value = None
        self.last_capture_length = None
        self.capture_count = 0
        self.machine_stop_sent = False

        if self.predict_worker is not None:
            self.predict_worker.machine_stop_sent = False
            self.predict_worker.last_capture_length = None
            self.predict_worker.capture_count = 0

    @pyqtSlot(result=str)
    def plcStatus(self):
        if self.plc is None:
            self.plc = PLCController()

        connected = self.plc.ensure_connected()
        return json.dumps({
            "ok": True,
            "connected": bool(connected),
            "message": "PLC connected" if connected else "PLC not connected",
        })

    def _navigation_allowed(self):
        if not self.detection_running:
            return True

        self.camera_status_signal.emit(
            True,
            "Stop prediction before opening another menu",
        )
        print("Navigation blocked: prediction is running")
        return False
        
        # ------------------- NAVIGATION -------------------
    @pyqtSlot()
    def goHome(self):
        if not self._navigation_allowed():
            return
        self.app_ref.load_page(INDEX_PAGE)

    @pyqtSlot()
    def goTraining(self):
        if not self._navigation_allowed():
            return
        self.app_ref.load_page(TRAINING_PAGE)

    # @pyqtSlot()
    # def home_page(self):
    #     self.goTraining()

    @pyqtSlot()
    def controller_page(self):
        if not self._navigation_allowed():
            return
        self.app_ref.load_page(CONTROLLER_PAGE)

    @pyqtSlot()
    def showReport(self):
        if not self._navigation_allowed():
            return
        self.app_ref.load_page(REPORT_PAGE)

    @pyqtSlot()
    def showSetting(self):
        if not self._navigation_allowed():
            return
        self.app_ref.load_page(SETTINGS_PAGE)

    def _ensure_operator_table(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS operator_table (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

    def _ensure_roll_timing_table(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS roll_timing_table (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    roll_id INTEGER,
                    start_time TEXT,
                    end_time TEXT,
                    operator_name TEXT,
                    machine_number TEXT,
                    job_id TEXT DEFAULT NULL
                )
            """)

            existing_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(roll_timing_table)").fetchall()
            }
            for column_name, column_type in (
                ("operator_name", "TEXT"),
                ("machine_number", "TEXT"),
                ("job_id", "TEXT DEFAULT NULL"),
            ):
                if column_name not in existing_columns:
                    conn.execute(
                        f"ALTER TABLE roll_timing_table ADD COLUMN {column_name} {column_type}"
                    )

            conn.commit()

    def _ensure_shift_table(self):
        default_shifts = (
            ("A", "06:00:00", "14:00:00"),
            ("B", "14:00:00", "22:00:00"),
            ("C", "22:00:00", "06:00:00"),
        )

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shift_table (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shift TEXT,
                    shift_start_time TEXT,
                    shift_end_time TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)

            existing = {
                str(row[0] or "").strip()
                for row in conn.execute("SELECT shift FROM shift_table").fetchall()
            }
            for shift, start_time, end_time in default_shifts:
                if shift not in existing:
                    conn.execute(
                        """
                        INSERT INTO shift_table (shift, shift_start_time, shift_end_time)
                        VALUES (?, ?, ?)
                        """,
                        (shift, start_time, end_time),
                    )

            conn.commit()

    def _shift_label(self, shift):
        value = str(shift or "").strip()
        return {
            "A": "Morning",
            "B": "Afternoon",
            "C": "Evening",
        }.get(value.upper(), value)

    def _shift_rows(self):
        self._ensure_shift_table()
        with sqlite3.connect(DB_PATH) as conn:
            return conn.execute(
                """
                SELECT shift, shift_start_time, shift_end_time
                FROM shift_table
                ORDER BY shift_start_time
                """
            ).fetchall()

    def _current_shift(self):
        now_time = datetime.now().time()

        for shift, start_time, end_time in self._shift_rows():
            try:
                start = datetime.strptime(str(start_time), "%H:%M:%S").time()
                end = datetime.strptime(str(end_time), "%H:%M:%S").time()
            except ValueError:
                continue

            if start <= end:
                in_shift = start <= now_time < end
            else:
                in_shift = now_time >= start or now_time < end

            if in_shift:
                label = self._shift_label(shift)
                return {
                    "shift": shift,
                    "label": label,
                    "display": f"{shift} - {label}",
                    "start_time": start_time,
                    "end_time": end_time,
                }

        return {}
    
    
    @pyqtSlot(float)
    def handleLengthValue(self, value):
        try:
            self.last_length_value = value

            LENGTH_FILE.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            LENGTH_FILE.write_text(
                str(value),
                encoding="utf-8"
            )

            print(
                f"📏 D0 Length saved: {value} mm"
            )

        except Exception as e:
            print(
                "❌ Failed to save length.txt:",
                e
            )
    
    @pyqtSlot(result=str)
    def currentLength(self):
        length_mm = None
        try:
            if LENGTH_FILE.exists():
                text = LENGTH_FILE.read_text(encoding="utf-8").strip()
                if text:
                    length_mm = float(text)
        except Exception as e:
            print("Length file read failed:", e)
            length_mm = None

        if length_mm is None:
            return json.dumps({
                "ok": False,
                "message": "Length not available",
                "length_mm": None,
                "length_m": None,
            })

        try:
            length_mm = float(length_mm)
        except (TypeError, ValueError):
            return json.dumps({
                "ok": False,
                "message": "Invalid length value",
                "length_mm": None,
                "length_m": None,
            })

        self.last_length_value = length_mm
        return json.dumps({
            "ok": True,
            "length_mm": length_mm,
            "length_m": length_mm / 1000,
        })
    
    @pyqtSlot(str)
    def handleLengthError(self, error):
        print("❌ Encoder D0 error:", error)

    @pyqtSlot(result=str)
    def listShifts(self):
        try:
            rows = self._shift_rows()

            shifts = [
                {
                    "shift": row[0],
                    "label": self._shift_label(row[0]),
                    "display": f"{row[0]} - {self._shift_label(row[0])}",
                    "start_time": row[1],
                    "end_time": row[2],
                }
                for row in rows
                if str(row[0] or "").strip()
            ]
            return json.dumps({"ok": True, "shifts": shifts})
        except Exception as e:
            return json.dumps({"ok": False, "message": str(e), "shifts": []})

    @pyqtSlot(result=str)
    def currentShift(self):
        try:
            shift = self._current_shift()
            return json.dumps({"ok": True, "shift": shift})
        except Exception as e:
            return json.dumps({"ok": False, "message": str(e), "shift": {}})

    def _operator_names(self):
        self._ensure_operator_table()
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT name FROM operator_table ORDER BY name COLLATE NOCASE"
            ).fetchall()

        names = []
        seen = set()
        for row in rows:
            name = str(row[0] or "").strip()
            key = name.lower()
            if name and key not in seen:
                names.append(name)
                seen.add(key)
        return names

    @pyqtSlot(result=str)
    def listOperatorNames(self):
        try:
            return json.dumps({"ok": True, "operators": self._operator_names()})
        except Exception as e:
            return json.dumps({"ok": False, "message": str(e), "operators": []})

    @pyqtSlot(str, result=str)
    def saveOperatorName(self, name):
        safe_name = str(name or "").strip()
        if not safe_name:
            return json.dumps({"ok": False, "message": "Operator name is required"})

        try:
            self._ensure_operator_table()
            with sqlite3.connect(DB_PATH) as conn:
                existing = conn.execute(
                    "SELECT id FROM operator_table WHERE lower(trim(name)) = lower(trim(?)) LIMIT 1",
                    (safe_name,),
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO operator_table (name) VALUES (?)",
                        (safe_name,),
                    )
                    conn.commit()

            return json.dumps({"ok": True, "message": "Operator saved", "operators": self._operator_names()})
        except Exception as e:
            return json.dumps({"ok": False, "message": str(e)})

    @pyqtSlot(str, result=str)
    def deleteOperatorName(self, name):
        safe_name = str(name or "").strip()
        if not safe_name:
            return json.dumps({"ok": False, "message": "Operator name is required"})

        try:
            self._ensure_operator_table()
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.execute(
                    "DELETE FROM operator_table WHERE lower(trim(name)) = lower(trim(?))",
                    (safe_name,),
                )
                conn.commit()

            return json.dumps({
                "ok": True,
                "message": "Operator deleted" if cursor.rowcount else "Operator not found",
                "operators": self._operator_names(),
            })
        except Exception as e:
            return json.dumps({"ok": False, "message": str(e)})
        


    # @pyqtSlot(str, str, str, result=str)
    # def createNewRoll(self, operator_name, machine_number, job_id):
    #     operator_name = str(operator_name or "").strip()
    #     # machine_number = str(machine_number or "").strip()
    #     job_id = str(job_id or "").strip()

    #     if not operator_name:
    #         return json.dumps({
    #             "ok": False,
    #             "message": "Operator name is required"
    #         })

    #     # if not machine_number:
    #     #     return json.dumps({
    #     #         "ok": False,
    #     #         "message": "Machine number is required"
    #     #     })

    #     if not job_id:
    #         return json.dumps({
    #             "ok": False,
    #             "message": "Job ID is required"
    #         })

    #     # Get local PC date and time
    #     current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    #     try:
    #         self._ensure_roll_timing_table()
    #         with sqlite3.connect(DB_PATH) as conn:
    #             cursor = conn.cursor()

    #             # Find the current active roll
    #             active_roll = cursor.execute("""
    #                 SELECT id, roll_id
    #                 FROM roll_timing_table
    #                 WHERE end_time IS NULL
    #                 OR TRIM(end_time) = ''
    #                 ORDER BY id DESC
    #                 LIMIT 1
    #             """).fetchone()

    #             # Fill the previous roll's end time
    #             if active_roll:
    #                 cursor.execute("""
    #                     UPDATE roll_timing_table
    #                     SET end_time = ?
    #                     WHERE id = ?
    #                 """, (
    #                     current_time,
    #                     active_roll[0]
    #                 ))

    #             # Get the next roll ID
    #             last_roll = cursor.execute("""
    #                 SELECT COALESCE(MAX(roll_id), 0)
    #                 FROM roll_timing_table
    #             """).fetchone()

    #             new_roll_id = int(last_roll[0]) + 1

    #             # Insert the new roll
    #             cursor.execute("""
    #                 INSERT INTO roll_timing_table (
    #                     roll_id,
    #                     start_time,
    #                     end_time,
    #                     operator_name,
    #                     machine_number,
    #                     job_id
    #                 )
    #                 VALUES (?, ?, NULL, ?, NULL, ?)
    #             """, (
    #                 new_roll_id,
    #                 current_time,
    #                 operator_name,
    #                 # machine_number,
    #                 job_id
    #             ))

    #             conn.commit()
                
    #             with open(CONFIG_FILE, "r", encoding="utf-8") as file:
    #                 settings = json.load(file)
                    
    #             if "selected_job" not in settings:
    #                 settings["selected_job"] = {}

    #             settings["selected_job"]["roll_id"] = str(new_roll_id)

    #             with open(CONFIG_FILE, "w", encoding="utf-8") as file:
    #                 json.dump(settings, file, indent=4)
    #                     # Mandatory success response to JavaScript
    #             return json.dumps({
    #                 "ok": True,
    #                 "roll_id": str(new_roll_id)
    #             })

    #     except Exception as error:
    #         return json.dumps({
    #             "ok": False,
    #             "message": str(error)
    #         })

    @pyqtSlot(str, str, str, result=str)
    def createNewRoll(self, operator_name, machine_number, job_id):

        operator_name = str(operator_name or "").strip()
        job_id = str(job_id or "").strip()

        if not operator_name:
            return json.dumps({
                "ok": False,
                "message": "Operator name is required"
            })

        if not job_id:
            return json.dumps({
                "ok": False,
                "message": "Job ID is required"
            })

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            self._ensure_roll_timing_table()

            previous_roll_id = None
            previous_roll_start = None
            previous_roll_end = None
            report_path = None

            # =====================================================
            # 1. CLOSE PREVIOUS ACTIVE ROLL
            # =====================================================
            with sqlite3.connect(DB_PATH) as conn:

                cursor = conn.cursor()

                active_roll = cursor.execute("""
                    SELECT
                        id,
                        roll_id,
                        start_time
                    FROM roll_timing_table
                    WHERE end_time IS NULL
                    OR TRIM(end_time) = ''
                    ORDER BY id DESC
                    LIMIT 1
                """).fetchone()

                if active_roll:

                    row_id = active_roll[0]
                    previous_roll_id = active_roll[1]
                    previous_roll_start = active_roll[2]
                    previous_roll_end = current_time

                    cursor.execute("""
                        UPDATE roll_timing_table
                        SET end_time = ?
                        WHERE id = ?
                    """, (
                        previous_roll_end,
                        row_id
                    ))

                    print(
                        f"✅ Roll {previous_roll_id} closed: "
                        f"{previous_roll_start} -> {previous_roll_end}"
                    )

                conn.commit()

            # =====================================================
            # 2. GENERATE REPORT FOR PREVIOUS ROLL
            # =====================================================
            if (
                previous_roll_id is not None
                and previous_roll_start
                and previous_roll_end
            ):

                try:

                    report_path = generate_defect_report_pdf(
                        report_type="roll",
                        start_time=previous_roll_start,
                        end_time=previous_roll_end,
                        roll_id=previous_roll_id,
                        exclude_defect_ids=[]
                    )

                    print(
                        f"✅ Roll {previous_roll_id} report created:"
                    )
                    print(report_path)

                except Exception as report_error:

                    # Do not stop new roll creation because
                    # report may have zero defects.
                    print(
                        f"⚠️ Roll {previous_roll_id} "
                        f"report generation failed:",
                        report_error
                    )

            # =====================================================
            # 3. CREATE NEW ROLL
            # =====================================================
            with sqlite3.connect(DB_PATH) as conn:

                cursor = conn.cursor()

                last_roll = cursor.execute("""
                    SELECT COALESCE(MAX(roll_id), 0)
                    FROM roll_timing_table
                """).fetchone()

                new_roll_id = int(last_roll[0]) + 1

                cursor.execute("""
                    INSERT INTO roll_timing_table (
                        roll_id,
                        start_time,
                        end_time,
                        operator_name,
                        machine_number,
                        job_id
                    )
                    VALUES (?, ?, NULL, ?, NULL, ?)
                """, (
                    new_roll_id,
                    current_time,
                    operator_name,
                    job_id
                ))

                conn.commit()

            # =====================================================
            # 4. UPDATE CONFIG.JSON
            # =====================================================
            with open(
                CONFIG_FILE,
                "r",
                encoding="utf-8"
            ) as file:

                settings = json.load(file)

            if "selected_job" not in settings:
                settings["selected_job"] = {}

            settings["selected_job"]["roll_id"] = str(
                new_roll_id
            )

            with open(
                CONFIG_FILE,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    settings,
                    file,
                    indent=4
                )

            print(
                f"✅ New roll created: {new_roll_id}"
            )

            # =====================================================
            # 5. RETURN RESULT TO JAVASCRIPT
            # =====================================================
            return json.dumps({
                "ok": True,
                "roll_id": str(new_roll_id),
                "previous_roll_id": (
                    str(previous_roll_id)
                    if previous_roll_id is not None
                    else None
                ),
                "report_path": report_path
            })

        except Exception as error:

            print(
                "❌ Create new roll error:",
                error
            )

            return json.dumps({
                "ok": False,
                "message": str(error)
            })

    def _read_config(self):
        try:
            if CONFIG_FILE.exists():
                return json.loads(CONFIG_FILE.read_text(encoding="utf-8") or "{}")
        except Exception as e:
            print("Config read failed:", e)
        return {}

    def _write_config(self, data):
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._strip_polygon_config_data(data)
            if isinstance(data, dict):
                data.pop("job_configs", None)
            CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True, ""
        except Exception as e:
            print("Config write failed:", e)
            return False, str(e)

    @pyqtSlot(result=str)
    def controllerCameraSettings(self):
        settings = get_camera_settings()
        return json.dumps({
            "ok": True,
            "exposure": settings["exposure"],
            "min_exposure": settings["min_exposure"],
            "max_exposure": settings["max_exposure"],
        })

    @pyqtSlot(result=str)
    def settings_json(self):
        data = self._read_config()
        return json.dumps({
            "ok": True,
            "settings": {
                "camera_indexes": data.get("camera_indexes", [0, 1, 2, 3]),
                "capture_step_mm": data.get("capture_step_mm", ""),
                "exposure": data.get("exposure", 7000),
                "min_exposure": data.get("min_exposure", 0),
                "max_exposure": data.get("max_exposure", 15600),
            },
        })

    def _parse_camera_indexes(self, value):
        if isinstance(value, list):
            items = value
        else:
            items = str(value or "").replace(";", ",").split(",")

        indexes = []
        for item in items:
            text = str(item or "").strip()
            if text == "":
                continue
            indexes.append(int(text))

        if not indexes:
            raise ValueError("Enter at least one camera index")

        return indexes

    @pyqtSlot(str, result=str)
    def save_settings_json(self, settings_json="{}"):
        try:
            settings = json.loads(settings_json or "{}")
            if not isinstance(settings, dict):
                settings = {}
        except Exception:
            return json.dumps({"ok": False, "message": "Invalid JSON settings"})

        try:
            camera_indexes = self._parse_camera_indexes(settings.get("camera_indexes", ""))
            capture_step_mm = float(str(settings.get("capture_step_mm") or 0).strip())
            exposure = int(float(str(settings.get("exposure") or 0).strip()))
            min_exposure = int(float(str(settings.get("min_exposure") or 0).strip()))
            max_exposure = int(float(str(settings.get("max_exposure") or 0).strip()))
        except ValueError as error:
            return json.dumps({"ok": False, "message": str(error) or "Enter valid JSON settings"})

        if min_exposure > max_exposure:
            return json.dumps({"ok": False, "message": "Min exposure cannot be greater than max exposure"})

        if exposure < min_exposure or exposure > max_exposure:
            return json.dumps({
                "ok": False,
                "message": f"Exposure must be between {min_exposure} and {max_exposure}",
            })

        data = self._read_config()
        data.update({
            "camera_indexes": camera_indexes,
            "capture_step_mm": capture_step_mm,
            "exposure": exposure,
            "min_exposure": min_exposure,
            "max_exposure": max_exposure,
        })

        ok, message = self._write_config(data)
        if not ok:
            return json.dumps({"ok": False, "message": message or "Unable to save JSON settings"})

        if self.camera_worker is not None:
            self.camera_worker.set_exposure(exposure)

        return json.dumps({
            "ok": True,
            "message": "JSON settings saved",
            "settings": {
                "camera_indexes": camera_indexes,
                "capture_step_mm": capture_step_mm,
                "exposure": exposure,
                "min_exposure": min_exposure,
                "max_exposure": max_exposure,
            },
        })

    @pyqtSlot(str, result=str)
    def saveControllerExposure(self, exposure):
        try:
            value = int(float(str(exposure or "").strip()))
        except ValueError:
            return json.dumps({"ok": False, "message": "Enter a valid exposure value"})

        settings = get_camera_settings()
        min_exposure = settings["min_exposure"]
        max_exposure = settings["max_exposure"]

        if value < min_exposure or value > max_exposure:
            return json.dumps({
                "ok": False,
                "message": f"Exposure must be between {min_exposure} and {max_exposure}",
            })

        data = self._read_config()
        data["exposure"] = value
        data.setdefault("min_exposure", min_exposure)
        data.setdefault("max_exposure", max_exposure)

        ok, message = self._write_config(data)
        if not ok:
            return json.dumps({"ok": False, "message": message or "Unable to save exposure"})

        if self.camera_worker is not None:
            self.camera_worker.set_exposure(value)

        return json.dumps({
            "ok": True,
            "message": f"Exposure saved: {value}",
            "exposure": value,
        })

    def _strip_polygon_config(self, config):
        if not isinstance(config, dict):
            return config
        for key in POLYGON_CONFIG_KEYS:
            config.pop(key, None)
        return config

    def _strip_polygon_config_data(self, data):
        if not isinstance(data, dict):
            return data

        configs = data.get("job_configs")
        if isinstance(configs, dict):
            for config in configs.values():
                if isinstance(config, dict):
                    self._strip_polygon_config(config)

        selected_job = data.get("selected_job")
        if isinstance(selected_job, dict):
            self._strip_polygon_config(selected_job)

        return data

    def _polygon_settings_file(self, job_id):
        safe_job = str(job_id or "").strip()
        if not safe_job:
            return None
        return TRAINING_IMAGES_DIR / safe_job / "polygon_settings.json"

    def _read_polygon_config(self, job_id):
        polygon_file = self._polygon_settings_file(job_id)
        try:
            if polygon_file and polygon_file.exists():
                data = json.loads(polygon_file.read_text(encoding="utf-8") or "{}")
                return data if isinstance(data, dict) else {}
        except Exception as e:
            print("Polygon config read failed:", e)
        return {}

    def _write_polygon_config(self, job_id, data):
        polygon_file = self._polygon_settings_file(job_id)
        if not polygon_file:
            return False, "Job ID is required"

        try:
            polygon_file.parent.mkdir(parents=True, exist_ok=True)
            polygon_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True, ""
        except Exception as e:
            print("Polygon config write failed:", e)
            return False, str(e)

    def _polygon_configs(self, data):
        configs = data.get("job_polygons")
        if not isinstance(configs, dict):
            configs = {}
            data["job_polygons"] = configs
        return configs

    def _find_polygon_config(self, job_id):
        safe_job = str(job_id or "").strip()
        if not safe_job:
            return None

        data = self._read_polygon_config(safe_job)
        config = self._polygon_configs(data).get(safe_job)
        return config if isinstance(config, dict) else None

    @pyqtSlot(str, result=str)
    def has_training_polygon(self, job_id):
        config = self._find_polygon_config(job_id)
        points = config.get("polygon_points") if isinstance(config, dict) else None
        return json.dumps({
            "ok": True,
            "has_polygon": isinstance(points, list) and len(points) >= 3,
        })

    def _polygon_dimensions(self, config):
        if not isinstance(config, dict):
            return {}

        dimensions = {}
        for source_key, target_key in (
            ("polygon_width", "polygon_width"),
            ("polygon_height", "polygon_height"),
            ("polygon_image_width", "polygon_image_width"),
            ("polygon_image_height", "polygon_image_height"),
        ):
            value = config.get(source_key)
            if value not in (None, ""):
                dimensions[target_key] = value

        if "polygon_width" not in dimensions or "polygon_height" not in dimensions:
            roi = config.get("polygon_roi")
            if isinstance(roi, dict):
                try:
                    width = abs(float(roi.get("x1", 0)) - float(roi.get("x0", 0)))
                    height = abs(float(roi.get("y2", 0)) - float(roi.get("y0", 0)))
                    dimensions.setdefault("polygon_width", int(width) if width.is_integer() else width)
                    dimensions.setdefault("polygon_height", int(height) if height.is_integer() else height)
                except (TypeError, ValueError):
                    pass

        return dimensions

    def _sync_camera_polygon_dimensions(self, job_id, polygon_config):
        safe_job = str(job_id or "").strip()
        dimensions = self._polygon_dimensions(polygon_config)
        if not safe_job or not dimensions:
            return

        data = self._read_config()
        selected_job = data.get("selected_job")
        if not isinstance(selected_job, dict):
            return

        selected_id = selected_job.get("Job_ID") or selected_job.get("job_id")
        if str(selected_id or "") != safe_job:
            return

        selected_job.update(dimensions)
        self._write_config(data)

    def _delete_polygon_config(self, job_id):
        safe_job = str(job_id or "").strip()
        if not safe_job:
            return

        data = self._read_polygon_config(safe_job)
        configs = self._polygon_configs(data)
        if safe_job in configs:
            configs.pop(safe_job, None)
            if data.get("selected_job") == safe_job:
                data["selected_job"] = ""
            self._write_polygon_config(safe_job, data)


    @pyqtSlot(result=str)
    def latest_camera_frame(self):
        try:
            frame = self.last_frame

            if frame is None or frame.size == 0:
                return ""

            ok, buffer = cv2.imencode(".jpg", frame)

            if not ok:
                return ""

            return base64.b64encode(buffer).decode("utf-8")

        except Exception as e:
            print("❌ latest_camera_frame error:", e)

            
            return ""
    @pyqtSlot(result=str)
    def get_polygon_frame(self):
        camera = None

        try:
            settings = get_camera_settings()

            camera = Camera(
                cam_indices=settings["camera_indexes"],
                exposure=settings["exposure"],
                fps=20,
            )

            if not camera.open():
                return json.dumps({
                    "ok": False,
                    "message": "Camera open failed"
                })

            # Grab only ONE combined frame
            frame = camera.get_frame()

            if frame is None or frame.size == 0:
                return json.dumps({
                    "ok": False,
                    "message": "Frame capture failed"
                })

            print(
                "📸 Polygon frame:",
                frame.shape
            )

            ok, buffer = cv2.imencode(
                ".jpg",
                frame
            )

            if not ok:
                return json.dumps({
                    "ok": False,
                    "message": "Frame encode failed"
                })

            image_base64 = base64.b64encode(
                buffer
            ).decode("utf-8")

            return json.dumps({
                "ok": True,
                "image": "data:image/jpeg;base64," + image_base64,
                "width": frame.shape[1],
                "height": frame.shape[0],
            })

        except Exception as e:
            print(
                "❌ Polygon frame error:",
                e
            )

            return json.dumps({
                "ok": False,
                "message": str(e)
            })

        finally:
            if camera is not None:
                try:
                    camera.close()
                except Exception as e:
                    print(
                        "❌ Polygon camera close error:",
                        e
                    )

    def _combined_job_id(self, job_id, roll_color, polygon_size):
        parts = [job_id, roll_color, polygon_size]
        return "_".join(str(part or "").strip() for part in parts)

    def _job_configs(self, data):
        configs = data.get("job_configs")
        return configs if isinstance(configs, dict) else {}

    def _find_config(self, data, job_id):
        safe_job = str(job_id or "").strip()
        if not safe_job:
            return None

        configs = self._job_configs(data)
        if safe_job in configs:
            return configs[safe_job]

        selected_job = data.get("selected_job")
        if isinstance(selected_job, dict):
            selected_id = selected_job.get("Job_ID") or selected_job.get("job_id")
            if str(selected_id or "") == safe_job:
                return selected_job

        return None

    @pyqtSlot(str)
    def startTraining(self, job_id=""):
        print("🚀 Training Started")

        self.current_training_job = str(job_id or "").strip()
        self.training_running = True
        self.training_count = 0
        self.last_capture_time = 0

        # start camera if not running
        self.startCamera()

    @pyqtSlot()
    def stopTraining(self):
        print("🛑 Training Stopped")

        self.training_running = False

        # 🔥 STOP CAMERA (IMPORTANT FIX)
        self.stopCamera()

        self.camera_status_signal.emit(False, "Training stopped")

    def _is_model_training(self):
        return self.model_training_thread is not None

    @pyqtSlot(str, result=str)
    def startModelTraining(self, job_id):
        return self._start_model_training(job_id)

    @pyqtSlot(str, str, result=str)
    def startModelTrainingImage(self, job_id, filename):
        safe_name = os.path.basename(str(filename or ""))
        if not safe_name:
            return json.dumps({"ok": False, "message": "Image is required"})

        return self._start_model_training(job_id, [safe_name])

    def _start_model_training(self, job_id, filenames=None):
        safe_job = str(job_id or "").strip()
        if not safe_job:
            return json.dumps({"ok": False, "message": "Job ID is required"})

        if self._is_model_training():
            return json.dumps({"ok": False, "message": "Model training already running"})

        job_dir = TRAINING_IMAGES_DIR / safe_job
        if not job_dir.exists():
            return json.dumps({"ok": False, "message": f"No training images found for {safe_job}"})

        selected_files = list(filenames or [])
        if selected_files:
            for filename in selected_files:
                safe_name = os.path.basename(str(filename or ""))
                if not safe_name or not (job_dir / safe_name).exists():
                    return json.dumps({"ok": False, "message": "Selected image not found"})

        self.model_training_thread = QThread()
        self.model_training_worker = ModelTrainingWorker(safe_job, selected_files)
        self.model_training_worker.moveToThread(self.model_training_thread)

        self.model_training_thread.started.connect(self.model_training_worker.run)
        self.model_training_worker.progress_signal.connect(
            lambda percent, message: self.model_training_signal.emit(percent, message, True)
        )
        self.model_training_worker.finished_signal.connect(self._handle_model_training_finished)
        self.model_training_worker.finished_signal.connect(self.model_training_thread.quit)
        self.model_training_thread.finished.connect(self.model_training_worker.deleteLater)
        self.model_training_thread.finished.connect(self.model_training_thread.deleteLater)
        self.model_training_thread.finished.connect(self._clear_model_training_worker)

        target = selected_files[0] if selected_files else safe_job
        self.model_training_signal.emit(0, f"Training model: {target}", True)
        self.model_training_thread.start()
        return json.dumps({"ok": True, "message": f"Model training started: {target}"})

    @pyqtSlot(bool, str)
    def _handle_model_training_finished(self, ok, message):
        self.model_training_signal.emit(100 if ok else 0, message, False)

    @pyqtSlot()
    def _clear_model_training_worker(self):
        self.model_training_thread = None
        self.model_training_worker = None

    @pyqtSlot(str, result=str)
    def deleteTrainingJob(self, job_id):
        safe_job = str(job_id or "").strip()
        if not safe_job:
            return json.dumps({"ok": False, "message": "Job ID is required"})

        if safe_job == self.current_training_job and self.training_running:
            return json.dumps({"ok": False, "message": "Stop training before deleting this job"})

        removed = []
        for base_dir, label in ((TRAINING_IMAGES_DIR, "images"), (MODELS_DIR, "model")):
            target = (base_dir / safe_job).resolve()
            root = base_dir.resolve()
            if not str(target).startswith(str(root)) or target == root:
                return json.dumps({"ok": False, "message": "Invalid job path"})
            if target.exists():
                shutil.rmtree(target)
                removed.append(label)

        self._delete_polygon_config(safe_job)

        message = "Deleted " + ", ".join(removed) if removed else "Nothing found to delete"
        return json.dumps({"ok": True, "message": message})

    @pyqtSlot(result=str)
    def job_options(self):
        return self.config_options()

    @pyqtSlot(result=str)
    def config_options(self):
        jobs = self._model_job_names()

        return json.dumps([{"job_id": job} for job in sorted(set(jobs))])

    def _training_job_names(self):
        jobs = []
        try:
            if TRAINING_IMAGES_DIR.exists():
                for item in TRAINING_IMAGES_DIR.iterdir():
                    if item.is_dir():
                        jobs.append(item.name)
        except Exception as e:
            print("training folder options read failed:", e)
        return jobs

    def _model_job_names(self):
        jobs = []
        try:
            if MODELS_DIR.exists():
                for item in MODELS_DIR.iterdir():
                    if item.is_dir():
                        jobs.append(item.name)
        except Exception as e:
            print("model folder options read failed:", e)
        return jobs

    @pyqtSlot(result=str)
    def source_job_options(self):
        jobs = []

        try:
            data = self._read_config()
            for config in self._job_configs(data).values():
                if not isinstance(config, dict):
                    continue
                job_id = config.get("source_job_id") or config.get("Job_ID") or config.get("job_id")
                safe_job = str(job_id or "").strip()
                if safe_job:
                    jobs.append(safe_job)
        except Exception as e:
            print("source_job_options settings read failed:", e)

        return json.dumps([{"job_id": job} for job in sorted(set(jobs))])

    @pyqtSlot(result=str)
    def trained_model_options(self):
        jobs = self._model_job_names()

        return json.dumps([{"job_id": job} for job in sorted(set(jobs))])

    @pyqtSlot(result=str)
    def selected_config(self):
        data = self._read_config()
        selected_job = data.get("selected_job", {})
        selected = ""

        if isinstance(selected_job, dict):
            selected = selected_job.get("Job_ID") or selected_job.get("job_id") or ""

        return json.dumps({"ok": True, "selected": str(selected)})

    @pyqtSlot(str, result=str)
    def get_config(self, job_id):
        data = self._read_config()
        config = self._find_config(data, job_id)

        if not config:
            safe_job = str(job_id or "").strip()
            if safe_job in set(self._model_job_names()):
                config = {"Job_ID": safe_job}
            else:
                return json.dumps({"ok": False, "message": "Configuration not found"})

        settings_keys = [
            "roll_id",
            "shift",
            "operator_name",
            "machine_number",
            "fabric_type",
            "block_confidence",
            "vertical_confidence",
            "horizontal_confidence",
            "new_vertical_confidence",
            "new_horizontal_confidence",
            "threshold_value",
        ]
        settings = {
            key: config.get(key, "")
            for key in settings_keys
            if key in config
        }

        return json.dumps({
            "ok": True,
            "config": {
                "job_id": config.get("Job_ID") or config.get("job_id") or str(job_id),
                "roll_color": config.get("roll_color", ""),
                "polygon_size": config.get("polygon_size", ""),
                "settings": settings,
            },
        })

    @pyqtSlot(str, str, result=str)
    def save_selected_config(self, job_id, settings_json="{}"):
        safe_job = str(job_id or "").strip()
        if not safe_job:
            return json.dumps({"ok": False, "message": "Configuration is required"})

        try:
            settings = json.loads(settings_json or "{}")
            if not isinstance(settings, dict):
                settings = {}
        except Exception:
            settings = {}

        data = self._read_config()
        existing_config = self._find_config(data, safe_job) or {"Job_ID": safe_job}
        config = self._strip_polygon_config(existing_config.copy())
        config["Job_ID"] = safe_job

        operator_name = str(settings.get("operator_name") or "").strip()
        if operator_name:
            saved = json.loads(self.saveOperatorName(operator_name) or "{}")
            if not saved.get("ok"):
                return json.dumps({"ok": False, "message": saved.get("message", "Operator save failed")})

        config.update(settings)
        data["selected_job"] = config.copy()

        ok, message = self._write_config(data)
        return json.dumps({"ok": ok, "message": message, "selected": safe_job})

    @pyqtSlot(str, str, result=str)
    def save_training_polygon(self, job_id, polygon_json="{}"):
        safe_job = str(job_id or "").strip()
        if not safe_job:
            return json.dumps({"ok": False, "message": "Configuration is required"})

        try:
            polygon = json.loads(polygon_json or "{}")
            points = polygon.get("points", [])
            if not isinstance(points, list) or len(points) < 3:
                return json.dumps({"ok": False, "message": "Draw at least 3 polygon points"})
        except Exception:
            return json.dumps({"ok": False, "message": "Invalid polygon data"})

        data = self._read_polygon_config(safe_job)
        configs = self._polygon_configs(data)
        configs[safe_job] = {
            "Job_ID": safe_job,
            "polygon_points": points,
            "polygon_image_width": polygon.get("image_width", 0),
            "polygon_image_height": polygon.get("image_height", 0),
            "polygon_width": polygon.get("polygon_width", 0),
            "polygon_height": polygon.get("polygon_height", 0),
            "polygon_roi": {
                "x0": polygon.get("x0", 0),
                "y0": polygon.get("y0", 0),
                "x1": polygon.get("x1", 0),
                "y1": polygon.get("y1", 0),
                "x2": polygon.get("x2", 0),
                "y2": polygon.get("y2", 0),
            },
        }
        data["selected_job"] = safe_job

        ok, message = self._write_polygon_config(safe_job, data)
        if ok:
            self._sync_camera_polygon_dimensions(safe_job, configs[safe_job])
        return json.dumps({"ok": ok, "message": message, "selected": safe_job})

    @pyqtSlot(str, str, str, result=str)
    def saveTrainingConfig(self, job_id, roll_color, polygon_size):
        source_job = str(job_id or "").strip()
        safe_roll = str(roll_color or "").strip()
        safe_polygon = str(polygon_size or "").strip()

        if not source_job or not safe_roll or not safe_polygon:
            return json.dumps({"ok": False, "message": "JOB ID, ROLL COLOR and POLYGON SIZE are required"})

        combined = self._combined_job_id(source_job, safe_roll, safe_polygon)
        data = self._read_config()

        base = self._find_config(data, source_job) or {}
        config = self._strip_polygon_config(base.copy())
        config.update({
            "Job_ID": combined,
            "source_job_id": source_job,
            "roll_color": safe_roll,
            "polygon_size": safe_polygon,
        })
        config.update(self._polygon_dimensions(self._find_polygon_config(combined)))

        data["selected_job"] = config.copy()

        ok, message = self._write_config(data)
        return json.dumps({
            "ok": ok,
            "message": message,
            "combined": combined,
        })

    def _training_image_filenames(self, job_id):
        safe_job = str(job_id or "").strip()
        if not safe_job:
            return []

        job_dir = TRAINING_IMAGES_DIR / safe_job
        if not job_dir.exists():
            return []

        image_exts = {".jpg", ".jpeg", ".png", ".bmp"}
        return sorted(
            item.name
            for item in job_dir.iterdir()
            if item.is_file() and item.suffix.lower() in image_exts
        )

    @pyqtSlot(str, result=str)
    def getTrainingCaptureStatus(self, job_id):
        filenames = self._training_image_filenames(job_id)
        is_current = str(job_id or "").strip() == self.current_training_job

        return json.dumps({
            "ok": True,
            "session_count": self.training_count if is_current else 0,
            "folder_count": len(filenames),
        })

    @pyqtSlot(str, result=str)
    def getTrainingImageFilenames(self, job_id):
        return json.dumps({
            "ok": True,
            "filenames": self._training_image_filenames(job_id),
        })

    @pyqtSlot(str, str, result=str)
    def getTrainingImage(self, job_id, filename):
        safe_job = str(job_id or "").strip()
        safe_name = os.path.basename(str(filename or ""))
        image_path = TRAINING_IMAGES_DIR / safe_job / safe_name

        if not safe_job or not safe_name or not image_path.exists():
            return json.dumps({
                "ok": False,
                "message": "Image not found",
                "path": str(image_path),
            })

        try:
            encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
            suffix = image_path.suffix.lower().lstrip(".") or "jpeg"
            mime = "jpeg" if suffix == "jpg" else suffix
            return json.dumps({
                "ok": True,
                "data": f"data:image/{mime};base64,{encoded}",
            })
        except Exception as e:
            return json.dumps({"ok": False, "message": str(e)})

    @pyqtSlot(str, str, result=str)
    def deleteTrainingImage(self, job_id, filename):
        safe_job = str(job_id or "").strip()
        safe_name = os.path.basename(str(filename or ""))
        image_path = TRAINING_IMAGES_DIR / safe_job / safe_name

        if not safe_job or not safe_name or not image_path.exists():
            return json.dumps({"ok": False, "message": "Image not found"})

        try:
            image_path.unlink()
            return json.dumps({"ok": True, "message": f"Deleted image: {safe_name}"})
        except Exception as e:
            return json.dumps({"ok": False, "message": str(e)})


    @pyqtSlot()
    def startDetection(self):

        # ==========================================
        # 1. CHECK PLC CONNECTION
        # ==========================================
        if self.plc is None:
            self.plc = PLCController()

        if not self.plc.ensure_connected():
            print("❌ PLC not connected")

            self.camera_status_signal.emit(
                False,
                "PLC not connected"
            )
            return

        # ==========================================
        # 2. CHECK MACHINE STATUS - D512
        # ==========================================
        try:
            machine_status = self.plc.machine_status()

            print(
                "⚙️ D512 Machine Status:",
                machine_status
            )

            if machine_status is None:
                self.camera_status_signal.emit(
                    False,
                    "Unable to read machine status"
                )
                return

            if int(machine_status) != 1:
                print("❌ Machine is not ON")

                self.camera_status_signal.emit(
                    False,
                    "Machine not ON"
                )
                return

        except Exception as e:
            print(
                "❌ Machine status read error:",
                e
            )

            self.camera_status_signal.emit(
                False,
                "Machine status read failed"
            )
            return

        # ==========================================
        # 3. READ SETTINGS
        # ==========================================
        data = self._read_config()

        selected_job = data.get(
            "selected_job",
            {}
        )

        if not isinstance(selected_job, dict):
            print("❌ Selected job configuration not found")

            self.camera_status_signal.emit(
                False,
                "Selected job configuration not found"
            )
            return

        # ==========================================
        # 4. GET JOB ID
        # ==========================================
        self.current_detection_job = str(
            selected_job.get("Job_ID")
            or selected_job.get("job_id")
            or ""
        ).strip()

        if not self.current_detection_job:
            print("❌ Detection Job ID is empty")

            self.camera_status_signal.emit(
                False,
                "Detection Job ID is empty"
            )
            return

        # ==========================================
        # 5. CHECK POLYGON
        # ==========================================
        if not self._find_polygon_config(
            self.current_detection_job
        ):
            message = (
                "Polygon configuration not found: "
                f"{self.current_detection_job}"
            )

            print("❌", message)

            self.camera_status_signal.emit(
                False,
                message
            )
            return

        # ==========================================
        # 6. GET CAPTURE STEP FROM JSON
        # ==========================================
        try:
            self.capture_step_mm = float(
                data.get("capture_step_mm", 20.0)
            )
        except (TypeError, ValueError):
            self.capture_step_mm = 20.0

        if self.capture_step_mm <= 0:
            self.capture_step_mm = 20.0

        print(
            f"📐 Prediction every "
            f"{self.capture_step_mm:.2f} mm"
        )

        # ==========================================
        # 7. INITIAL ENCODER POSITION
        # ==========================================
        self.last_capture_length = (
            float(self.last_length_value)
            if self.last_length_value is not None
            else None
        )

        print(
            "📏 Detection starting D0:",
            self.last_capture_length
        )

        # ==========================================
        # 8. MACHINE ON - START DETECTION
        # ==========================================
        print("✅ D512 = 1 - Machine ON")
        print(
            "✅ Detection Job ID:",
            self.current_detection_job
        )
        print("🚀 Detection Started")

        self.detection_running = True
        self.prediction_busy = False
        self.last_polygon_config_warning_job = ""

        # ==========================================
        # 9. START PREDICTION WORKER
        # ==========================================
        self._start_prediction_worker()

        # ==========================================
        # 10. START CAMERA
        # ==========================================
        self.startCamera()

        self.camera_status_signal.emit(
            True,
            "Detection started"
        )


    @pyqtSlot()
    def stopDetection(self):

        print("🛑 Detection Stopped")

        self.detection_running = False
        self.prediction_busy = False

        # Reset 20mm capture reference
        self.last_capture_length = None

        # Stop camera
        self.stopCamera()

        self.camera_status_signal.emit(
            False,
            "Detection stopped"
        )