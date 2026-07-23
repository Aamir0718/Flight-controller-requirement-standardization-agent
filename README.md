# Flight Controller Requirements Platform

## Easy Setup Guide

Hi!

Follow these steps one by one. You need **3 terminals**.

---

## STEP 1 — Clone the project (only the first time)

```powershell
git clone <your-repo-url>
cd Flight-controller-requirement-standardization-agent
```

---

## TERMINAL 1 — Backend (Python)

1. Open a terminal in the project folder.

2. Activate the virtual environment:

   ```powershell
   .venv\Scripts\Activate.ps1
   ```

3. Tell Python where the source code is:

   ```powershell
   $env:PYTHONPATH = "src"
   ```

4. Start the backend:

   ```powershell
   scripts\run_api.ps1
   ```

   If everything is correct, you should see something like:

   ```
   Uvicorn running on: http://127.0.0.1:8000
   ```

5. Open this in your browser:

   ```
   http://127.0.0.1:8000/health
   ```

   You should see:

   ```json
   {"status": "ok"}
   ```

   If you see this, the backend is working.

---

## TERMINAL 2 — Ollama

Check if Ollama is installed and which models you have:

```powershell
ollama list
```

If `gemma3:4b` is missing:

```powershell
ollama pull gemma3:4b
```

If `llama3.1` is missing:

```powershell
ollama pull llama3.1
```

Now start Ollama:

```powershell
ollama serve
```

If it says it is already running, that is completely fine.

> **Note:** `gemma3:4b` is a small model. On complex or ambiguous requirement text it will occasionally still need a retry (the backend handles this automatically — see "AI Response Validation Failed" below). If you see repeated validation failures on the same file, try switching the configured model to `llama3.1` in `config/settings.yaml` for more reliable structured output.

---

## TERMINAL 3 — Frontend (Website)

Open another terminal.

Go inside the frontend folder:

```powershell
cd frontend
```

Only the first time:

```powershell
npm install
```

Every time after that:

```powershell
npm run dev
```

Now open:

```
http://localhost:3000
```

The website should open.

---

## RUN ORDER

Always start everything in this order:

**Terminal 1**
```powershell
.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
scripts\run_api.ps1
```

**Terminal 2**
```powershell
ollama serve
```

**Terminal 3**
```powershell
cd frontend
npm run dev
```

---

## HOW TO CHECK EVERYTHING

- Backend: http://127.0.0.1:8000/health
- Frontend: http://localhost:3000

If both open correctly, everything is running.

---

## HOW TO USE THE PROJECT

1. Open the website.
2. Upload an Excel (`.xlsx`) file.
3. Click **Start Pipeline Analysis**.
4. Wait for the processing to finish.
5. Review the AI-generated requirement suggestions on the **Requirement Review** page.
6. Check the **Consistency Analysis** page for duplicates, similar pairs, and contradictions across requirements.
7. Accept or reject each recommendation.
8. Export the final reviewed Excel file from the **Export Center**.

---

## IF SOMETHING DOESN'T WORK

### Backend not running?

Run:
```powershell
scripts\run_api.ps1
```
Backend health page should open: http://127.0.0.1:8000/health

If you see an `IndentationError` or `SyntaxError` in the traceback right after starting the backend, it means a source file under `src/` has a typo or bad indentation (commonly `src/llm/local_llm_client.py` if it was recently edited). Check the exact file and line number named in the traceback.

---

### Frontend not opening?

Go to frontend:
```powershell
cd frontend
```
Run:
```powershell
npm install
```
Then:
```powershell
npm run dev
```

---

### Ollama error?

Run:
```powershell
ollama serve
```

If the backend reports `AI_SERVICE_UNAVAILABLE`, Ollama isn't reachable — confirm it's running and that the host/port in `config/settings.yaml` match.

---

### Model missing?

Run:
```powershell
ollama pull gemma3:4b
```
or
```powershell
ollama pull llama3.1
```

---

### "AI Response Validation Failed" on the Processing Status page

This means Ollama returned a response that didn't match the required JSON schema, even after one automatic retry. It does **not** mean your Excel file is wrong.

Suggested actions:
- Click **Retry Processing** on the same file.
- Restart the local Ollama service (`ollama serve`).
- Confirm the configured model is pulled and available (`ollama list`).
- If this happens often with `gemma3:4b`, switch to `llama3.1` in `config/settings.yaml` — smaller models are more prone to malformed structured output.

---

### Consistency Analysis page shows 0 duplicates / 0 similar / 0 contradictions on a file that should have some

1. Check the backend terminal for a line like:
   ```
   Consistency analysis completed for run N: X relationships found
   ```
   If you instead see `Consistency analysis FAILED for run N: ...`, the analysis hit an error and no relationships were saved — read the traceback above that line for the cause.
2. Click **Re-analyze** on the Consistency Analysis page after fixing any backend issue — this re-runs analysis on the existing run without re-uploading the file.
3. Very short or very generic requirement text can sometimes score below the similarity threshold even when related — this is expected behavior, not a bug.

---

## THAT'S IT!

Once these three terminals are running, the complete application will work.

Happy Coding!
