import os
import sys
import time
import cv2
import numpy as np
import importlib.util
import uuid
import json
from path import *
from path import MODELS_DIR

#This function reads JSON File:

import json

def load_confidence_from_camera_settings():
    cfg_path = os.path.join(os.path.abspath("."), CONFIG_FILE)

    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"camera_settings.json not found: {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    job = data.get("selected_job", {})

    def to_float(val):
        if val is None:
            return None
        if isinstance(val, str) and val.strip() == "":
            return None
        try:
            return float(val)
        except Exception:
            return None

    return {
        "block_conf_threshold": to_float(job.get("block_confidence")),
        "vertical_conf_threshold": to_float(job.get("vertical_confidence")),
        "horizontal_conf_threshold": to_float(job.get("horizontal_confidence")),
        "new_vertical": to_float(job.get("new_vertical_confidence")),
        "new_horizontal": to_float(job.get("new_horizontal_confidence")),
    }


CONF_THRESH = load_confidence_from_camera_settings()

print(CONF_THRESH)




class VisionProcessor:
    def __init__(self):
        self.BLOCK_SIZE = 50
        self.PADDING = 3

        # self.EXPECTED_ROWS = 40
        # self.EXPECTED_COLS = 117
        self.load_grid_from_json()

        # self.EXPECTED_WIDTH  = 117 * 50   # 5850
        # self.EXPECTED_HEIGHT = 40 * 50    # 2000
        self.post_defect_skip = 1         # number of frames to skip after defect
        self.post_defect_counter = 0       # runtime counter

        # self.BLOCK_SIZE = 50
        # self.PADDING = 3
        # self.EXPECTED_WIDTH =  2448 * 4 
        # self.EXPECTED_HEIGHT = 2048
        # self.EXPECTED_ROWS = self.EXPECTED_HEIGHT // self.BLOCK_SIZE
        # self.EXPECTED_COLS = self.EXPECTED_WIDTH // self.BLOCK_SIZE

        self.ANNOTATED_FOLDER = BAD_IMG_SAVE
        os.makedirs(self.ANNOTATED_FOLDER, exist_ok=True)

        self.skip_frame_count = 1
        self.frames_seen = 0

        self.load_thresholds()
    
    def load_grid_from_json(self):
        cfg_path = os.path.join(os.path.abspath("."),CONFIG_FILE)

        with open(cfg_path, "r") as f:
            data = json.load(f)

        job = data.get("selected_job", {})

        self.EXPECTED_ROWS = int(job.get("polygon_rows", 40))
        self.EXPECTED_COLS = int(job.get("polygon_columns", 117))
        self.BLOCK_SIZE = int(data.get("block_size", 50))

        self.EXPECTED_WIDTH  = self.EXPECTED_COLS * self.BLOCK_SIZE
        self.EXPECTED_HEIGHT = self.EXPECTED_ROWS * self.BLOCK_SIZE

def load_thresholds(self):
    def find_file_in_models(filename):
        # check direct: models/file.py
        direct_path = MODELS_DIR / filename
        if direct_path.exists():
            return str(direct_path)

        # check inside subfolders: models/job1/file.py
        for root, dirs, files in os.walk(MODELS_DIR):
            if filename in files:
                return os.path.join(root, filename)

        return None

    def load_optional(filename, attr, default):
        try:
            path = find_file_in_models(filename)

            if path is None:
                print(f"⚠️ Trained model/threshold missing: {filename}")
                return default

            spec = importlib.util.spec_from_file_location("mod", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            return getattr(mod, attr, default)

        except Exception as e:
            print(f"⚠️ Threshold load warning: {filename} -> {e}")
            return default

    self.block_thresholds = load_optional(
        "new_training_overall.py",
        "thresholds",
        None
    )

    self.horizontal_thresholds = load_optional(
        "horizontal_new_training.py",
        "horizontal_thresholds",
        {"Sum_G": None}
    ).get("Sum_G")

    self.vertical_thresholds = load_optional(
        "vertical_new_training.py",
        "vertical_thresholds",
        {"Sum_G": None}
    ).get("Sum_G")

    self.selected_vertical_dict = load_optional(
        "vertical_thresholds.py",
        "vertical_thresholds_sum_g",
        {}
    )

    self.selected_horizontal_dict = load_optional(
        "horizontal_thresholds.py",
        "horizontal_thresholds_sum_g",
        {}
    )
    # def load_thresholds(self):
    #     def load_thresholds(file, attr):
    #         if getattr(sys, 'frozen', False):
    #             base_path = sys._MEIPASS
    #         else:
    #             base_path = os.path.abspath(".")
    #         path = os.path.join(base_path, file)
    #         spec = importlib.util.spec_from_file_location("mod", path)
    #         mod = importlib.util.module_from_spec(spec)
    #         spec.loader.exec_module(mod)
    #         return getattr(mod, attr)

    #     self.block_thresholds = load_thresholds("training/new_training_overall.py", "thresholds")
    #     self.horizontal_thresholds = load_thresholds("training/horizontal_new_training.py", "horizontal_thresholds")['Sum_G']
    #     self.vertical_thresholds = load_thresholds("training/vertical_new_training.py", "vertical_thresholds")['Sum_G']
    #     self.selected_vertical_dict = load_thresholds("training/vertical_thresholds.py", "vertical_thresholds_sum_g")
    #     self.selected_horizontal_dict = load_thresholds("training/horizontal_thresholds.py", "horizontal_thresholds_sum_g")

    def calculate_confidence(self, value, min_val, max_val):
        range_val = max_val - min_val
        if range_val == 0:
            return 1.0
        center = (min_val + max_val) / 2
        deviation = abs(value - center)
        percentage = (deviation / range_val) * 100
        return round(percentage / 10, 1)

    def are_neighbors(self, p1, p2):
        bs = self.BLOCK_SIZE
        return (abs(p1[0] - p2[0]) == bs and p1[1] == p2[1]) or (abs(p1[1] - p2[1]) == bs and p1[0] == p2[0])

    def group_neighbors(self, points):
        groups = []
        visited = set()

        for pt in points:
            if pt in visited:
                continue

            stack = [pt]
            group = []

            while stack:
                current = stack.pop()

                if current in visited:
                    continue

                visited.add(current)
                group.append(current)

                for other in points:
                    if other not in visited and self.are_neighbors(current, other):
                        stack.append(other)

            groups.append(group)

        return groups

    def merge_rectangles(self, rects, axis):
        merged = []
        rects = sorted(rects, key=lambda r: r[axis])
        group = []
        last_end = None
        for r in rects:
            if not group:
                group.append(r)
                last_end = r[axis + 2]
            elif r[axis] <= last_end:
                group.append(r)
                last_end = max(last_end, r[axis + 2])
            else:
                merged.append(group)
                group = [r]
                last_end = r[axis + 2]
        if group:
            merged.append(group)
        return merged

    def get_next_serial_filename(self, prefix="frame", ext="jpg"):
        serial = uuid.uuid4().hex[:8]
        filename = f"{prefix}_{serial}.{ext}"
        return filename, os.path.join(self.ANNOTATED_FOLDER, filename)

    def calculate_stat(self, block, metric):
        if metric == "vertical_thresholds_sum_g" or metric == "horizontal_thresholds_sum_g":
            return int(np.sum(block[:, :, 1]))
        return 0
    
    def safe_imwrite(self, path, img):
        if img is None or img.size == 0:
            print("❌ Cannot save empty image:", path)
            return False
        return cv2.imwrite(path, img)

    
    def apply_json_roi(self, frame):
        if frame is None or frame.size == 0:
            print("❌ Empty input frame before ROI")
            return None

        cfg_path = os.path.join(os.path.abspath("."), CONFIG_FILE)

        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        selected_job = data.get("selected_job", {})
        selected_id = selected_job.get("Job_ID") or selected_job.get("job_id") or ""
        roi = selected_job.get("polygon_roi", {})

        try:
            polygon_file = TRAINING_IMAGES_DIR / str(selected_id) / "polygon_settings.json"
            with open(polygon_file, "r", encoding="utf-8") as f:
                polygon_data = json.load(f)
            polygon_jobs = polygon_data.get("job_polygons", {})
            polygon_config = polygon_jobs.get(str(selected_id), {})
            if isinstance(polygon_config, dict):
                roi = polygon_config.get("polygon_roi", roi)
        except Exception as e:
            print("Polygon settings read failed:", e)

        h, w = frame.shape[:2]

        rx1 = float(roi.get("x1", w))
        rx2 = float(roi.get("x2", 0))
        ry1 = float(roi.get("y1", h))
        ry2 = float(roi.get("y2", 0))

        # support both ratio ROI and pixel ROI
        if 0 <= rx1 <= 1 and 0 <= rx2 <= 1 and 0 <= ry1 <= 1 and 0 <= ry2 <= 1:
            x1 = int(rx1 * w)
            x2 = int(rx2 * w)
            y1 = int(ry1 * h)
            y2 = int(ry2 * h)
        else:
            x1 = int(rx1)
            x2 = int(rx2)
            y1 = int(ry1)
            y2 = int(ry2)
        # Fix reversed ROI
        if x1 > x2:
            x1, x2 = x2, x1

        if y1 > y2:
            y1, y2 = y2, y1

        # Limit inside image
        x1 = max(0, min(x1, w - 1))
        x2 = max(1, min(x2, w))
        y1 = max(0, min(y1, h - 1))
        y2 = max(1, min(y2, h))

        if x2 <= x1 or y2 <= y1:
            print(f"❌ Invalid ROI after fix: x1={x1}, x2={x2}, y1={y1}, y2={y2}, frame={w}x{h}")
            return None

        roi_frame = frame[y1:y2, x1:x2]

        if roi_frame is None or roi_frame.size == 0:
            print("❌ ROI result empty")
            return None

        print("ROI OK:", roi_frame.shape)
        return roi_frame
        
    def process_image(
        self,
        frame,
        input_path,
        target_rotation,
        machine_number,
        save_good=False,
    ):
        # frame = self.apply_json_roi(frame)
        if frame is None or frame.size == 0:
            print("❌ Skipping prediction: empty frame/ROI")
            return "skip", "0000", None
        # print(frame)
        # Skip frames after a defect
        if self.post_defect_counter > 0:
            print(f"⏭️ Skipping post-defect frame ({self.post_defect_counter} left)")
            self.post_defect_counter -= 1
            return "skip", "0000", None

        if CONF_THRESH["block_conf_threshold"] is not None:
            block_conf_threshold = CONF_THRESH["block_conf_threshold"]

        if CONF_THRESH["vertical_conf_threshold"] is not None:
            vertical_conf_threshold = CONF_THRESH["vertical_conf_threshold"]

        if CONF_THRESH["horizontal_conf_threshold"] is not None:
            horizontal_conf_threshold = CONF_THRESH["horizontal_conf_threshold"]

        if CONF_THRESH["new_vertical"] is not None:
            new_vertical = CONF_THRESH["new_vertical"]

        if CONF_THRESH["new_horizontal"] is not None:
            new_horizontal = CONF_THRESH["new_horizontal"]

        # frame = cv2.imread(r"assets/defect_6a00d4b0.jpg")
        self.frames_seen += 1
        if self.frames_seen <= self.skip_frame_count:
            print(f"⏭️ Skipping frame {self.frames_seen} (green frame)")
            return "skip", "0000", None
        
        os.makedirs("process_frame", exist_ok=True)

        save_path = os.path.join(
            "process_frame",
            f"process_{uuid.uuid4().hex[:8]}.bmp"
        )
        start_time = time.perf_counter()

        self.safe_imwrite(save_path, frame)

        end_time = time.perf_counter()

        save_ms = (end_time - start_time) * 1000
        print(f"⏱ RAW Save Time: {save_ms:.2f} ms")

        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_clahe = clahe.apply(l)
        lab_clahe = cv2.merge((l_clahe, a, b))
        clahe_bgr = cv2.cvtColor(lab_clahe, cv2.COLOR_LAB2BGR)
        # clahe_bgr = clahe_bgr[:self.EXPECTED_ROWS * self.BLOCK_SIZE, :self.EXPECTED_COLS * self.BLOCK_SIZE]
        clahe_bgr = cv2.resize( clahe_bgr,(self.EXPECTED_COLS * self.BLOCK_SIZE,self.EXPECTED_ROWS * self.BLOCK_SIZE))

        # annotated_img = frame.copy()
        annotated_img=clahe_bgr.copy()
        # self.safe_imwrite("debug_roi.jpg", frame)
        # self.safe_imwrite("debug_resized.jpg", clahe_bgr)
        block_id = 1
        block_points = []
        block_confs = {}
        grid_sum_g = []
        defect_flags = [0, 0, 0]
        defect_sizes = {
            "holes_oil": 0.0,
            "needle_line": 0.0,
            "double_yarn": 0.0,
        }

        for y in range(0, self.EXPECTED_ROWS * self.BLOCK_SIZE, self.BLOCK_SIZE):
            row_g = []
            for x in range(0, self.EXPECTED_COLS * self.BLOCK_SIZE, self.BLOCK_SIZE):
                block = clahe_bgr[y:y + self.BLOCK_SIZE, x:x + self.BLOCK_SIZE]
                sum_g = int(np.sum(block[:, :, 1]))
                row_g.append(sum_g)

                if block_id in self.block_thresholds:
                    min_g, max_g = self.block_thresholds[block_id]['Sum_G']
                    if not (min_g <= sum_g <= max_g):
                        conf = self.calculate_confidence(sum_g, min_g, max_g)
                        if conf > block_conf_threshold:
                            block_points.append((x, y))
                            block_confs[(x, y)] = conf
                block_id += 1
            grid_sum_g.append(row_g)

        groups = self.group_neighbors(block_points)
        for group in groups:
            if len(group) >= 2 or (len(group) == 1 and block_confs[group[0]] > 8):
                pts, confs = [], []
                for (x, y) in group:
                    pts.extend([
                        [x - self.PADDING, y - self.PADDING],
                        [x + self.BLOCK_SIZE + self.PADDING, y - self.PADDING],
                        [x + self.BLOCK_SIZE + self.PADDING, y + self.BLOCK_SIZE + self.PADDING],
                        [x - self.PADDING, y + self.BLOCK_SIZE + self.PADDING]
                    ])
                    confs.append(block_confs[(x, y)])
                poly = cv2.convexHull(np.array(pts))
                avg_conf = round(sum(confs) / len(confs), 1)
                perimeter = cv2.arcLength(poly, True) * 0.01
                defect_sizes["holes_oil"] += perimeter
                cv2.polylines(annotated_img, [poly], isClosed=True, color=(0, 0, 255), thickness=4)
                x, y = poly[poly[:, :, 1].argmin()][0]
                cv2.putText(annotated_img, f"holes/oil{avg_conf:.1f}f | size: {perimeter:.1f} mm", (x, y + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 3)
                defect_flags[0] = 1

        vertical_rects, vertical_conf = [], []
        for col in range(self.EXPECTED_COLS):
            total = sum(grid_sum_g[r][col] for r in range(self.EXPECTED_ROWS))
            if col + 1 in self.vertical_thresholds:
                min_v, max_v = self.vertical_thresholds[col + 1]
                if not (min_v <= total <= max_v):
                    conf = self.calculate_confidence(total, min_v, max_v)
                    if conf > vertical_conf_threshold:
                        x1 = col * self.BLOCK_SIZE
                        vertical_rects.append((x1, 0, x1 + self.BLOCK_SIZE, self.BLOCK_SIZE * self.EXPECTED_ROWS))
                        vertical_conf.append(conf)
                        defect_flags[1] = 1

        for group in self.merge_rectangles(vertical_rects, axis=0):
            x1 = min(r[0] for r in group)
            x2 = max(r[2] for r in group)
            y1, y2 = 0, self.BLOCK_SIZE * self.EXPECTED_ROWS
            avg_conf = round(sum(vertical_conf[:len(group)]) / len(group), 1)
            height_mm = (y2 - y1) * 0.01
            defect_sizes["needle_line"] += height_mm
            cv2.rectangle(annotated_img, (x1, y1), (x2, y2), (0, 255, 0), 4)
            cv2.putText(annotated_img, f"Needleline{avg_conf:.1f}f | H: {height_mm:.1f} mm", (x1 + 2, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (246, 15, 153), 3)

        horizontal_rects, horizontal_conf = [], []
        for row in range(self.EXPECTED_ROWS):
            total = sum(grid_sum_g[row])
            if row + 1 in self.horizontal_thresholds:
                min_h, max_h = self.horizontal_thresholds[row + 1]
                if not (min_h <= total <= max_h):
                    conf = self.calculate_confidence(total, min_h, max_h)
                    if conf > horizontal_conf_threshold:
                        y1 = row * self.BLOCK_SIZE
                        horizontal_rects.append((0, y1, self.BLOCK_SIZE * self.EXPECTED_COLS, y1 + self.BLOCK_SIZE))
                        horizontal_conf.append(conf)
                        defect_flags[2] = 1

        defected_rows = set([y // self.BLOCK_SIZE for (x, y) in block_points])
        filtered_horizontal_rects, filtered_horizontal_conf = [], []
        for idx, rect in enumerate(horizontal_rects):
            y_row = rect[1] // self.BLOCK_SIZE
            if y_row not in defected_rows:
                filtered_horizontal_rects.append(rect)
                filtered_horizontal_conf.append(horizontal_conf[idx])
        horizontal_rects = filtered_horizontal_rects
        horizontal_conf = filtered_horizontal_conf

        for group in self.merge_rectangles(horizontal_rects, axis=1):
            y1 = min(r[1] for r in group)
            y2 = max(r[3] for r in group)
            x1, x2 = 0, self.BLOCK_SIZE * self.EXPECTED_COLS
            avg_conf = round(sum(horizontal_conf[:len(group)]) / len(group), 1)
            width_mm = (x2 - x1) * 0.01
            defect_sizes["double_yarn"] += width_mm
            cv2.rectangle(annotated_img, (x1, y1), (x2, y2), (255, 0, 0), 4)
            cv2.putText(annotated_img, f"Double_yarn{avg_conf:.1f}f | W: {width_mm:.1f} mm", (5, y1 + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (5, 243, 18), 3)


        if defect_flags[1] == 0:
            flagged_cols = set([rect[0] // self.BLOCK_SIZE for rect in vertical_rects])
            vertical_rects = []
            vertical_confs = []
            block_id = 0
            for col in range(self.EXPECTED_COLS):
                if col in flagged_cols:
                    block_id += 4
                    continue
                x_start = col * self.BLOCK_SIZE
                for split in range(4):
                    y_start = split * 500
                    block = clahe_bgr[y_start:y_start+500, x_start:x_start+self.BLOCK_SIZE]
                    value = self.calculate_stat(block, "vertical_thresholds_sum_g")
                    if block_id in self.selected_vertical_dict:
                        min_val, max_val = self.selected_vertical_dict[block_id]
                        if not (min_val <= value <= max_val):
                            conf = self.calculate_confidence(value, min_val, max_val)
                            if conf >= new_vertical:
                                vertical_rects.append((x_start, y_start, x_start + self.BLOCK_SIZE, y_start + 500))
                                vertical_confs.append(conf)
                    block_id += 1

            for group in self.merge_rectangles(vertical_rects, axis=0):
                x1 = min(r[0] for r in group)
                x2 = max(r[2] for r in group)
                y1 = min(r[1] for r in group)
                y2 = max(r[3] for r in group)
                avg_conf = round(sum(vertical_confs[:len(group)]) / len(group), 1)
                height_mm = (y2 - y1) * 0.01
                defect_sizes["needle_line"] += height_mm
                cv2.rectangle(annotated_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(annotated_img, f"Needleline{avg_conf:.1f}f | H: {height_mm:.1f} mm", (x1 + 2, y1 + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (246, 15, 153), 2)
                defect_flags[1] = 1

        # === Enhanced Horizontal Split Check ===
        if defect_flags[2] == 0:
            flagged_rows = set([rect[1] // self.BLOCK_SIZE for rect in horizontal_rects])
            horizontal_rects = []
            horizontal_confs = []
            block_id = 0
            for row in range(self.EXPECTED_ROWS):
                if row in flagged_rows:
                    block_id += 4
                    continue
                y_start = row * self.BLOCK_SIZE
                for split in range(4):
                    x_start = split * 600
                    block = clahe_bgr[y_start:y_start+self.BLOCK_SIZE, x_start:x_start+600]
                    value = self.calculate_stat(block, "horizontal_thresholds_sum_g")
                    if block_id in self.selected_horizontal_dict:
                        min_val, max_val = self.selected_horizontal_dict[block_id]
                        if not (min_val <= value <= max_val):
                            conf = self.calculate_confidence(value, min_val, max_val)
                            if conf >= new_horizontal:
                                horizontal_rects.append((x_start, y_start, x_start + 600, y_start + self.BLOCK_SIZE))
                                horizontal_confs.append(conf)
                    block_id += 1

            for group in self.merge_rectangles(horizontal_rects, axis=1):
                x1 = min(r[0] for r in group)
                x2 = max(r[2] for r in group)
                y1 = min(r[1] for r in group)
                y2 = max(r[3] for r in group)
                avg_conf = round(sum(horizontal_confs[:len(group)]) / len(group), 1)
                width_mm = (x2 - x1) * 0.01
                defect_sizes["double_yarn"] += width_mm
                cv2.rectangle(annotated_img, (x1, y1), (x2, y2), (255, 0, 0), 2)
                cv2.putText(annotated_img, f"Double_yarn{avg_conf:.1f}f | W: {width_mm:.1f} mm", (x1 + 5, y1 + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (5, 243, 18), 2)
                defect_flags[2] = 1
        binary_code = f"{defect_flags[0]}{defect_flags[1]}{defect_flags[2]}0"

        self.defect_type = self.get_defect_type_from_sizes(defect_sizes)
        # save_all_folder = "all_predictions"
        # os.makedirs(save_all_folder, exist_ok=True)

        # filename = f"frame_{uuid.uuid4().hex[:8]}.jpg"
        # save_path = os.path.join(save_all_folder, filename)

        # self.safe_imwrite(save_path, annotated_img)

        if any(defect_flags):
            self.post_defect_counter = self.post_defect_skip

            save_path = os.path.join(
                self.ANNOTATED_FOLDER,
                f"defect_{uuid.uuid4().hex[:8]}.jpg"
            )

            ok = self.safe_imwrite(save_path, annotated_img)

            if not ok:
                print("❌ Defect image save failed:", save_path)
                return "defect", binary_code, None

            print("Defect image saved:", save_path)
            return "defect", binary_code, save_path
        else:
            training_need_folder = "training_need"
            # os.makedirs(training_need_folder, exist_ok=True)

            for block_id_y in range(self.EXPECTED_ROWS):
                for block_id_x in range(self.EXPECTED_COLS):
                    block_id = block_id_y * self.EXPECTED_COLS + block_id_x + 1
                    if block_id not in self.block_thresholds:
                        continue

                    x = block_id_x * self.BLOCK_SIZE
                    y = block_id_y * self.BLOCK_SIZE
                    block = clahe_bgr[y:y + self.BLOCK_SIZE, x:x + self.BLOCK_SIZE]
                    sum_g = int(np.sum(block[:, :, 1]))
                    min_g, max_g = self.block_thresholds[block_id]['Sum_G']

                    if not (min_g <= sum_g <= max_g):
                        filename = f"block_{block_id}_g{sum_g}.bmp"
                        save_path = os.path.join(training_need_folder, filename)
                        self.safe_imwrite(save_path, block)

            return "good", "0000", None

    def get_defect_type_from_flags(self, defect_flags):
        types = []
        if defect_flags[0]:
            types.append("holes_oil")
        if defect_flags[1]:
            types.append("needle_line")
        if defect_flags[2]:
            types.append("double_yarn")

        if not types:
            return None

        # If multiple defects, join them
        return ",".join(types)
    
    def get_defect_type_from_sizes(self, defect_sizes):

        parts = []

        for defect_name, size in defect_sizes.items():

            if size > 0:
                parts.append(f"{defect_name} {size:.1f} mm")

        if not parts:
            return None

        return ", ".join(parts)
