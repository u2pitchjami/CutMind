""" """

from __future__ import annotations

from pathlib import Path
import uuid

import numpy as np
from PIL import Image
import torch

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import MULTIPLE_FRAMES_DIR_SC


def load_frames_as_tensor(
    frames_dir: Path,
    segment_id: str,
    size: tuple[int, int] = (512, 512),
    max_frames: int = 5,
) -> torch.Tensor:
    """
    Charge les frames d’un segment vidéo et les empile en un batch tensor [N, 3, H, W].
    """
    segment_dir = Path(frames_dir)
    files = sorted(segment_dir.glob(f"{segment_id}_*.jpg"))

    if not files:
        raise CutMindError(
            "❌ Aucune frame pour le segment en cours.",
            code=ErrCode.NOFILE,
            ctx=get_step_ctx({"frames_dir": str(frames_dir), "segment_id": segment_id}),
        )
        raise FileNotFoundError(f"Aucune frame trouvée pour {segment_id} dans {frames_dir}")

    selected_files = files[:max_frames]

    tensors: list[torch.Tensor] = []
    try:
        for path in selected_files:
            img = Image.open(path).convert("RGB")
            if size:
                w, h = size  # width, height
                img = img.resize((w, h))
            arr = np.asarray(img, dtype=np.float32) / 255.0  # [H, W, 3]
            tensor = torch.from_numpy(arr).permute(2, 0, 1)  # → [3, H, W]
            tensors.append(tensor)

        frames_tensor = torch.stack(tensors, dim=0)  # → [N, 3, H, W]
        return frames_tensor
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du frame tensor.",
            code=ErrCode.VIDEO,
            ctx=get_step_ctx({"frames_dir": str(frames_dir), "segment_id": segment_id}),
        ) from exc


def temp_batch_image(image_batch: torch.Tensor, seed: str | int) -> list[str]:
    """
    Sauvegarde un batch d'images (tensor [N, C, H, W]) en fichiers temporaires PNG.

    Retourne une liste d'URI "file://..."
    """
    image_paths: list[str] = []
    try:
        num_images = image_batch.shape[0]
        for idx in range(num_images):
            img_tensor = image_batch[idx].cpu().numpy().squeeze()

            # [C, H, W] → [H, W, C]
            if img_tensor.ndim == 3 and img_tensor.shape[0] in (1, 3, 4):
                img_tensor = np.transpose(img_tensor, (1, 2, 0))

            arr = np.clip(255.0 * img_tensor, 0, 255).astype(np.uint8)
            img = Image.fromarray(arr).convert("RGB")

            unique_id = uuid.uuid4().hex
            image_path = MULTIPLE_FRAMES_DIR_SC / f"temp_image_{seed}_{idx}_{unique_id}.jpg"
            img.save(image_path, format="JPEG", quality=95)

            image_paths.append(f"file://{image_path.resolve().as_posix()}")

        return image_paths
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du batch_images.",
            code=ErrCode.VIDEO,
            ctx=get_step_ctx({"image_batch": image_batch}),
        ) from exc
