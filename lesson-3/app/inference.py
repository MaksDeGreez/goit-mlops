"""Run image classification with the traced MobileNetV2 model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from PIL import Image
from torchvision.models import MobileNet_V2_Weights

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = PROJECT_ROOT / "model" / "model.pt"


def predict(image_path: Path, model_path: Path, top_k: int) -> list[tuple[int, float, str]]:
    if not image_path.is_file():
        raise SystemExit(f"error: image not found: {image_path}")
    if not model_path.is_file():
        raise SystemExit(f"error: model not found: {model_path} (run export_model.py first)")

    weights = MobileNet_V2_Weights.IMAGENET1K_V1
    # The weights come with their own transforms, so the image is prepared
    # exactly the same way as during training (resize, crop, normalise).
    preprocess = weights.transforms()
    categories = weights.meta["categories"]

    # convert("RGB") makes sure the image always has 3 colour channels,
    # also for grey or transparent pictures.
    image = Image.open(image_path).convert("RGB")
    batch = preprocess(image).unsqueeze(0)

    model = torch.jit.load(str(model_path), map_location="cpu")
    model.eval()

    with torch.no_grad():
        logits = model(batch)
    probabilities = logits.softmax(dim=1).squeeze(0)

    confidences, class_ids = probabilities.topk(top_k)
    return [
        (int(class_id), float(confidence), categories[int(class_id)])
        for class_id, confidence in zip(class_ids, confidences)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify an image with the traced model.")
    parser.add_argument("image", type=Path, help="path to the input image")
    parser.add_argument("-m", "--model", type=Path, default=DEFAULT_MODEL, help="path to model.pt")
    parser.add_argument("-k", "--top-k", type=int, default=3, help="how many predictions to print")
    args = parser.parse_args()

    predictions = predict(args.image, args.model, args.top_k)

    print(f"Image: {args.image}")
    print(f"Top-{args.top_k} predictions:")
    for rank, (class_id, confidence, label) in enumerate(predictions, start=1):
        # A fixed number of digits lets us compare the output of the two
        # images with diff.
        print(f"  {rank}. class_id={class_id:<4d} confidence={confidence:.6f}  {label}")


if __name__ == "__main__":
    sys.exit(main())
