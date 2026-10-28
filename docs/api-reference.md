# API reference

This reference covers interfaces exposed by the tracked runtime sources:
`agent_api.py`, `server.py`, and `client.py`. It excludes private implementation
helpers and archived or untracked source variants.

## HTTP service (`agent_api.py`)

Run `python agent_api.py` to start Uvicorn. The default port is `8000`; the
`PORT` environment variable overrides it. The app serves its chat route and
the contents of `static/` from the same origin.

### `POST /chat`

Request JSON is validated by the `ChatRequest` Pydantic model:

| Field | Type | Default | Description |
|---|---|---|---|
| `message` | string | Required | User's message. |
| `thread_id` | string | `"default"` | LangGraph checkpoint thread identifier. |
| `context` | string | `""` | Optional Tableau dashboard context. |

When `context` is non-empty, the service invokes the agent with
`[Dashboard context]`, the context, and then the message. Otherwise it passes
the message as supplied.

Success response:

```json
{"reply": "Assistant response"}
```

If agent invocation raises an exception, the handler returns:

```json
{"reply": "Error: <exception message>", "error": true}
```

The handler does not set a separate HTTP error status for this caught
application error. Request validation failures are handled by FastAPI/Pydantic.

### Static assets and framework routes

- `GET /` and `GET /index.html` serve the static directory's HTML entry point
  (`static/index.html`); other paths under `/` are handled by the
  `StaticFiles` mount.
- FastAPI's default OpenAPI/schema and interactive documentation routes are
  also enabled: `/openapi.json`, `/docs`, and `/redoc`.

## MCP tools (`server.py`)

`server.py` registers the following tools on the FastMCP server named
`tableau-mcp`. When run directly, `mcp.run()` uses FastMCP's default transport
(stdio). Each tool signs into Tableau using the configured PAT and signs out
after the call.

`LUID` below means the Tableau content identifier accepted by the tool. Return
shapes list keys produced by this code; remote Tableau/VDS responses can contain
additional service-defined fields where noted.

### Site and projects

#### `whoami() -> dict`

No parameters. Returns `server_url`, `site_id`, `site_name`, and `server_info`.

#### `list_projects(limit: int = 50) -> list[dict]`

Returns up to `limit` projects. Each object has `id`, `name`, `description`,
and `parent_id`.

### Workbooks

#### `list_workbooks(limit: int = 50, name_filter: str | None = None) -> list[dict]`

Lists workbooks, optionally filtering by a case-insensitive name substring.
Returns objects with `id`, `name`, `project_name`, `owner_id`, `content_url`,
`webpage_url`, `created_at`, `updated_at`, and `size_mb`.

#### `get_workbook(workbook_id: str) -> dict`

`workbook_id` is a workbook LUID. Returns `id`, `name`, `project_name`,
`webpage_url`, `tags`, and `views`; each view has `id`, `name`, and
`content_url`.

#### `download_workbook(workbook_id: str, output_dir: str = "/tmp", include_extract: bool = False) -> dict`

`workbook_id` is a workbook LUID; `output_dir` is created if needed;
`include_extract` controls whether embedded extracts are included. Returns
`{"downloaded_path": "<path>"}`.

#### `refresh_workbook_extract(workbook_id: str) -> dict`

`workbook_id` is a workbook LUID. Starts an extract refresh and returns
`{"job_id": "<id>", "status": "<status>"}`; status is `"queued"` if the
Tableau job object has no `status` attribute.

### Views

#### `list_views(limit: int = 100, name_filter: str | None = None) -> list[dict]`

Lists views (sheets or dashboards), optionally filtered by a case-insensitive
name substring. Each object has `id`, `name`, `workbook_id`, and `content_url`.

#### `query_view_data(view_id: str, max_rows: int = 200) -> dict`

`view_id` is a view LUID. Returns CSV-parsed summary data as `columns` (header
array), `rows` (array of row arrays, capped at `max_rows`),
`row_count_returned`, `row_count_total`, and `truncated`.

#### `download_view_image(view_id: str, output_dir: str = "/tmp") -> dict`

`view_id` is a view LUID. Writes a PNG named from the view name (spaces replaced
with underscores) into `output_dir`, creating the directory if needed. Returns
`{"saved_path": "<path>"}`.

#### `download_view_pdf(view_id: str, output_dir: str = "/tmp") -> dict`

`view_id` is a view LUID. Writes a PDF named from the view name (spaces replaced
with underscores) into `output_dir`, creating the directory if needed. Returns
`{"saved_path": "<path>"}`.

### Data sources and queries

#### `list_datasources(limit: int = 50, name_filter: str | None = None) -> list[dict]`

Lists published data sources, optionally filtered by a case-insensitive name
substring. Each object has `id`, `name`, `project_name`, `type`, `content_url`,
and `updated_at`.

#### `get_datasource_metadata(datasource_id: str) -> dict`

`datasource_id` is a data-source LUID. Returns the raw JSON object from the
VizQL Data Service `read-metadata` response, including the service's
field-level metadata.

#### `query_datasource(datasource_id: str, fields: list[dict], filters: list[dict] | None = None, limit: int | None = None) -> dict`

- `datasource_id`: data-source LUID.
- `fields`: VDS field specifications. The code passes these through as the
  query's `fields` array; field captions must match metadata captions.
- `filters`: optional VDS filter specifications; omitted when `None` or empty.
- `limit`: optional maximum row count; when provided, passed to VDS as
  `options.rowLimit`.

Returns the raw JSON object from the VizQL Data Service `query-datasource`
response, requested with `returnFormat: "OBJECTS"`.

#### `refresh_datasource_extract(datasource_id: str) -> dict`

`datasource_id` is a data-source LUID. Starts a refresh and returns
`{"job_id": "<id>", "status": "<status>"}`; status is `"queued"` if the
Tableau job object has no `status` attribute.

### Jobs and users

#### `get_job_status(job_id: str) -> dict`

`job_id` is a Tableau job ID, such as one returned by an extract refresh.
Returns `id`, `type`, `created_at`, `started_at`, `completed_at`, `finish_code`,
and `notes`.

#### `list_users(limit: int = 50, name_filter: str | None = None) -> list[dict]`

Lists site users, optionally filtered case-insensitively against the user's
name, full name, or email. Each object has `id`, `name`, `fullname`, `email`,
and `site_role`.

### Tableau Pulse

#### `list_pulse_metrics() -> list[dict]`

No parameters. Lists Pulse metric definitions. Each object has `definition_id`,
`name`, `description`, `datasource_id`, `measure`, `aggregation`,
`time_dimension`, `allowed_dimensions`, `allowed_granularities`, and
`default_metric_id`.

#### `get_pulse_insights(metric_name: str | None = None, definition_id: str | None = None, bundle_type: str = "ban", granularity: str | None = None, comparison: str | None = None, period: str | None = None) -> dict`

- `metric_name`: case-insensitive exact definition name; ignored if
  `definition_id` is provided.
- `definition_id`: exact definition identifier; takes precedence over name.
- `bundle_type`: `"ban"`, `"springboard"`, or `"detail"`; default `"ban"`.
- `granularity`: optional `"day"`, `"week"`, `"month"`, `"quarter"`, or
  `"year"`.
- `comparison`: optional `"previous_period"` or `"year_ago"`.
- `period`: optional `"current_partial"` or `"last_complete"`.

At least one of `metric_name` or `definition_id` is required. Returns
`metric`, `definition_id`, `datasource_id`, `bundle_type`, `granularity`,
`period`, `comparison`, `insights` (groups of `{group, insights}`, where each
insight has `type` and `text`), and `note` (a string or `null`).

## Terminal client (`client.py`)

Run `python client.py` for an interactive terminal chat. The module exposes
`async main() -> None` as its entrypoint; it prompts for messages until `exit`
or `quit`, invokes its LangGraph agent, and prints the final response. It does
not expose an HTTP endpoint. `TABLEAU_MCP_SERVER_PATH` optionally overrides the
default `server.py` subprocess path.
