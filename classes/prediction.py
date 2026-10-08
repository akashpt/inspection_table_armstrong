import os
import cv2
import uuid
import torch
import joblib
import json
import numpy as np
from PIL import Image
from torchvision import models, transforms
from ultralytics import YOLO
from path import (
    MODELS_DIR,
    DEFECT_MAPPED_DIR,
    DEFECT_RAW_DIR,
    CONFIG_FILE,
)

class VisionProcessor:
  
    def __init__(
        self,
        safety_factor: float = 3.0,
    ):
        # ===============================
        # DEVICE
        # ===============================
        self.DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

        # ===============================
        # OUTPUT FOLDERS
        # ===============================
        # self.DEFECT_MAPPED_DIR = str(DEFECT_MAPPED_DIR)
        # self.DEFECT_RAW_DIR = str(DEFECT_RAW_DIR)
        # self.NOT_MAPPING_FOLDER = DEFECT_RAW_DIR
        
        # os.makedirs(self.NOT_MAPPING_FOLDER, exist_ok=True)

        self.safety_factor = safety_factor
        self.pca = None
        self.mean = None
        self.inv = None
        self.threshold = None
        self.loaded_job_id = None
        # print(f"[VisionProcessor] YOLO model       : {self.yolo_model_path}")
        # print(f"[VisionProcessor] Threshold safety factor: {safety_factor}")

        # ===============================
        # LOAD EfficientNet-B2
        # ===============================
        self.model = models.efficientnet_b2(weights=models.EfficientNet_B2_Weights.IMAGENET1K_V1)
        self.model.classifier = torch.nn.Identity()
        self.model.to(self.DEVICE)
        self.model.eval()

        # ===============================
        # TRANSFORM
        # ===============================
        self.tf = transforms.Compose([
            transforms.Resize((640, 640)),
            transforms.ToTensor(),
            transforms.Normalize(
                [0.485, 0.456, 0.406],
                [0.229, 0.224, 0.225],
            ),
        ])

        # ===============================
        # LOAD YOLO
        # ===============================
        try:
            self.yolo_model_path = MODELS_DIR / "best.pt"
            self.yolo_model = YOLO(self.yolo_model_path)
        except Exception as e:
            print("Yolo Model Not Found",e)
            self.yolo_model_path = None
            self.yolo_model = None
        

        self.CLASS_NAMES = {
            0: "hole",
            1: "needle",
            2: "double_yarn",
            3:"oil"
        }
        self.CLASS_COLORS = {
            0: (0, 255, 255),   # cyan   – hole
            1: (0, 0, 255),     # red    – needle
            2: (0, 140, 255),   # orange – double_yarn
        }

        self.PIXEL_TO_MM = 0.01
        self.INFER_SIZE  = 1280

        # ===============================
        # FRAME SKIP
        # ===============================
        self.skip_frame_count = 0
        self.frames_seen      = 0


    def load_job_model(self, job_id):
        if self.loaded_job_id == job_id:
            return

        job_model_dir = MODELS_DIR / str(job_id)

        pca_model_path = job_model_dir / f"{job_id}_model.joblib"
        stats_path     = job_model_dir / f"{job_id}_stats.joblib"

        if not pca_model_path.exists():
            raise FileNotFoundError(f"PCA model not found: {pca_model_path}")
            
        
        if not stats_path.exists():
            raise FileNotFoundError(f"Stats file not found: {stats_path}")
            

        self.pca = joblib.load(pca_model_path)
        mean, inv, threshold_raw = joblib.load(stats_path)

        self.mean = mean
        self.inv = inv
        self.threshold = float(threshold_raw) * float(self.safety_factor)
        self.loaded_job_id = job_id

        print(f"✅ Loaded job model: {job_id}")
        print(f"✅ PCA: {pca_model_path}")
        print(f"✅ Stats: {stats_path}")
        print(
            f"✅ Trained model threshold: "
            f"{self.threshold:.4f}"
        )


    def map_the_defect(self,original,detected_defect_info):
        # annotated = original.copy()
        try:
            orig_h, orig_w = original.shape[:2]
            
            results = self.yolo_model.predict(
                original,
                conf=0.05,
                iou=0.25,
                imgsz=self.INFER_SIZE,
                device=0 if self.DEVICE == "cuda" else "cpu",
                augment=False,
                verbose=False,
            )[0]

            
            defect_id = 1

            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cls = int(box.cls[0])

                w_px = x2 - x1
                h_px = y2 - y1

                # Noise filter
                if w_px < 3 or h_px < 3:
                    continue

                # ── Orientation rules ──────────────────────────────────────
                if cls == 1:          # needle → stretch full height
                    y1, y2 = 0, orig_h
                    h_px   = orig_h

                elif cls == 2:        # double_yarn → stretch full width
                    x1, x2 = 0, orig_w
                    w_px   = orig_w

                width_mm  = round(w_px * self.PIXEL_TO_MM, 2)
                height_mm = round(h_px * self.PIXEL_TO_MM, 2)

                defect_type = self.CLASS_NAMES.get(cls, "defect")
                color       = self.CLASS_COLORS.get(cls, (0, 255, 0))

                # Draw bounding box
                cv2.rectangle(original, (x1, y1), (x2, y2), color, 2)

                # Label with mm measurements
                label         = f"{defect_type} {width_mm:.2f}x{height_mm:.2f} mm" 
                TOP_MARGIN    = 40
                BOTTOM_MARGIN = orig_h - 20
                above_y       = y1 - 15
                below_y       = y2 + 25

                if above_y > TOP_MARGIN:
                    text_y = above_y
                elif below_y < BOTTOM_MARGIN:
                    text_y = below_y
                else:
                    text_y = TOP_MARGIN

                cv2.putText(
                    original, label, (x1, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2,
                )

                detected_defect_info.append({
                    "id":        defect_id,
                    "type":      defect_type,
                    "width_mm":  width_mm,
                    "height_mm": height_mm,
                })
                defect_id += 1
            return original , detected_defect_info
        except Exception as e:
            print("Mapping Error",e)
            return original , None

    def get_threshold_from_json(self, job_id):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)

            selected_job = config.get("selected_job", {})

            selected_job_id = str(
                selected_job.get("Job_ID", "")
            ).strip()

            # Make sure threshold belongs to current job
            if selected_job_id != str(job_id).strip():
                print(
                    f"⚠️ JSON Job ID mismatch | "
                    f"Selected: {selected_job_id} | "
                    f"Prediction: {job_id}"
                )
                return None

            threshold = selected_job.get(
                "threshold_value"
            )

            if threshold in (None, ""):
                print("⚠️ threshold_value not found in settings.json")
                return None

            threshold = float(threshold)

            print(
                f"✅ JSON Threshold loaded: {threshold:.4f}"
            )

            return threshold

        except Exception as e:
            print(
                "❌ Threshold JSON read error:",
                e
            )
            return None
    # ------------------------------------------------------------------
    # MAIN PIPELINE
    # ------------------------------------------------------------------
    def process_image(
        self,
        frame,
        job_id,
        threshold_value=None,
    ):
        print("========== PROCESS IMAGE ==========")
        print("Job ID:", job_id)
        print("Frame is None:", frame is None)
        print(
            "Frame shape:",
            frame.shape if frame is not None else None,
        )
        print("Frames seen before:", self.frames_seen)
        print("Skip frame count:", self.skip_frame_count)

        if frame is None:
            print("⏭️ SKIP REASON: frame is None")
            return "skip", "0000", None, []

        if not isinstance(frame, np.ndarray):
            print("⏭️ SKIP REASON: frame is not NumPy array")
            return "skip", "0000", None, []

        if frame.size == 0:
            print("⏭️ SKIP REASON: frame is empty")
            return "skip", "0000", None, []

        try:
            self.load_job_model(job_id)
        except FileNotFoundError as e:
            print(f"❌ Job model file missing: {e}")
            return "model_not_found", "0000", None, []
        except Exception as e:
            print(f"❌ Job model load error: {e}")
            return "model_error", "0000", None, []

        self.frames_seen += 1

        if self.frames_seen <= self.skip_frame_count:
            print(
                f"⏭️ SKIP REASON: initial frame "
                f"{self.frames_seen}/{self.skip_frame_count}"
            )
            return "skip", "0000", None, []

        print("✅ Frame accepted for EfficientNet prediction")

        # ==========================================
        # GET THRESHOLD FROM settings.json
        # ==========================================
        if threshold_value is None:

            threshold_value = self.get_threshold_from_json(
                job_id
            )

            if threshold_value is None:
                print(
                    "⚠️ JSON threshold unavailable, "
                    "using trained model threshold"
                )

                threshold_value = (
                    float(self.threshold)
                    if self.threshold is not None
                    else 0.0
                )

    # Continue your EfficientNet code below...
        # ===============================
        # STAGE 1 – EfficientNet-B2 GATE
        # ===============================
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        x = self.tf(pil_img).unsqueeze(0).to(self.DEVICE)

        with torch.no_grad():
            feat = self.model(x).cpu().numpy().flatten()

        z = self.pca.transform([feat])[0]
        score = float((z - self.mean) @ self.inv @ (z - self.mean))

        # ===============================
        # PRINT PREDICTION INFORMATION
        # ===============================
        print("\n" + "=" * 50)
        print("IMAGE PREDICTION")
        print("=" * 50)
        print(f"Job ID       : {job_id}")
        print(f"Image Score  : {score:.4f}")
        print(f"Threshold    : {threshold_value:.4f}")

        if score <= threshold_value:
            print("Prediction   : GOOD")
            print("Result       : PASS")
        else:
            print("Prediction   : BAD / DEFECT")
            print("Result       : FAIL")

        print("=" * 50 + "\n")


        # ── GOOD gate ──────────────────────────────────────────────────
        if score <= threshold_value:
            return "good", "0000", None, [], score, threshold_value

        # ── EfficientNet says DEFECT ──────────────────────────────────
        original = frame.copy()

        # # Save raw BMP before annotation (unmapped copy)
        # raw_name = f"defect_{uuid.uuid4().hex[:8]}.bmp"
        # raw_path = os.path.join(DEFECT_RAW_DIR, raw_name)
        # cv2.imwrite(raw_path, original)

        # ===============================
        # STAGE 2 – YOLO ANNOTATION ONLY
        # ===============================
        annotated      = original.copy()
        detected_defect_info = []
        mapping = False
        if self.yolo_model:
            annotated , detected_defect_info = self.map_the_defect(annotated,detected_defect_info)
            mapping = True

        # ===============================
        # STATUS BANNER
        # ===============================
        if len(detected_defect_info) == 0 and mapping:
            banner = "Status: NG (unmapped)"
        elif len(detected_defect_info) > 0 and mapping:
            banner = "Status: NG (mapped)"
        else:
            banner = "Status: NG"

        cv2.putText(
            annotated, banner, (20, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3,
        )

        # ===============================
        # SAVE ANNOTATED IMAGE
        # ===============================
        mapped_name = f"defect_{uuid.uuid4().hex[:8]}.jpg"
        mapped_path = os.path.join(DEFECT_MAPPED_DIR, mapped_name)
        cv2.imwrite(mapped_path, annotated)

        return (
            "defect",
            "1000",
            mapped_path,
            detected_defect_info,
            score,
            threshold_value,
        )
        



if __name__ == "__main__":
    vp = VisionProcessor()

    img = cv2.imread(r"D:\Texa\knitting\knitting_b2_prediction\bad_img_oil1.bmp")

    if img is None:
        raise FileNotFoundError("Image not found or cannot read image")

    status, code, image_path, defect_info = vp.process_image(img,"check")

    print("Status:", status)
    print("Code:", code)
    print("Saved image:", image_path)
    print("Defects:", defect_info)