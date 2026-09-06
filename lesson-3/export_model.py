"""Export a pretrained MobileNetV2 to a TorchScript module.

The traced module is self-contained: it carries the weights and the forward graph,
so the inference image does not need to rebuild the model architecture in Python.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from torchvision.models import MobileNet_V2_Weights, mobilenet_v2

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PROJECT_ROOT / "model" / "model.pt"


def export(output: Path) -> None:
    # The `weights=` enum is the current API; `pretrained=True` has been removed.
    weights = MobileNet_V2_Weights.IMAGENET1K_V1
    model = mobilenet_v2(weights=weights)

    # eval() must be called before tracing. It switches the model to prediction
    # mode. If the model is traced in training mode, it returns different
    # results every time it is called.
    model.eval()

    example_input = torch.randn(1, 3, 224, 224)
    with torch.no_grad():
        traced = torch.jit.trace(model, example_input)

    output.parent.mkdir(parents=True, exist_ok=True)
    traced.save(str(output))

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"Model:   mobilenet_v2 ({weights})")
    print(f"Saved:   {output}")
    print(f"Size:    {size_mb:.1f} MB")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export MobileNetV2 as TorchScript.")
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"output path for the traced model (default: {DEFAULT_OUTPUT})",
    )
    export(parser.parse_args().output)


if __name__ == "__main__":
    main()
