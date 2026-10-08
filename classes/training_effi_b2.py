import os
import cv2
import joblib
import torch
import numpy as np
from PIL import Image
from torchvision import models, transforms
from sklearn.decomposition import PCA
from path import MODELS_DIR,TRAINING_IMAGES_DIR


class EffB2Trainer:

    def __init__(
        self,
        pca_components: int = 40,
        percentile: float   = 95.0,
    ):
        # ===============================
        # DEVICE
        # ===============================
        self.DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

        # ===============================
        # CONFIG
        # ===============================
        self.pca_components = pca_components
        self.percentile     = percentile
        # self.MODEL_PATH     = MODELS_DIR / "effb2_pca_model.joblib"
        # self.STAT_PATH      = MODELS_DIR / "effb2_stats.joblib"

        # os.makedirs(os.path.dirname(self.MODEL_PATH) or ".", exist_ok=True)
        # os.makedirs(os.path.dirname(self.STAT_PATH)  or ".", exist_ok=True)

        print(f"[EffB2Trainer] Device        : {self.DEVICE}")
        # print(f"[EffB2Trainer] PCA model out : {self.MODEL_PATH}")
        # print(f"[EffB2Trainer] Stats out     : {self.STAT_PATH}")

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
        # FEATURE BUFFER
        # ===============================
        self._features: list = []

    # ------------------------------------------------------------------
    # ADD FRAME  (call once per good frame)
    # ------------------------------------------------------------------
    def add_frame(self, frame: np.ndarray) -> None:
       
        if frame is None:
            return

        rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        x       = self.tf(pil_img).unsqueeze(0).to(self.DEVICE)

        with torch.no_grad():
            feat = self.model(x).cpu().numpy().flatten()

        self._features.append(feat)

    # ------------------------------------------------------------------
    # TRAIN  (call after all good frames are added)
    # ------------------------------------------------------------------
    def train(self, job_id, progress_callback=None) -> float:
        n = len(self._features)

        if n < 2:
            raise ValueError(f"Need at least 2 frames, got {n}")

        features = np.array(self._features)

        components = min(self.pca_components, n - 1)

        pca = PCA(n_components=components)
        X = pca.fit_transform(features)

        mean = X.mean(axis=0)

        # ✅ Fix covariance issue when components == 1
        if components == 1:
            cov = np.array([[np.var(X[:, 0]) + 1e-6]])
        else:
            cov = np.cov(X, rowvar=False) + np.eye(components) * 1e-6

        inv = np.linalg.inv(cov)

        scores = [
            float((x - mean) @ inv @ (x - mean))
            for x in X
        ]

        threshold = float(np.percentile(scores, self.percentile))

        # ✅ Create job folder
        job_model_dir = MODELS_DIR / str(job_id)
        job_model_dir.mkdir(parents=True, exist_ok=True)

        model_path = job_model_dir / f"{job_id}_model.joblib"
        stat_path  = job_model_dir / f"{job_id}_stats.joblib"

        joblib.dump(pca, model_path)
        joblib.dump((mean, inv, threshold), stat_path)

        if progress_callback:
            progress_callback(100, "Training model saved")

        print(f"[EffB2Trainer] Trained on {n} frames.")
        print(f"[EffB2Trainer] Threshold: {threshold:.2f}")
        # print(f"[EffB2Trainer] Saved PCA   → {model_path}")
        # print(f"[EffB2Trainer] Saved stats → {stat_path}")

        return threshold
    
    def _train_from_folder_legacy(self, job_id: str, progress_callback=None) -> float:
        folder_path = TRAINING_IMAGES_DIR / job_id
        if not os.path.isdir(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        self._features.clear()

        count = 0

        for file in sorted(os.listdir(folder_path)):
            if file.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                img_path = os.path.join(folder_path, file)
                frame = cv2.imread(img_path)

                if frame is None:
                    print(f"❌ Cannot read: {img_path}")
                    continue

                self.add_frame(frame)
                count += 1
                print(f"✅ Added: {count}")

        if count == 0:
            raise ValueError(f"No images found in folder: {folder_path}")

        print(f"[EffB2Trainer] Total images loaded: {count}")

        return self.train(job_id)
    
    def train_from_folder(self, job_id: str, progress_callback=None) -> float:
        folder_path = TRAINING_IMAGES_DIR / job_id
        if not os.path.isdir(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        self._features.clear()

        image_files = [
            file for file in sorted(os.listdir(folder_path))
            if file.lower().endswith((".jpg", ".jpeg", ".png", ".bmp"))
        ]
        total = len(image_files)
        if total == 0:
            raise ValueError(f"No images found in folder: {folder_path}")

        if progress_callback:
            progress_callback(1, f"Found {total} training images")

        count = 0
        for file in image_files:
            img_path = os.path.join(folder_path, file)
            frame = cv2.imread(img_path)

            if frame is None:
                print(f"Cannot read: {img_path}")
                continue

            self.add_frame(frame)
            count += 1
            if progress_callback:
                percent = 1 + int((count / total) * 89)
                progress_callback(percent, f"Extracting features {count}/{total}")
            print(f"Added: {count}")

        if count == 0:
            raise ValueError(f"No readable images found in folder: {folder_path}")

        print(f"[EffB2Trainer] Total images loaded: {count}")

        if progress_callback:
            progress_callback(92, "Building PCA model")

        return self.train(job_id, progress_callback=progress_callback)
    
    def train_from_files(
        self,
        job_id: str,
        filenames,
        progress_callback=None,
    ) -> float:

        folder_path = TRAINING_IMAGES_DIR / str(job_id)

        if not folder_path.is_dir():
            raise FileNotFoundError(
                f"Folder not found: {folder_path}"
            )

        self._features.clear()

        image_files = list(filenames or [])
        total = len(image_files)

        if total == 0:
            raise ValueError("No training images selected")

        if progress_callback:
            progress_callback(
                1,
                f"Found {total} selected images",
            )

        count = 0

        for filename in image_files:
            # Prevent invalid paths
            safe_name = os.path.basename(str(filename))
            image_path = folder_path / safe_name

            if not image_path.is_file():
                print(f"Image not found: {image_path}")
                continue

            frame = cv2.imread(str(image_path))

            if frame is None:
                print(f"Cannot read: {image_path}")
                continue

            self.add_frame(frame)
            count += 1

            if progress_callback:
                percent = 1 + int(
                    (count / total) * 89
                )

                progress_callback(
                    percent,
                    f"Extracting features {count}/{total}",
                )

            print(f"Added: {count} - {safe_name}")

        if count < 2:
            raise ValueError(
                f"Need at least 2 readable images, got {count}"
            )

        print(
            f"[EffB2Trainer] Total selected images loaded: "
            f"{count}"
        )

        if progress_callback:
            progress_callback(
                92,
                "Building PCA model",
            )

        return self.train(
            job_id,
            progress_callback=progress_callback,
        )


if __name__ == "__main__":
    trainer = EffB2Trainer()
    trainer.train_from_folder("check")
