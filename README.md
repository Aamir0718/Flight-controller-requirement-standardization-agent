# Flight Controller Requirement Standardization Agent

## How to Run the Project in VS Code (Offline PC)

---

## STEP 1: Open the Project

Open the project folder in VS Code.

Example:

```text
E:\Projects\fli original
```

---

## STEP 2: Open Terminal

In VS Code:

```text
Terminal → New Terminal
```

Or press:

```text
Ctrl + `
```

---

## STEP 3: Activate Python Virtual Environment

Run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Then:

```powershell
.\.venv\Scripts\Activate.ps1
```

The terminal should show something similar to:

```text
(.venv) PS E:\Projects\fli original>
```

---

## STEP 4: Check Ollama

Run:

```powershell
ollama list
```

Make sure the required model exists:

```text
gemma3:4b
```

If the model is available, proceed.

---

## STEP 5: Start Backend

In the first terminal, run:

```powershell
scripts\run_api.ps1
```

Keep this terminal running.

The backend should start at:

```text
http://127.0.0.1:8000
```

---

## STEP 6: Start Frontend

Open a **second terminal** in VS Code.

Run:

```powershell
cd frontend
```

Then:

```powershell
npm start
```

If `npm start` does not work, try:

```powershell
npm run dev
```

The frontend should be available at:

```text
http://localhost:3000
```

---

# Normal Daily Startup

## Terminal 1 — Backend

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
scripts\run_api.ps1
```

Keep this terminal running.

---

## Terminal 2 — Frontend

```powershell
cd frontend
npm start
```

If required:

```powershell
npm run dev
```

---

# If Python Dependencies Are Missing

Since this project runs on an offline PC, install packages from the local `offline_packages` folder:

```powershell
pip install --no-index --find-links=offline_packages -r requirements.txt
```

---

# If the Frontend Shows an Old or Broken Build

Stop the frontend.

Delete the Next.js build folder:

```text
frontend\.next
```

Then restart the frontend:

```powershell
cd frontend
npm start
```

Or:

```powershell
npm run dev
```

---

# Important

Do **NOT** delete these folders:

```text
.venv
frontend\node_modules
offline_packages
```

These are required for the offline environment.

---

# Quick Start

## Terminal 1 — Backend

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
scripts\run_api.ps1
```

## Terminal 2 — Frontend

```powershell
cd frontend
npm start
```

Open the application:

```text
http://localhost:3000
```