# Storage

This document describes storage used by the tracked application code. It does
not infer a backing store from the external services' internal implementations.

## Configuration and credentials

`server.py`, `agent_api.py`, and `client.py` call `load_dotenv()`, which loads
environment settings from a `.env` file in the process's current directory
when present. Environment variables are also used directly.

| Setting | Use |
|---|---|
| `TABLEAU_SERVER_URL` | Tableau server base URL; defaults in `server.py` to `https://10ax.online.tableau.com`. |
| `TABLEAU_SITE` | Tableau site content URL; defaults in `server.py` to `personalsandboxpp`. |
| `TABLEAU_TOKEN_NAME` | Personal Access Token name used for sign-in. |
| `TABLEAU_TOKEN_SECRET` | Personal Access Token secret used for sign-in. |
| `TABLEAU_MCP_SERVER_PATH` | Optional path to the `server.py` subprocess used by the HTTP app and CLI; defaults to `"server.py"`. |
| `OPENAI_API_KEY` | Required by the `ChatOpenAI` integration; read by its library from the environment. |
| `PORT` | Optional Uvicorn port for `agent_api.py`; defaults to `8000`. |

`.env.example` is the checked-in template for Tableau settings. `.env` is
excluded by `.gitignore`; credentials should be supplied through the local
environment or that ignored file. The code does not write credentials to a
separate store.

## In-memory agent state

- `agent_api.py` keeps the created agent in a process-global `state` dictionary.
- Both the HTTP and terminal LangGraph agents use `InMemorySaver` as their
  checkpoint saver. Conversation checkpoints are held in process memory and
  associated with the configured thread ID; they are not written to disk or a
  database by this project.
- The extension creates a random `thread_id` per page load. The HTTP model
  defaults to `"default"` when callers omit it. The CLI uses the fixed
  `"cli-session-1"` identifier for its run.
- In-memory agent/checkpoint state is lost when the relevant process exits.
  The project defines no database, durable conversation store, or application
  cache.

## Local files

- `static/index.html` and `chat.trex` are project files; `agent_api.py` serves
  the `static/` directory through FastAPI's `StaticFiles` mount.
- `download_workbook` writes Tableau workbook files to its `output_dir`
  argument, defaulting to the literal path `"/tmp"`. It creates the directory
  if it does not already exist. Whether that path is appropriate depends on the
  host operating system.
- `download_view_image` and `download_view_pdf` write PNG and PDF files under
  their respective `output_dir` arguments, also defaulting to `"/tmp"`. Their
  output names derive from the Tableau view name, with spaces replaced by
  underscores. Existing files at the same path can be overwritten.
- The `query_view_data` and data-source query tools return data in the response;
  they do not write query results to local files.

## Remote data and service responses

Tableau Server/Cloud remains the source for projects, workbooks, views, data
sources, users, job status, and Pulse definitions/insights. Tableau refresh
operations are remote jobs; the application returns job identifiers and can
query their status. VDS and Pulse payloads are fetched over HTTP and returned
to the caller/agent; the project does not persist those payloads locally.

The LangChain/OpenAI model and optional tracing integrations are external
services. This project does not implement local persistence for prompts,
responses, or traces.
