# syntax=docker/dockerfile:1.7
#
# Multi-stage build for competitive-intel-agents.
#
# Stage 1 ("builder") installs the project into an isolated prefix so the
# runtime image only carries the resolved site-packages, not the build
# toolchain or pip caches. Stage 2 ("runner") copies that prefix on top
# of a minimal slim image and runs as an unprivileged user.
#
# Why python:3.12-slim:
#   - pyproject declares requires-python >= 3.12
#   - curl_cffi ships manylinux wheels for 3.12; -slim already has the
#     glibc those wheels target, so no compiler is needed at install
#   - alpine would force a musl rebuild of curl_cffi (no wheel) which
#     blows up the image size and CI time

FROM python:3.12-slim AS builder

WORKDIR /build

# Copy only what is needed to install the package. ``.dockerignore``
# scrubs the rest so changes to docs / tests / cached runs do not bust
# the install layer cache.
COPY pyproject.toml README.md ./
COPY src ./src

# --prefix=/install puts the resolved site-packages and entry-point
# scripts in a single tree we can COPY wholesale into the runtime stage.
RUN pip install --no-cache-dir --prefix=/install .


FROM python:3.12-slim AS runner

# Run as a non-root user. uid 1000 is the conventional first user on
# Debian-derived images and matches what host-mounted volumes typically
# own when bind-mounted from a developer workstation.
RUN useradd --create-home --shell /bin/bash --uid 1000 appuser

# Bring in the resolved python install (site-packages + the
# ``competitive-intel`` console script) from the builder stage.
COPY --from=builder /install /usr/local

# /data is where the workspace (artifacts.sqlite, journal.sqlite,
# runs.json) lives. docker-compose mounts a host volume here.
RUN mkdir -p /data && chown appuser:appuser /data

USER appuser
WORKDIR /home/appuser

# Forces stdout/stderr to be unbuffered so logs surface in
# ``docker logs`` immediately, and selects JSON log format by default
# so log shippers can parse without configuration.
ENV PYTHONUNBUFFERED=1 \
    CIA_LOG_FORMAT=json

EXPOSE 8080

# HEALTHCHECK shells back into Python (already on PATH) instead of
# pulling curl into the image. urllib raises on any non-2xx, which is
# the right semantics — we want unhealthy → restart.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3).status==200 else sys.exit(1)" \
    || exit 1

# Bind to 0.0.0.0 so connections coming through the bridge network
# reach the server. Default workspace path matches the volume mount.
CMD ["competitive-intel", "web", "--host", "0.0.0.0", "--port", "8080", "--workspace", "/data"]
