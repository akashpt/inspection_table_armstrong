import os
import cv2
import csv
import json
import math
import time
import numpy as np
import pandas as pd
import polars as pl
from pathlib import Path
from path import *


class TrainingProcess:

    def __init__(self, training_job_id):
        if not training_job_id:
            raise ValueError("Training Job ID is required")

        # Job ID received from the training UI
        self.training_job_id = str(training_job_id).strip()

        # Individual training job folder
        self.job_dir = Path(TRAINING_IMAGES_DIR) / self.training_job_id

        if not self.job_dir.exists():
            raise FileNotFoundError(
                f"Training job folder not found:\n{self.job_dir}"
            )

        # Polygon information stored inside this job folder
        self.polygon_json_file = self.job_dir / "polygon_settings.json"

        if not self.polygon_json_file.exists():
            raise FileNotFoundError(
                f"Polygon size JSON not found:\n{self.polygon_json_file}"
            )

        with open(self.polygon_json_file, "r", encoding="utf-8") as f:
            polygon_data = json.load(f)

        print("Training Job ID :", self.training_job_id)
        print("Training Folder :", self.job_dir)
        print("Polygon JSON    :", self.polygon_json_file)

        # Supports polygon values directly in polygon_size.json
        image_width = polygon_data.get("polygon_image_width")
        image_height = polygon_data.get("polygon_image_height")

        # Supports JSON wrapped inside job_polygons
        if image_width is None or image_height is None:
            job_polygons = polygon_data.get("job_polygons", {})

            if isinstance(job_polygons, dict):
                job_data = job_polygons.get(self.training_job_id, {})

                image_width = job_data.get("polygon_image_width")
                image_height = job_data.get("polygon_image_height")

        # Supports JSON wrapped directly inside the Job ID
        if image_width is None or image_height is None:
            job_data = polygon_data.get(self.training_job_id, {})

            if isinstance(job_data, dict):
                image_width = job_data.get("polygon_image_width")
                image_height = job_data.get("polygon_image_height")

        if image_width is None or image_height is None:
            raise ValueError(
                "polygon_image_width or polygon_image_height missing in:\n"
                f"{self.polygon_json_file}"
            )

        self.image_width = int(image_width)
        self.image_height = int(image_height)

        if self.image_width <= 0 or self.image_height <= 0:
            raise ValueError(
                f"Invalid polygon image size: "
                f"{self.image_width} x {self.image_height}"
            )

        # Grid calculation based on image dimensions
        self.block_width = 40
        self.block_height = 40

        self.num_cols = max(
            1,
            self.image_width // self.block_width
        )

        self.num_rows = max(
            1,
            self.image_height // self.block_height
        )

        print("Image Width :", self.image_width)
        print("Image Height:", self.image_height)
        print("Grid Rows   :", self.num_rows)
        print("Grid Columns:", self.num_cols)

        # Training images folder
        self.input_dir = Path(TRAINING_IMAGES_DIR) / self.training_job_id

        if not self.input_dir.exists():
            raise FileNotFoundError(
                f"Training image folder not found:\n{self.input_dir}"
            )

        # Model output folder
        self.model_dir = Path(MODELS_DIR) / self.training_job_id

        # Create MODELS_DIR/job_id automatically when missing
        self.model_dir.mkdir(parents=True, exist_ok=True)

        # Output CSV path
        self.training_csv = self.model_dir / "new_training.csv"

        print("Training images folder:", self.input_dir)
        print("Model output folder   :", self.model_dir)        
    def run(self, progress_callback=None):

        if progress_callback:
            progress_callback(10, "Generating Training CSV...")
        self.generate_training_csv()

        if progress_callback:
            progress_callback(50, "Generating Thresholds...")
        self.generate_thresholds()

        if progress_callback:
            progress_callback(80, "Generating H & V Thresholds...")
        self.generate_new_thresholds()

        if progress_callback:
            progress_callback(100, "Completed")

        return str(self.model_dir)

    def get_image_files(self):
        return [
            f for f in sorted(os.listdir(self.input_dir))
            if f.lower().endswith(
                (".bmp", ".dib", ".jpg", ".jpeg", ".png", ".tif", ".tiff")
            )
        ]

    def apply_clahe(self, image):
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_clahe = clahe.apply(l)

        lab_clahe = cv2.merge((l_clahe, a, b))
        return cv2.cvtColor(lab_clahe, cv2.COLOR_LAB2BGR)

    def generate_training_csv(self):
        image_files = self.get_image_files()

        if not image_files:
            raise FileNotFoundError(f"No images found in:\n{self.input_dir}")

        processed_images = set()

        if self.training_csv.exists():
            with open(self.training_csv, mode="r", newline="") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    processed_images.add(row["Image_Name"])
            write_header = False
        else:
            write_header = True

        with open(self.training_csv, mode="a", newline="") as file:
            writer = csv.writer(file)

            if write_header:
                writer.writerow(["Image_Name", "Block_ID", "Sum_R", "Sum_G", "Sum_B"])

            for filename in image_files:
                if filename in processed_images:
                    print(f"⏩ Skipping already processed: {filename}")
                    continue

                img_path = self.input_dir / filename
                image = cv2.imread(str(img_path))

                if image is None:
                    print(f"⚠️ Could not load {filename}")
                    continue

                clahe_bgr = self.apply_clahe(image)

                height, width, _ = clahe_bgr.shape
                block_height = height // self.num_rows
                block_width = width // self.num_cols

                block_id = 1

                for row in range(self.num_rows):
                    for col in range(self.num_cols):
                        y_start = row * block_height
                        x_start = col * block_width

                        block = clahe_bgr[
                            y_start:y_start + block_height,
                            x_start:x_start + block_width
                        ]

                        sum_r = int(np.sum(block[:, :, 2]))
                        sum_g = int(np.sum(block[:, :, 1]))
                        sum_b = int(np.sum(block[:, :, 0]))

                        writer.writerow([
                            filename,
                            block_id,
                            sum_r,
                            sum_g,
                            sum_b
                        ])

                        block_id += 1

                print(f"✅ CSV processed: {filename}")

        print(f"✅ Training CSV saved: {self.training_csv}")
        return str(self.training_csv)

    def generate_thresholds(self):
        if not self.training_csv.exists():
            raise FileNotFoundError(f"new_training.csv not found:\n{self.training_csv}")

        blockwise_output = self.model_dir / "new_training_overall.py"
        vertical_output = self.model_dir / "vertical_new_training.py"
        horizontal_output = self.model_dir / "horizontal_new_training.py"

        start_all = time.time()

        df = pl.read_csv(
            self.training_csv,
            columns=["Image_Name", "Block_ID", "Sum_R", "Sum_G", "Sum_B"]
        )

        if df.is_empty():
            raise ValueError(f"CSV is empty:\n{self.training_csv}")

        df = df.sort(["Image_Name", "Block_ID"])

        block_df = df.select(["Block_ID", "Sum_R", "Sum_G", "Sum_B"])
        block_df = block_df.sort("Block_ID")

        batch_size = 100
        total_rows = block_df.shape[0]
        total_epochs = math.ceil(total_rows / batch_size)

        thresholds = {}

        for epoch in range(total_epochs):
            start_idx = epoch * batch_size
            end_idx = min(start_idx + batch_size, total_rows)
            batch = block_df[start_idx:end_idx]

            grouped = batch.group_by("Block_ID").agg([
                pl.col("Sum_R").min().alias("Sum_R_min"),
                pl.col("Sum_R").max().alias("Sum_R_max"),
                pl.col("Sum_G").min().alias("Sum_G_min"),
                pl.col("Sum_G").max().alias("Sum_G_max"),
                pl.col("Sum_B").min().alias("Sum_B_min"),
                pl.col("Sum_B").max().alias("Sum_B_max"),
            ])

            for row in grouped.iter_rows():
                block_id, r_min, r_max, g_min, g_max, b_min, b_max = row
                block_id = int(block_id)

                if block_id not in thresholds:
                    thresholds[block_id] = {
                        "Sum_R": [r_min, r_max],
                        "Sum_G": [g_min, g_max],
                        "Sum_B": [b_min, b_max],
                    }
                else:
                    thresholds[block_id]["Sum_R"][0] = min(thresholds[block_id]["Sum_R"][0], r_min)
                    thresholds[block_id]["Sum_R"][1] = max(thresholds[block_id]["Sum_R"][1], r_max)
                    thresholds[block_id]["Sum_G"][0] = min(thresholds[block_id]["Sum_G"][0], g_min)
                    thresholds[block_id]["Sum_G"][1] = max(thresholds[block_id]["Sum_G"][1], g_max)
                    thresholds[block_id]["Sum_B"][0] = min(thresholds[block_id]["Sum_B"][0], b_min)
                    thresholds[block_id]["Sum_B"][1] = max(thresholds[block_id]["Sum_B"][1], b_max)

            print(f"✅ Epoch {epoch + 1}/{total_epochs} done")

        with open(blockwise_output, "w") as f:
            f.write("thresholds = {\n")
            for block_id in sorted(thresholds):
                entry = thresholds[block_id]
                f.write(f"    {block_id}: {{")
                f.write(f"'Sum_R': ({int(entry['Sum_R'][0])}, {int(entry['Sum_R'][1])}), ")
                f.write(f"'Sum_G': ({int(entry['Sum_G'][0])}, {int(entry['Sum_G'][1])}), ")
                f.write(f"'Sum_B': ({int(entry['Sum_B'][0])}, {int(entry['Sum_B'][1])})")
                f.write("},\n")
            f.write("}\n")

        print(f"✅ Block-wise thresholds saved: {blockwise_output}")

        all_images = df["Image_Name"].unique().to_list()

        vertical_sums = {
            col: {"Sum_R": [], "Sum_G": [], "Sum_B": []}
            for col in range(1, self.num_cols + 1)
        }

        horizontal_sums = {
            row: {"Sum_R": [], "Sum_G": [], "Sum_B": []}
            for row in range(1, self.num_rows + 1)
        }

        for img_name in all_images:
            img_df = df.filter(df["Image_Name"] == img_name)

            sum_r_list = img_df["Sum_R"].to_list()
            sum_g_list = img_df["Sum_G"].to_list()
            sum_b_list = img_df["Sum_B"].to_list()

            grid_r, grid_g, grid_b = [], [], []

            for i in range(0, len(sum_r_list), self.num_cols):
                grid_r.append(sum_r_list[i:i + self.num_cols])
                grid_g.append(sum_g_list[i:i + self.num_cols])
                grid_b.append(sum_b_list[i:i + self.num_cols])

            actual_rows = len(grid_r)
            actual_cols = min(len(r) for r in grid_r)

            for col in range(actual_cols):
                vertical_sums[col + 1]["Sum_R"].append(
                    sum(grid_r[row][col] for row in range(actual_rows))
                )
                vertical_sums[col + 1]["Sum_G"].append(
                    sum(grid_g[row][col] for row in range(actual_rows))
                )
                vertical_sums[col + 1]["Sum_B"].append(
                    sum(grid_b[row][col] for row in range(actual_rows))
                )

            for row in range(actual_rows):
                horizontal_sums[row + 1]["Sum_R"].append(sum(grid_r[row]))
                horizontal_sums[row + 1]["Sum_G"].append(sum(grid_g[row]))
                horizontal_sums[row + 1]["Sum_B"].append(sum(grid_b[row]))

        with open(vertical_output, "w") as f:
            f.write("vertical_thresholds = {\n")
            for color in ["Sum_R", "Sum_G", "Sum_B"]:
                f.write(f"    '{color}': {{\n")
                for col in sorted(vertical_sums):
                    f.write(
                        f"        {col}: "
                        f"({int(min(vertical_sums[col][color]))}, "
                        f"{int(max(vertical_sums[col][color]))}),\n"
                    )
                f.write("    },\n")
            f.write("}\n")

        with open(horizontal_output, "w") as f:
            f.write("horizontal_thresholds = {\n")
            for color in ["Sum_R", "Sum_G", "Sum_B"]:
                f.write(f"    '{color}': {{\n")
                for row in sorted(horizontal_sums):
                    f.write(
                        f"        {row}: "
                        f"({int(min(horizontal_sums[row][color]))}, "
                        f"{int(max(horizontal_sums[row][color]))}),\n"
                    )
                f.write("    },\n")
            f.write("}\n")

        print(f"✅ Vertical saved: {vertical_output}")
        print(f"✅ Horizontal saved: {horizontal_output}")
        print(f"✅ Threshold process completed in {time.time() - start_all:.2f} sec")

        return str(self.model_dir)

    def analyze_horizontal_blocks_to_excel(self, output_excel, num_horizontal_splits=4):
        all_data = []
        image_files = self.get_image_files()

        for filename in image_files:
            image_path = self.input_dir / filename
            image = cv2.imread(str(image_path))

            if image is None:
                continue

            clahe_bgr = self.apply_clahe(image)

            height, width, _ = clahe_bgr.shape
            block_height = height // self.num_rows
            split_width = width // num_horizontal_splits

            block_id = 0

            for row in range(self.num_rows):
                for split in range(num_horizontal_splits):
                    y_start = row * block_height
                    y_end = (row + 1) * block_height
                    x_start = split * split_width
                    x_end = (split + 1) * split_width

                    block = clahe_bgr[y_start:y_end, x_start:x_end]

                    b_channel, g_channel, r_channel = cv2.split(block)

                    sum_r = int(np.sum(r_channel))
                    sum_g = int(np.sum(g_channel))
                    sum_b = int(np.sum(b_channel))
                    total_sum = sum_r + sum_g + sum_b

                    rgb_sum = (
                        r_channel.astype(np.int32)
                        + g_channel.astype(np.int32)
                        + b_channel.astype(np.int32)
                    )

                    non_zero_pixels = int(np.count_nonzero(rgb_sum))
                    total_pixels = block.shape[0] * block.shape[1]
                    zero_pixels = total_pixels - non_zero_pixels

                    all_data.append([
                        filename,
                        block_id,
                        sum_r,
                        sum_g,
                        sum_b,
                        total_sum,
                        non_zero_pixels,
                        zero_pixels
                    ])

                    block_id += 1

            print(f"✅ Horizontal blocks completed: {filename}")

        df = pd.DataFrame(all_data, columns=[
            "image_id",
            "block_id",
            "sum_r",
            "sum_g",
            "sum_b",
            "sum_total_rgb",
            "non_zero_pixels",
            "zero_pixels"
        ])

        df.to_excel(output_excel, index=False)
        print(f"✅ Horizontal Excel saved: {output_excel}")

    def analyze_vertical_blocks_to_excel(self, output_excel, num_vertical_splits=4):
        all_data = []
        image_files = self.get_image_files()

        for filename in image_files:
            image_path = self.input_dir / filename
            image = cv2.imread(str(image_path))

            if image is None:
                continue

            clahe_bgr = self.apply_clahe(image)

            height, width, _ = clahe_bgr.shape
            block_width = width // self.num_cols
            split_height = height // num_vertical_splits

            block_id = 0

            for col in range(self.num_cols):
                for split in range(num_vertical_splits):
                    x_start = col * block_width
                    x_end = (col + 1) * block_width
                    y_start = split * split_height
                    y_end = (split + 1) * split_height

                    block = clahe_bgr[y_start:y_end, x_start:x_end]

                    b_channel, g_channel, r_channel = cv2.split(block)

                    sum_r = int(np.sum(r_channel))
                    sum_g = int(np.sum(g_channel))
                    sum_b = int(np.sum(b_channel))
                    total_sum = sum_r + sum_g + sum_b

                    rgb_sum = (
                        r_channel.astype(np.int32)
                        + g_channel.astype(np.int32)
                        + b_channel.astype(np.int32)
                    )

                    non_zero_pixels = int(np.count_nonzero(rgb_sum))
                    total_pixels = block.shape[0] * block.shape[1]
                    zero_pixels = total_pixels - non_zero_pixels

                    all_data.append([
                        filename,
                        block_id,
                        sum_r,
                        sum_g,
                        sum_b,
                        total_sum,
                        non_zero_pixels,
                        zero_pixels
                    ])

                    block_id += 1

            print(f"✅ Vertical blocks completed: {filename}")

        df = pd.DataFrame(all_data, columns=[
            "image_id",
            "block_id",
            "sum_r",
            "sum_g",
            "sum_b",
            "sum_total_rgb",
            "non_zero_pixels",
            "zero_pixels"
        ])

        df.to_excel(output_excel, index=False)
        print(f"✅ Vertical Excel saved: {output_excel}")

    def generate_threshold_py(self, excel_file, output_py_file, var_name="thresholds"):
        df = pd.read_excel(excel_file)

        columns_to_process = [
            "sum_r",
            "sum_g",
            "sum_b",
            "sum_total_rgb",
            "non_zero_pixels",
            "zero_pixels"
        ]

        result_dict = {col: {} for col in columns_to_process}
        block_ids = sorted(df["block_id"].unique())

        for block_id in block_ids:
            group = df[df["block_id"] == block_id]

            for col in columns_to_process:
                min_val = int(group[col].min())
                max_val = int(group[col].max())
                result_dict[col][block_id] = (min_val, max_val)

        with open(output_py_file, "w") as f:
            for col in columns_to_process:
                f.write(f"{var_name}_{col} = {{\n")
                for k in sorted(result_dict[col].keys()):
                    f.write(f"    {k}: {result_dict[col][k]},\n")
                f.write("}\n\n")

        print(f"✅ Threshold file created: {output_py_file}")

    def generate_new_thresholds(self):
        image_files = self.get_image_files()

        if not image_files:
            raise FileNotFoundError(f"No images found in:\n{self.input_dir}")

        v_xlsx = self.model_dir / "vertical_blocks.xlsx"
        h_xlsx = self.model_dir / "horizontal_blocks.xlsx"

        v_py = self.model_dir / "vertical_thresholds.py"
        h_py = self.model_dir / "horizontal_thresholds.py"

        self.analyze_vertical_blocks_to_excel(str(v_xlsx))
        self.analyze_horizontal_blocks_to_excel(str(h_xlsx))

        self.generate_threshold_py(
            str(v_xlsx),
            str(v_py),
            var_name="vertical_thresholds"
        )

        self.generate_threshold_py(
            str(h_xlsx),
            str(h_py),
            var_name="horizontal_thresholds"
        )

        print(f"✅ New H and V thresholds saved in: {self.model_dir}")

        return str(self.model_dir)