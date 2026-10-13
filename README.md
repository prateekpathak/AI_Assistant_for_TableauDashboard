# Tableau MCP Server

A [FastMCP](https://gofastmcp.com) server that wraps common Tableau Server /
Tableau Cloud REST API endpoints as standardized MCP tools, built on the
official `tableauserverclient` (TSC) Python library.

Configured for your site: `https://10ax.online.tableau.com` / site
`personalsandboxpp` (edit `.env.example` / env vars if this changes).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your Personal Access Token
```

Create a Personal Access Token in Tableau: **Account Settings → Personal
Access Tokens → Create new token**. PATs are the recommended auth method for
API automation since they can be scoped and revoked independently of your
login password.

Export the variables (or use a tool like `direnv`/`python-dotenv` to load
`.env` automatically):

```bash
export TABLEAU_SERVER_URL=https://10ax.online.tableau.com
export TABLEAU_SITE=personalsandboxpp
export TABLEAU_TOKEN_NAME=your-token-name
export TABLEAU_TOKEN_SECRET=your-token-secret
```

## Run

```bash
python server.py
```

By default FastMCP runs over stdio, which is what Claude Desktop / Claude
Code and most MCP clients expect. To add it to Claude Desktop, add to your
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tableau": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"],
      "env": {
        "TABLEAU_SERVER_URL": "https://10ax.online.tableau.com",
        "TABLEAU_SITE": "personalsandboxpp",
        "TABLEAU_TOKEN_NAME": "your-token-name",
        "TABLEAU_TOKEN_SECRET": "your-token-secret"
      }
    }
  }
}
```

To run over HTTP/SSE instead of stdio, change the last line of `server.py` to
`mcp.run(transport="streamable-http", port=8000)` — see FastMCP docs for
details.

## Tools exposed

| Tool | Wraps | Description |
|---|---|---|
| `whoami` | Sign In | Verify credentials, return site/server info |
| `list_projects` | Query Projects | List projects/folders |
| `list_workbooks` | Query Workbooks for Site | List workbooks, optional name filter |
| `get_workbook` | Query Workbook, Query Views for Workbook | Workbook detail + its views |
| `download_workbook` | Download Workbook | Save .twb/.twbx locally |
| `refresh_workbook_extract` | Update Workbook Now | Trigger extract refresh, returns job id |
| `list_views` | Query Views for Site | List views, optional name filter |
| `query_view_data` | Query View Data | Underlying summary data as rows |
| `download_view_image` | Query View Image | PNG render of a view |
| `download_view_pdf` | Query View PDF | PDF render of a view |
| `list_datasources` | Query Data Sources (REST) | List published data sources |
| `get_datasource_metadata` | Request Data Source Metadata (VDS `read-metadata`) | Field names, types, formulas for a data source — the modern replacement for the old "list fields" tool |
| `query_datasource` | Query Data Source (VDS `query-datasource`) | Run a VizQL query (aggregations, filters, sorts, top-N) directly against a data source |
| `refresh_datasource_extract` | Update Data Source Now | Trigger extract refresh, returns job id |
| `get_job_status` | Query Job | Poll status of an async refresh job |
| `list_users` | Query Users on Site | List site users, optional name filter |

## Two different Tableau APIs, one server

This server actually wraps **two separate Tableau API surfaces** under one MCP interface:

- The classic **REST API** (via `tableauserverclient`) — everything about content: projects, workbooks, views, users, jobs, extract refreshes.
- The **VizQL Data Service (VDS)** (`/api/v1/vizql-data-service/...`, called directly via `requests`, not wrapped by `tableauserverclient`) — everything about querying the actual data inside a published data source: `get_datasource_metadata` and `query_datasource`.

Both are authenticated with the same PAT-derived session token, so this is transparent to you as a user, but worth knowing if you extend the server: new REST-style tools go through `server.<resource>` (TSC), while new VDS-style tools go through `_vds_post()`.

`query_datasource` requires knowing valid field names first — always call `get_datasource_metadata` on a data source before querying it, since VDS field captions must match exactly (case-sensitive).

## Notes / design choices

- **Auth pattern**: each tool call signs in and out around itself rather than
  holding one long-lived session, since Tableau session tokens expire and MCP
  tool calls can be sparse/bursty. If you're making many calls in a tight
  loop and want to avoid repeated sign-ins, refactor `_session()` into a
  cached session with expiry tracking.
- **Pagination**: list tools accept a `limit` and internally over-fetch when
  a `name_filter` is applied (since TSC doesn't support server-side name
  filtering directly) — fine for moderate site sizes, but for very large
  sites you may want to switch to `RequestOptions` with server-side filters
  (TSC supports this via `TSC.RequestOptions().filter.add(...)`).
- **Extensibility**: to add more endpoints (e.g. subscriptions, flows,
  metrics, schedules, group management), follow the same pattern — call the
  relevant `server.<resource>` TSC method inside a `_session()` block and
  register it with `@mcp.tool()`.
