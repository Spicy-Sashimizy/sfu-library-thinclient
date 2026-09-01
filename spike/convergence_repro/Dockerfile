# Convergence-artifact synthetic repro — benchmark cell image.
#
# Field-standard tools only (PREREGISTRATION.md "Design"):
#   fio      — the mmap random-read pass engine
#   vmtouch  — per-file page-cache eviction + residency verification
#              (no global drop_caches dependence)
#   procps   — /proc helpers
#   time     — GNU time -v, the majflt source (Major page faults line)
#   python3  — JSON assembly inside the cell (no third-party modules)
#   coreutils— dd for the sequential "load" phase
#
# Build:  docker build -t convrepro:latest spike/convergence_repro
FROM debian:bookworm-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        fio \
        vmtouch \
        procps \
        time \
        python3 \
        coreutils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /bench
COPY cell.sh /bench/cell.sh
COPY jobs /bench/jobs
RUN chmod +x /bench/cell.sh

# The benchmark data (R.bin, L.bin) arrives via a docker NAMED VOLUME mounted
# at /data — never a bind mount from the dev container (that path would
# resolve on the docker host, and the dev-container workspace is v9fs).
VOLUME ["/data"]

ENTRYPOINT ["/bench/cell.sh"]
