# syntax=docker/dockerfile:1.7
#
# The backend and every tool, in one image -- because the tools are the backend's own child
# processes, talking to it over MCP on stdio, and that is the architecture (../CLAUDE.md), not
# something a container boundary should quietly change. The web app is a different image
# (web.Dockerfile): the two stay separate programs.
#
# Built from Shelby's root:  docker build -f docker/backend.Dockerfile .   (or compose)

ARG PYTHON=3.14-slim
ARG NODE=24-slim

FROM node:${NODE} AS node
FROM python:${PYTHON} AS python

# cpu, or nvidia for NVIDIA's builds of the speech models' libraries (about 4 GB more): cuBLAS for meet-ai's
# Whisper, PyTorch's CUDA build for audiobook. ./start-docker passes nvidia when the host has an NVIDIA card
# Docker can hand to a container (compose.nvidia.yaml). The image needs no CUDA of its own: the driver comes
# from the host, the rest from these packages.
ARG GPU=cpu

# --- Shelby's shared Python environment (assistant, meet-ai, mail-ai, apply-ai, web-ai) -----------------
# Built at the path it will run from, since a venv's scripts name their own location.
FROM python AS shared-venv
ARG GPU
WORKDIR /app
COPY assistant/requirements.txt assistant/
COPY meet-ai/requirements.txt meet-ai/requirements-dev.txt meet-ai/requirements-nvidia.txt meet-ai/
COPY mail-ai/requirements.txt mail-ai/requirements-dev.txt mail-ai/
COPY apply-ai/requirements.txt apply-ai/requirements-dev.txt apply-ai/
COPY web-ai/requirements.txt web-ai/requirements-dev.txt web-ai/
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv .venv \
 && .venv/bin/pip install -r assistant/requirements.txt \
      -r meet-ai/requirements.txt -r meet-ai/requirements-dev.txt \
      $([ "$GPU" = nvidia ] && echo -r meet-ai/requirements-nvidia.txt) \
      -r mail-ai/requirements.txt -r mail-ai/requirements-dev.txt \
      -r apply-ai/requirements.txt -r apply-ai/requirements-dev.txt \
      -r web-ai/requirements.txt -r web-ai/requirements-dev.txt \
 && .venv/bin/pip check

# --- audiobook's own: torch, Docling, Pocket TTS -- ~1.9 GB nothing else uses (CPU build) -------------
FROM python AS audiobook-venv
ARG GPU
WORKDIR /app/audiobook
COPY audiobook/requirements.txt audiobook/requirements-dev.txt audiobook/requirements-nvidia.txt audiobook/install-deps ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv .venv \
 && ./install-deps .venv/bin/python "$GPU"

# --- docu-ai's Node packages (tsx, which runs it, is a dev dependency) -----------------------------
FROM node AS docu-ai-deps
WORKDIR /app/docu-ai
COPY docu-ai/package.json docu-ai/package-lock.json ./
RUN npm ci --no-audit --no-fund

# --- what runs -----------------------------------------------------------------------------------
FROM python AS runtime

# ffmpeg: every tool that touches audio. pulseaudio-utils: `pactl`, how meet-ai lists microphones
# (only useful with compose.audio.yaml). bzip2: unpacking the speaker models. poppler-utils:
# `pdftotext`, how docu-ai reads where a built document's pages break (without it a build still
# works and says its layout was not measured).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg pulseaudio-utils curl ca-certificates bzip2 poppler-utils \
 && rm -rf /var/lib/apt/lists/*

# Node, for docu-ai: the binary and npm from the official image, not a second package manager.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Not root, and the same numbers as the person who owns ./data, so what the tools write there
# is theirs to read and move.
ARG SHELBY_UID=1000
ARG SHELBY_GID=1000
RUN groupadd --gid ${SHELBY_GID} shelby \
 && useradd --create-home --uid ${SHELBY_UID} --gid ${SHELBY_GID} --shell /bin/bash shelby

WORKDIR /app
COPY --from=shared-venv /app/.venv /app/.venv
COPY --from=audiobook-venv /app/audiobook/.venv /app/audiobook/.venv
COPY . /app
# Owned by the user it runs as: vitest keeps its cache inside node_modules.
COPY --chown=shelby:shelby --from=docu-ai-deps /app/docu-ai/node_modules /app/docu-ai/node_modules

# meet-ai's speaker models (~37 MB). Whisper's and Pocket TTS's are fetched on first use into the
# data volume (HF_HOME), so they are downloaded once, not once per image build.
RUN meet-ai/fetch-models.sh

# audiobook keeps its data in folders relative to itself, and reads no setting for where. Rather
# than change it, point those folders into the one volume. Everything else takes its location
# from an environment variable (compose.yaml).
RUN mkdir -p /data \
 && for d in voices voice output .cache; do ln -s "/data/audiobook/${d#.}" "/app/audiobook/$d"; done \
 && ln -s /data/audiobook/.env /app/audiobook/.env \
 && chown -R shelby:shelby /data /app/meet-ai/models

ENV HOME=/home/shelby \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER shelby
EXPOSE 8750
# The backend's own launcher: it finds Shelby's .venv, and it launches every tool as a child.
CMD ["/app/assistant/assistant-web"]
