#!/bin/sh
# One image, two surfaces: APP_MODE selects which server this container runs.
#   APP_MODE=ui  (default) -> Streamlit demo app
#   APP_MODE=api           -> FastAPI service (uvicorn)
set -e

PORT="${PORT:-8501}"

if [ "$APP_MODE" = "api" ]; then
    exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
fi

exec streamlit run app/streamlit_app.py \
    --server.port="$PORT" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --browser.gatherUsageStats=false
