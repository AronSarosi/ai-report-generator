# Container image for the AI Report Generator. One image serves both surfaces:
# APP_MODE=ui (default) runs the Streamlit demo, APP_MODE=api runs FastAPI.
#
# Single-stage on purpose: there are no compiled artifacts to discard, and the
# image weight is dominated by the libreoffice-impress apt layer, which the
# final image needs anyway - a multi-stage build would not shrink it.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MPLCONFIGDIR=/tmp/matplotlib

# System deps:
#   - libreoffice-impress : renders the .pptx to .pdf (drop this line to shrink the
#                           image ~300MB; PDF export then degrades gracefully to PPTX only)
#   - fonts-liberation    : Arial-compatible fonts so the matplotlib charts match the deck
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Files copied from a Windows host arrive without the Unix executable bit, so
# the ENTRYPOINT script must be made executable explicitly (else Cloud Run fails
# to start with "permission denied").
RUN chmod +x docker/entrypoint.sh

# Bake the demo datasets into the image so "Use sample data" works out of the box,
# then hand /app to the non-root user (the app writes data/db|out|charts at runtime).
RUN python scripts/gen_sales_data.py && python scripts/gen_budget_data.py \
    && chown -R appuser:appuser /app

USER appuser
ENV HOME=/home/appuser

# The platform provides the listen port via $PORT (Cloud Run defaults to 8080,
# Azure Container Apps also injects it); default to 8080 for local parity with Cloud Run.
ENV PORT=8080 APP_MODE=ui
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD ["python", "docker/healthcheck.py"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
