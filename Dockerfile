# MySpace++ — universal container image
# Base: debian-slim. Target image size: under 200 MB (no model bundled).
# The myspace binary inside lives at /usr/local/bin/myspace and /usr/local/bin/cc.
# Volume mounts:
#   /data       → CC_HOME (DBs, cache, scripts) — bind to a persistent dir
#   /workspace  → cwd inside the container — bind to your project root
# Ollama, if used, is reached at http://ollama:11434 by default (compose convention).
#
# Build:   docker build -t myspace-pp:local .
# Run:     docker run --rm -it -v "$PWD:/workspace" -v "$HOME/.cc-home:/data" myspace-pp:local -help

FROM debian:bookworm-slim AS runtime

# Avoid interactive prompts during apt operations.
ENV DEBIAN_FRONTEND=noninteractive

# Runtime deps. Pinned to slim Debian's defaults; image size stays small.
# - bash:       substrate language
# - python3:    db.py / tui.py / studio.py (sqlite3 is stdlib)
# - curl, jq:   ollama HTTP calls + JSON parsing in cc
# - sqlite3:    CLI used by smoke tests
# - coreutils:  sha256sum, mktemp, dirname, basename, date (most are already
#               in slim, but pinning makes intent explicit)
# - ca-certificates: for HTTPS curl
# - uuid-runtime: provides uuidgen (UUID fallback in cc)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        python3 \
        ca-certificates \
        curl \
        jq \
        sqlite3 \
        coreutils \
        uuid-runtime \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Copy the substrate.
COPY core/ /opt/myspace-pp/
RUN chmod +x /opt/myspace-pp/cc \
             /opt/myspace-pp/tests/*.sh \
             /opt/myspace-pp/setup/*.sh \
    && ln -sf /opt/myspace-pp/cc /usr/local/bin/myspace \
    && ln -sf /opt/myspace-pp/cc /usr/local/bin/cc

# Pin install root so the auto-discovery doesn't have to guess.
ENV CC_INSTALL_ROOT=/opt/myspace-pp \
    CC_HOME=/data \
    CC_CACHE=/data/cache \
    CC_GLOBAL_DB=/data/cc.db \
    CC_OLLAMA_URL=http://ollama:11434 \
    CC_AUTO_SCOPE=1

# Persistent state lives in /data — mount a volume here.
# /workspace is the user's project root — mount cwd here.
VOLUME ["/data"]
WORKDIR /workspace

# OCI labels for ecosystem tooling.
LABEL org.opencontainers.image.title="MySpace++" \
      org.opencontainers.image.description="Deterministic terminal substrate for AI orchestration" \
      org.opencontainers.image.licenses="LicenseRef-Proprietary" \
      org.opencontainers.image.vendor="Tom Lee (Zero2oneZ)" \
      org.opencontainers.image.documentation="https://github.com/zero2onez/MySpace-pp"

# Default entrypoint runs myspace; default command shows help.
# Override CMD for real use: docker run ... myspace-pp:local <subcommand>
ENTRYPOINT ["myspace"]
CMD ["-help"]

# Healthcheck: cheap, doesn't need ollama.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD myspace -help > /dev/null 2>&1 || exit 1
