# Container image for the AI Report Generator (the Streamlit demo app).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# System deps:
#   - libreoffice-impress : renders the .pptx to .pdf (drop this line to shrink the
#                           image ~300MB; PDF export then degrades gracefully to PPTX only)
#   - fonts-liberation    : Arial-compatible fonts so the matplotlib charts match the deck
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Bake the demo datasets into the image so "Use sample data" works out of the box.
RUN python scripts/gen_sales_data.py && python scripts/gen_budget_data.py

# Azure Container Apps provides the port via $PORT; default to 8501 for local runs.
ENV PORT=8501
EXPOSE 8501
CMD streamlit run app/streamlit_app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
