#!/bin/sh
# Starts Ollama (model weights already baked into the image at build
# time) and waits for its API to answer before starting the FastAPI app,
# so the first real request isn't the thing that discovers Ollama is
# still warming up.
set -e

ollama serve &

until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 1
done

exec uvicorn ui.api:app --host 0.0.0.0 --port 7860 --app-dir /app/src
