# Running the Project (Offline)

Open **3 terminals**.

---

# Terminal 1 — Ollama

Start the Ollama server.

```bash
ollama serve
```

(Optional) Verify the model is available.

```bash
ollama list
```

Expected model:

```
gemma3:4b
```

or

```
llama3.1
```

Leave this terminal running.

---

# Terminal 2 — Backend

Navigate to the project.

```powershell
cd Flight-controller-requirement-standardization-agent
```

Create a virtual environment (only the first time).

```powershell
python -m venv .venv
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Activate the virtual environment.

```powershell
.\.venv\Scripts\Activate.ps1
```

Install Python dependencies (only the first time).

```powershell
pip install --no-index --find-links=offline_packages -r requirements.txt
```

Start the backend.

```powershell
scripts\run_api.ps1
```

Backend URL:

```
http://127.0.0.1:8008
```

---

# Terminal 3 — Frontend

Navigate to the frontend.

```powershell
cd frontend
```

> **Important:** Before running the frontend on an offline machine, copy the following folders from the development machine into the `frontend` directory:
>
> - `node_modules/`
> - `.next/`

Start the frontend.

```powershell
npm start
```

If needed:

```powershell
npm run dev
```

Frontend URL:

```
http://localhost:3000
```

---

# Verify

All three terminals should now be running:

- ✅ Terminal 1 → Ollama
- ✅ Terminal 2 → FastAPI Backend (Port 8008)
- ✅ Terminal 3 → Next.js Frontend (Port 3000)

Open:

```
http://localhost:3000
```

The application is now ready to use.