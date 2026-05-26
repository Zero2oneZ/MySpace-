# MySpace++ — studio container (DAG canvas + Wardrobe + YouTube cutter)
# Separate image because the Streamlit/opencv/rembg stack is ~1 GB heavier
# than the core substrate. Friends who only want core can skip this profile.
#
# Build:   docker build -t myspace-pp-studio:local -f studio.Dockerfile .
# Run:     docker run --rm -p 8510:8510 myspace-pp-studio:local wardrobe

FROM python:3.11-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Native deps for opencv-python-headless, rembg (onnxruntime), Pillow,
# yt-dlp, and ffmpeg for video pipelines.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

WORKDIR /opt/studio

# Install Python deps in a layer that caches well.
COPY studio/requirements.txt /opt/studio/requirements.txt
RUN pip install -r /opt/studio/requirements.txt

# Copy studio sources. .dockerignore excludes .venv, media caches, AND
# studio/auth/permissions.jsonl (per-host state — auto-seeded on first launch).
COPY studio/ /opt/studio/

# Streamlit ports: 8501 (DAG canvas), 8510 (wardrobe), 8511 (yt-cutter).
EXPOSE 8501 8510 8511

# Outputs go here. Mount a volume for persistence.
VOLUME ["/opt/studio/media"]

# Dispatcher: `docker run ... studio` → run.sh, `wardrobe` → run-wardrobe.sh,
# `yt` → run_yt_cutter.sh. Default = wardrobe (most friend-friendly first run).
COPY <<'EOF' /usr/local/bin/studio-launch
#!/usr/bin/env bash
set -euo pipefail
cd /opt/studio
case "${1:-wardrobe}" in
  studio|dag)   exec streamlit run app.py             --server.headless true --server.address 0.0.0.0 --server.port 8501 ;;
  wardrobe)     exec streamlit run wardrobe_studio.py --server.headless true --server.address 0.0.0.0 --server.port 8510 ;;
  yt|yt-cut)    exec streamlit run yt_cutter.py       --server.headless true --server.address 0.0.0.0 --server.port 8511 ;;
  test)         exec python test_pipelines.py ;;
  *)            echo "studio-launch: unknown mode '$1' (use studio|wardrobe|yt|test)" >&2; exit 1 ;;
esac
EOF
RUN chmod +x /usr/local/bin/studio-launch

LABEL org.opencontainers.image.title="MySpace++ Studio" \
      org.opencontainers.image.description="DAG canvas + Wardrobe + YT cutter Streamlit apps" \
      org.opencontainers.image.licenses="LicenseRef-Proprietary" \
      org.opencontainers.image.vendor="Tom Lee (Zero2oneZ)"

ENTRYPOINT ["studio-launch"]
CMD ["wardrobe"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:8510/_stcore/health > /dev/null \
     || curl -sf http://localhost:8501/_stcore/health > /dev/null \
     || curl -sf http://localhost:8511/_stcore/health > /dev/null \
     || exit 1
