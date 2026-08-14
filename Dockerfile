FROM python:3.12-slim

# I-12: the sha is baked HERE, at build time, from the artifact's own stamp.
# A runtime COMMIT_SHA env var is ignored by api/app/buildinfo.py. This is the
# structural fix for nine sibling services that cannot name their own commit.
ARG COMMIT_SHA=""
ARG BUILT_AT=""

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY api ./api
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

# I-12: an EMPTY COMMIT_SHA must fail the build, not sail through it.
# Previously the sed replaced "" with "" (a no-op) and the grep then matched
# that same empty string, so a build with no COMMIT_SHA passed and shipped a
# container reporting commit_sha: null — exactly the "service cannot name its
# own commit" defect this project exists to prevent. Caught 2026-08-14 when
# /version went null after a deploy.
RUN test -n "${COMMIT_SHA}" || (echo "FATAL: COMMIT_SHA build arg is empty (I-12)" && false) \
 && sed -i "s|^BAKED_COMMIT_SHA: str = \"\"|BAKED_COMMIT_SHA: str = \"${COMMIT_SHA}\"|" api/app/buildinfo.py \
 && sed -i "s|^BAKED_BUILT_AT: str = \"\"|BAKED_BUILT_AT: str = \"${BUILT_AT}\"|" api/app/buildinfo.py \
 && grep -q "BAKED_COMMIT_SHA: str = \"${COMMIT_SHA}\"" api/app/buildinfo.py

EXPOSE 8600
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -fsS http://localhost:8600/health || exit 1

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8600"]
