# Local Codebase Explainer

A local-first tool for exploring an unfamiliar codebase. It scans supported files safely, stores isolated per-project vector indexes on your device, and answers questions through Ollama with verifiable source references.

## Requirements

- Python 3.11 or newer
- [Ollama](https://ollama.com/) running locally
- A local chat model (default: `llama3.2`) and embedding model (default: `nomic-embed-text`)

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
ollama pull llama3.2
ollama pull nomic-embed-text
streamlit run app.py --server.address 127.0.0.1
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`.

The app connects to `http://localhost:11434` by default. You can change model names, file-size limits, chunk sizes, and evidence threshold in the sidebar. Enter the full project path in the app; supported text files are scanned and the app explains why other files were skipped. Refresh updates changed files, full rebuild starts a clean generation, and Clear index removes only the selected project's local index.

Source snippets are sent only to Ollama on this device for local embeddings and answers; non-loopback model URLs are rejected, environment proxies are bypassed for model calls, and Chroma and Streamlit usage telemetry are disabled. Project files are never executed. Indexes are stored under the operating system's per-user application data directory, separate from the project.
