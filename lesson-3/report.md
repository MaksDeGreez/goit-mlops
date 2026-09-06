# Report: comparing the fat and slim Docker images

## Test conditions

| Parameter | Value |
|---|---|
| Host | macOS (Apple Silicon), Docker 29.4.0 |
| Image architecture | `linux/arm64` |
| Base images | `python:3.13` (fat) and `python:3.13-slim` (slim) |
| Model | `mobilenet_v2`, weights `IMAGENET1K_V1`, saved with `torch.jit.trace` |
| Dependencies | `torch==2.7.0`, `torchvision==0.22.0`, `pillow==11.2.1` |
| Test image | `example.jpg` (640x502, 95 KB) |

Both images were built from scratch, so the build time also includes downloading the base image.
Sizes are shown the way Docker shows them.

## Comparison table

| Metric | Fat image | Slim image |
|---|---|---|
| Image size | **1.98 GB** | **816 MB** (59% smaller) |
| Number of layers | 12 | 10 |
| Build time | 50 s | 26 s |
| Inference result | Samoyed / Pomeranian / keeshond | exactly the same |
| Extra tools inside | yes: gcc, git, wget, vim, pip cache | no, only what inference needs |

## Layer analysis (`docker history`)

### Fat image, 1.98 GB

| Layer | Size | Needed to run inference? |
|---|---|---|
| Base image `python:3.13` (6 layers) | about 1124 MB | only partly: the interpreter yes, the developer libraries no |
| `pip install -r requirements.txt` | **777 MB** | only partly: 128 MB of it is the pip cache |
| `apt-get install build-essential git curl wget vim` | 68.4 MB | **no** |
| `COPY . .` | 14.6 MB | only partly: the model yes, the rest no |

### Slim image, 816 MB

| Layer | Size | Comment |
|---|---|---|
| Base image `python:3.13-slim` (3 layers) | about 152 MB | 7 times smaller than the full base image |
| `COPY --from=builder /install /usr/local` | **635 MB** | the libraries themselves, without the pip cache |
| `RUN useradd && chown -R` | 14.6 MB | this repeats the model layer, see the ideas below |
| `COPY model/` | 14.5 MB | the saved model |
| `COPY app/` and `COPY example.jpg` | 0.1 MB | the script and the test image |

## What the fat image did not need

1. **The pip cache, 128 MB.** Without the `--no-cache-dir` flag, pip keeps every downloaded package
   inside the image. After the build these files are never used again.
2. **The build tools, about 92 MB.** `build-essential` installs gcc (24 MB), and `git`, `wget` and
   `vim` are also installed. None of them are used by `python app/inference.py`. The packages we
   install are ready-made, so no compiler is needed.
3. **The apt package lists, 21 MB.** They stay in `/var/lib/apt/lists` because the build never
   deletes them.
4. **The base image itself, about 972 MB more than the slim one.** `python:3.13` also contains
   database client libraries, version control tools and other developer packages.
5. **Extra project files.** `COPY . .` copied `export_model.py`, `requirements.txt`, `scripts/`,
   both Dockerfiles and `.dockerignore` into the image. These are needed to build the project,
   not to run it.

## What changed in the slim image

- **Two build stages.** The first stage installs the libraries into `/install`. The second stage
  copies only that folder. The pip cache and any temporary build files stay in the first stage and
  never reach the final image.
- **A smaller base image.** `python:3.13-slim` is about 152 MB instead of about 1124 MB. No extra
  system packages were needed, because the `torch` and `pillow` packages already include the
  binary libraries they depend on.
- **Copying only what is used.** Instead of `COPY . .` there are three lines: `app/`, `model/` and
  `example.jpg`. Checking the running container with `ls -A /app` shows exactly these three items
  and nothing else.
- **A normal user instead of root.** The container runs as `appuser` (uid 10001), which is safer.

## Did the inference result change?

No. Both containers print exactly the same text:

```
  1. class_id=258  confidence=0.854600  Samoyed
  2. class_id=259  confidence=0.058791  Pomeranian
  3. class_id=261  confidence=0.013077  keeshond
```

Running the same script directly on the Mac gives the same three classes in the same order, but the
confidence values differ in the sixth digit after the point (`0.854601` instead of `0.854600`).
This is a normal rounding difference between macOS and Linux and does not change the prediction.

## Ideas for further optimization

1. **Use `COPY --chown` instead of a separate `chown -R`.** Right now the `chown -R /app` command
   creates a 14.6 MB layer that simply repeats the model file, because changing the owner of a file
   makes Docker store the whole file again. One changed line saves 14.6 MB.
2. **Do not copy `example.jpg` into the image.** The image is always started with `-v`, so the test
   picture can come from outside. The image then does not depend on test data.
3. **Delete the C++ header files of PyTorch (51 MB).** They are only needed to build extensions,
   not to run a model.
4. **Do not install `torchvision` in the final image.** It is used for image preprocessing, but the
   same steps can be written with `pillow` only, using fixed numbers for resize and normalisation.

## Conclusion

The multi-stage build on the slim base image made the image 59% smaller, from 1.98 GB to 816 MB,
and the build twice as fast, from 50 to 26 seconds. The result of the inference stayed exactly the
same: both images print identical output.

Two changes gave almost all of the result: the smaller base image (about 972 MB) and removing the
pip cache together with the build tools (about 220 MB).

It is also useful to see what is left. In the slim image PyTorch itself takes 404 MB, which is half
of the final size. So the Dockerfile is no longer the main problem. To go much lower, the next step
would be to change what we install, not how we install it.
