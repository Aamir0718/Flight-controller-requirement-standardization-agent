---
title: Flight Controller Requirements Agent
emoji: 🛩️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Flight Controller Requirements Agent — Backend

FastAPI + local Ollama (`gemma3:4b`) backend for the requirements
standardization pipeline. Deployed here so the Next.js frontend
(hosted separately, e.g. on Vercel) has a public API to call.

This is a deploy snapshot of `src/` and `config/` from the main repo —
see `sync_backend.ps1` for how it's kept in sync.

Set the `CORS_ALLOWED_ORIGINS` Space secret/variable to your deployed
frontend's origin (e.g. `https://your-app.vercel.app`) so the browser
is allowed to call this API.

Health check: `/health`
