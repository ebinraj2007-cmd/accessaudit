# AccessAudit — production image
#
# Same shape as NoorDesk's: multi-stage so the compiler doesn't ship, non-root
# so a dependency RCE isn't automatically root, healthcheck against /healthz so
# "process alive" isn't mistaken for "app working".
#
# One difference worth knowing about. AccessAudit resolves its database path at
# import time from __file__:
#
#     DB_PATH = Path(__file__).resolve().parent.parent / "data" / "accessaudit.db"
#
# There is no environment override, unlike NoorDesk's NOORDESK_DB. So the volume
# has to be mounted where the code already looks — /app/data — rather than
# somewhere tidier like /data. Mounting /data and setting a variable would
# silently do nothing, and the findings would live inside the container until it
# was replaced.

# ---------------------------------------------------------------- builder ---
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .

# openpyxl and its dependencies occasionally need a compiler on platforms
# without a matching wheel. Build here, discard the toolchain, ship neither.
RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential \
 && pip install --upgrade pip \
 && pip install -r requirements.txt \
 && apt-get purge -y build-essential \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------- runtime ---
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
 && apt-get install --no-install-recommends -y curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1001 accessaudit \
 && useradd --system --uid 1001 --gid accessaudit --create-home accessaudit

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=accessaudit:accessaudit . .

# Must be /app/data — see the note at the top. The audit trail is the point of
# this application; losing it when a container is replaced would be worse than
# losing the findings.
RUN mkdir -p /app/data && chown accessaudit:accessaudit /app/data
VOLUME ["/app/data"]

USER accessaudit

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:8010/healthz || exit 1

CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8010"]
