#!/usr/bin/env bash
# Download the ONNX models used for speaker diarization (~36 MB).
# Only needed if you plan to use --diarize; Whisper models fetch themselves.
#
# From Hugging Face, not GitHub: the same two files, and a GitHub release download is what timed out
# in an image build (2026-10-28) while Hugging Face answered. Each file is checked against the SHA-256
# of the copy this was written against, so a changed or truncated download fails loudly instead of
# quietly breaking diarization later.
#
# Each URL names a commit, not "main" (2026-11-20): the owner of the embedding repo replaced that file on
# Hugging Face a day before an image build, "main" then served a different file (one byte longer, other
# hash) and the build failed on the check, though nothing here had changed. A commit never changes, so the
# check now tests the download, not whether upstream moved. Both commits were fetched and hashed against
# the pins below. To take a newer model on purpose: change the commit and the hash together.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p models && cd models

SEG_DIR=sherpa-onnx-pyannote-segmentation-3-0
SEG_REV=9403a6902bb58e3d5ae8c7e77c3422de279db2e0
SEG_BASE=https://huggingface.co/csukuangfj/$SEG_DIR/resolve/$SEG_REV
# Upstream's file is named for its original release; diarize.py looks for campplus_en.onnx.
EMB_REV=0743f301363dec56491a490f6d6cbc9d67f9a3bf
EMB=https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/$EMB_REV/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx

SEG_SHA256=220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079
EMB_SHA256=357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b

# fetch <url> <file> <sha256>: download to a .part file and move it into place only once it is the right file.
fetch() {
  curl -fsSL --retry 3 --connect-timeout 20 -o "$2.part" "$1"
  echo "$3  $2.part" | sha256sum -c --quiet - || { rm -f "$2.part"; echo "$2: downloaded file does not match the expected SHA-256" >&2; exit 1; }
  mv "$2.part" "$2"
}

if [[ ! -f $SEG_DIR/model.onnx ]]; then
  echo "Fetching speaker segmentation model..."
  mkdir -p "$SEG_DIR"
  fetch "$SEG_BASE/model.onnx" "$SEG_DIR/model.onnx" "$SEG_SHA256"
  curl -fsSL --retry 3 --connect-timeout 20 -o "$SEG_DIR/LICENSE" "$SEG_BASE/LICENSE"
fi

if [[ ! -f campplus_en.onnx ]]; then
  echo "Fetching speaker embedding model..."
  fetch "$EMB" campplus_en.onnx "$EMB_SHA256"
fi

echo "Models ready:"
find . -name "*.onnx" -printf "  %p (%s bytes)\n"
