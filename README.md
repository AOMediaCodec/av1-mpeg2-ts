# Carriage of AV1 in MPEG-2 TS

Official AOM specification for carrying AV1 video elementary streams in MPEG-2 Transport Stream format, written using [Bikeshed](https://speced.github.io/bikeshed/).

### Table of Contents

- [Introduction](#introduction)
- [Prerequisites](#prerequisites)
- [Building the Specification](#building-the-specification)
  - [Prepare Virtual Environment](#prepare-virtual-environment)
  - [Compile Specification](#compile-specification)
- [Known Implementations](#known-implementations)
- [License](#license)

## Introduction

This repository contains the source files used to generate the **Carriage of AV1 in MPEG-2 TS** specification. The specification source is `index.bs`, processed by the [Bikeshed](https://github.com/speced/bikeshed) specification preprocessor to produce `index.html`.

The latest published version is available at: https://AOMediaCodec.github.io/av1-mpeg2-ts

## Prerequisites

Ensure the following are installed:

- [Python 3](https://www.python.org/downloads/) — required for the build script and Bikeshed
- [Git](https://git-scm.com) — version control

[Bikeshed](https://github.com/speced/bikeshed) and all other dependencies are installed automatically into the virtual environment (see below).

## Building the Specification

Clone the repository:

```sh
git clone https://github.com/AOMediaCodec/av1-mpeg2-ts.git
cd av1-mpeg2-ts
```

### Prepare Virtual Environment

Create and activate the virtual environment, then install dependencies:

```sh
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

On subsequent runs, just activate it:

```sh
source venv/bin/activate
```

### Compile Specification

There are two build modes:

**Quick build** — renders syntax blocks as plain code blocks (no extra processing):
```sh
bikeshed spec
```

**Full build** — converts SDL syntax blocks into formatted HTML tables:
```sh
python compile.py
```

**Full build with PDF** — same as above, also generates `index.pdf`:
```sh
python compile.py --pdf
```

The output is written to `index.html` (and `index.pdf` if requested). Open either file in a browser to preview the specification.

## Known Implementations

- **FFmpeg**: https://code.ffmpeg.org/FFmpeg/FFmpeg/pulls/21307
- **VLC**: https://code.videolan.org/videolan/vlc/-/merge_requests/6837
- **GStreamer (WIP)**: https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11015

## License

For licensing information, please refer to the [LICENSE](LICENSE) file included in this repository.
