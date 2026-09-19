# Homework 1 — Bash script, TorchScript model and Docker images for inference

This project shows the full path from preparing the environment to running an ML model inside a
container. It contains a bash script that prepares the tools, a script that exports `mobilenet_v2`
to TorchScript, an inference script in Python, and two Docker images (fat and slim) that are
compared with each other.

The comparison of the two images is in [`report.md`](report.md).

## Requirements

| Tool | Version | Used for |
|---|---|---|
| Docker | 20.10 or newer (tested on 29.4.0) | building and running the images |
| Docker Compose | V2 (`docker compose version`) | checked by the setup script |
| Python | **3.13** | `torch==2.7.0` has no packages for Python 3.14 |
| uv | 0.8 or newer (optional) | creating the virtual environment |

Python dependencies are fixed in [`requirements.txt`](requirements.txt):
`torch==2.7.0`, `torchvision==0.22.0`, `pillow==11.2.1`.

> **About the Python version.** The setup script creates a local virtual environment `.venv` with
> Python 3.13 and installs the libraries **only there**. The system Python is not changed. If the
> computer does not have Python 3.13, `uv` downloads it. All commands below are run after
> `source .venv/bin/activate`.

## Project structure

```
lesson-3/
├── app/
│   └── inference.py            # takes an image path, prints the top-3 predictions
├── model/
│   └── model.pt                # TorchScript model (13.8 MB), created by export_model.py
├── scripts/
│   └── install_dev_tools.sh    # checks and prepares the environment, safe to run many times
├── export_model.py             # exports mobilenet_v2 with torch.jit.trace
├── requirements.txt            # fixed versions of the dependencies
├── Dockerfile.fat              # simple image based on python:3.13
├── Dockerfile.slim             # optimised multi-stage image based on python:3.13-slim
├── .dockerignore               # excludes .git, caches, virtual environment, archives
├── example.jpg                 # test image
├── install.log                 # log file written by the setup script
├── report.md                   # comparison of the two images
└── README.md
```

## How to run

### 1. Prepare the environment

```bash
./scripts/install_dev_tools.sh
source .venv/bin/activate
```

The script checks Docker, Docker Compose V2, Python 3.13 or newer, pip, and the libraries `torch`,
`torchvision` and `pillow`. What is missing, it installs into `.venv`. For Docker it prints
instructions instead, because a script should not install Docker Desktop by itself. The script can
be run many times: on the second run it installs nothing and only reports the current state.
Everything it does is also written to [`install.log`](install.log).

After activating the environment, the commands from the task description work:

```bash
docker --version
docker compose version
python3 --version
pip3 --version
python3 -c "import torch; print(torch.__version__)"
```

### 2. Export the model

```bash
python3 export_model.py
```

This downloads `mobilenet_v2` with the `IMAGENET1K_V1` weights, switches it to `eval()` mode, traces
it with `torch.jit.trace` on a `1x3x224x224` tensor and saves the result to `model/model.pt`.

### 3. Run inference locally

```bash
python3 app/inference.py example.jpg
```

### 4. Build the images

```bash
docker build -f Dockerfile.fat  -t ml-infer-fat:1.0  .
docker build -f Dockerfile.slim -t ml-infer-slim:1.0 .
```

### 5. Run inference in the containers

```bash
docker run --rm -v "$PWD/example.jpg:/app/example.jpg:ro" ml-infer-fat:1.0  example.jpg
docker run --rm -v "$PWD/example.jpg:/app/example.jpg:ro" ml-infer-slim:1.0 example.jpg
```

### 6. Compare the images

```bash
docker images | grep ml-infer
docker history ml-infer-fat:1.0
docker history ml-infer-slim:1.0
```

## Example of the result

```
$ python3 app/inference.py example.jpg
Image: example.jpg
Top-3 predictions:
  1. class_id=258  confidence=0.854601  Samoyed
  2. class_id=259  confidence=0.058790  Pomeranian
  3. class_id=261  confidence=0.013076  keeshond
```

Both Docker images print exactly the same result:

```
  1. class_id=258  confidence=0.854600  Samoyed
  2. class_id=259  confidence=0.058791  Pomeranian
  3. class_id=261  confidence=0.013077  keeshond
```

The confidence values from the local run differ only in the sixth digit after the point. This is a
normal rounding difference between macOS and Linux. The classes and their order are the same.

## Difference between the fat and slim images

| | Fat | Slim |
|---|---|---|
| Base image | `python:3.13` (about 1124 MB) | `python:3.13-slim` (about 152 MB) |
| Build | one stage | two stages: builder and runtime |
| pip cache | stays inside the image (128 MB) | removed by `--no-cache-dir` |
| System packages | `build-essential`, `git`, `curl`, `wget`, `vim` | none |
| Copying the code | `COPY . .`, the whole folder | only `app/`, `model/` and `example.jpg` |
| User | root | `appuser` (uid 10001) |
| **Size** | **1.98 GB**, 12 layers | **816 MB**, 10 layers (59% smaller) |

## Source of `example.jpg`

The picture comes from the official [pytorch/hub](https://github.com/pytorch/hub) repository, file
`images/dog.jpg`, licence BSD-3-Clause. It is the same image that the PyTorch documentation uses.
It was resized to 640 px on the longer side with `sips -Z 640` to keep the repository small.

## Submission

- Branch: [`lesson-3`](https://github.com/MaksDeGreez/goit-mlops/tree/lesson-3)
- The archive is created from the root of the repository:

  ```bash
  zip -r ДЗ3_Слєпцов_Максім.zip lesson-3/ -x "lesson-3/.venv/*"
  unzip -l ДЗ3_Слєпцов_Максім.zip
  ```
