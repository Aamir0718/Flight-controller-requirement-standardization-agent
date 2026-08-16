# Backend deployment image for a Hugging Face Space (Docker SDK).
# Bundles Ollama + the gemma3:4b weights + the FastAPI app in one
# always-on container, since HF Spaces don't let you run a second
# process (Ollama) outside the container you deploy.
#
# This is a deploy SNAPSHOT: src/ and config/ are copied in here from
# the main repo (see sync_backend.ps1 in this folder). Re-run that
# script and re-push after backend changes.

FROM python:3.11-slim

# curl: Ollama installer + startup healthcheck. build-essential: in case
# any Python dependency needs to compile from source on this platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://ollama.com/install.sh | sh

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY config ./config

# Bake the model weights into the image so the Space doesn't have to
# re-download ~3GB every time it restarts/wakes from sleep. Starts the
# daemon just for this build layer, pulls the model, then stops it --
# the pulled weights persist in /root/.ollama regardless.
RUN ollama serve & \
    sleep 5 && \
    ollama pull gemma3:4b && \
    kill %1

COPY start.sh .
RUN chmod +x start.sh

# HF Spaces (Docker SDK) route traffic to port 7860 by default.
EXPOSE 7860

CMD ["./start.sh"]
