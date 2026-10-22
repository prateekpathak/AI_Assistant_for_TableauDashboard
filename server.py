"""
Tableau MCP Server
===================
Wraps common Tableau Server / Tableau Cloud REST API endpoints as standardized
MCP tools using FastMCP.

Auth: Personal Access Token (PAT) — recommended by Tableau for automation/API
use over username+password, since it doesn't require storing a real password
and can be revoked independently.

Configuration is via environment variables (see .env.example):
  TABLEAU_SERVER_URL     e.g. https://10ax.online.tableau.com
  TABLEAU_SITE           content-url of the site, e.g. personalsandboxpp
  TABLEAU_TOKEN_NAME     name of the Personal Access Token
  TABLEAU_TOKEN_SECRET   secret value of the Personal Access Token

Run:
  pip install -r requirements.txt
  export TABLEAU_SERVER_URL=https://10ax.online.tableau.com
  export TABLEAU_SITE=personalsandboxpp
  export TABLEAU_TOKEN_NAME=my-token
  export TABLEAU_TOKEN_SECRET=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  python server.py
"""

import os
import io
import csv
import contextlib
from typing import Optional

import requests
import tableauserverclient as TSC
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()  # reads a .env file in the current directory, if present

mcp = FastMCP("tableau-mcp")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SERVER_URL = os.environ.get("TABLEAU_SERVER_URL", "https://10ax.online.tableau.com")
SITE_ID = os.environ.get("TABLEAU_SITE", "personalsandboxpp")
TOKEN_NAME = os.environ.get("TABLEAU_TOKEN_NAME")
TOKEN_SECRET = os.environ.get("TABLEAU_TOKEN_SECRET")


def _get_server() -> TSC.Server:
    """Create and sign in to a Tableau Server connection using a PAT.

    A fresh sign-in is used per call rather than a long-lived global session,
    since MCP tool calls can be infrequent and Tableau session tokens expire.
    """
    if not TOKEN_NAME or not TOKEN_SECRET:
        raise RuntimeError(
            "Missing credentials. Set TABLEAU_TOKEN_NAME and TABLEAU_TOKEN_SECRET "
            "environment variables (create a Personal Access Token in Tableau: "
            "Account Settings -> Personal Access Tokens)."
        )
    tableau_auth = TSC.PersonalAccessTokenAuth(TOKEN_NAME, TOKEN_SECRET, SITE_ID)
    server = TSC.Server(SERVER_URL, use_server_version=True)
    server.auth.sign_in(tableau_auth)
    return server


@contextlib.contextmanager
def _session():
    server = _get_server()
    try:
        yield server
    finally:
        try:
            server.auth.sign_out()
        except Exception:
            pass


def _paged(pager, limit: int) -> list:
    out = []
    for i, item in enumerate(pager):
        if i >= limit:
            break
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Tools — Sites / connectivity
# ---------------------------------------------------------------------------

@mcp.tool()
def whoami() -> dict:
    """Verify credentials and return the current site and server info."""
    with _session() as server:
        return {
            "server_url": SERVER_URL,
            "site_id": SITE_ID,
            "site_name": server.site_id,
            "server_info": str(server.server_info) if server.server_info else None,
        }


# ---------------------------------------------------------------------------
# Tools — Projects
# ---------------------------------------------------------------------------

@mcp.tool()
def list_projects(limit: int = 50) -> list[dict]:
    """List projects (folders) on the site.

    Args:
        limit: Max number of projects to return.
    """
    with _session() as server:
        projects = _paged(TSC.Pager(server.projects), limit)
        return [
            {"id": p.id, "name": p.name, "description": p.description, "parent_id": p.parent_id}
            for p in projects
        ]


# ---------------------------------------------------------------------------
# Tools — Workbooks
# ---------------------------------------------------------------------------

@mcp.tool()
def list_workbooks(limit: int = 50, name_filter: Optional[str] = None) -> list[dict]:
    """List workbooks on the site, optionally filtered by name substring.

    Args:
        limit: Max number of workbooks to return.
        name_filter: If provided, only workbooks whose name contains this
            (case-insensitive) are returned.
    """
    with _session() as server:
        workbooks = _paged(TSC.Pager(server.workbooks), max(limit * 5, limit) if name_filter else limit)
        results = []
        for wb in workbooks:
            if name_filter and name_filter.lower() not in wb.name.lower():
                continue
            results.append({
                "id": wb.id,
                "name": wb.name,
                "project_name": wb.project_name,
                "owner_id": wb.owner_id,
                "content_url": wb.content_url,
                "webpage_url": wb.webpage_url,
                "created_at": str(wb.created_at),
                "updated_at": str(wb.updated_at),
                "size_mb": wb.size,
            })
            if len(results) >= limit:
                break
        return results


@mcp.tool()
def get_workbook(workbook_id: str) -> dict:
    """Get full details for a single workbook, including its views.

    Args:
        workbook_id: The Tableau workbook LUID (from list_workbooks).
    """
    with _session() as server:
        wb = server.workbooks.get_by_id(workbook_id)
        server.workbooks.populate_views(wb)
        return {
            "id": wb.id,
            "name": wb.name,
            "project_name": wb.project_name,
            "webpage_url": wb.webpage_url,
            "tags": list(wb.tags),
            "views": [{"id": v.id, "name": v.name, "content_url": v.content_url} for v in wb.views],
        }


@mcp.tool()
def download_workbook(workbook_id: str, output_dir: str = "/tmp", include_extract: bool = False) -> dict:
    """Download a workbook (.twb/.twbx) to local disk.

    Args:
        workbook_id: The Tableau workbook LUID.
        output_dir: Directory to save the file into.
        include_extract: Whether to include embedded data extracts (larger file).
    """
    with _session() as server:
        os.makedirs(output_dir, exist_ok=True)
        path = server.workbooks.download(
            workbook_id, filepath=output_dir, include_extract=include_extract
        )
        return {"downloaded_path": path}


@mcp.tool()
def refresh_workbook_extract(workbook_id: str) -> dict:
    """Trigger an extract refresh for a workbook. Requires the workbook to
    have an extract-backed data source and refresh permissions.

    Args:
        workbook_id: The Tableau workbook LUID.
    """
    with _session() as server:
        wb = server.workbooks.get_by_id(workbook_id)
        job = server.workbooks.refresh(wb)
        return {"job_id": job.id, "status": job.status if hasattr(job, "status") else "queued"}


# ---------------------------------------------------------------------------
# Tools — Views
# ---------------------------------------------------------------------------

@mcp.tool()
def list_views(limit: int = 100, name_filter: Optional[str] = None) -> list[dict]:
    """List views (individual sheets/dashboards) across the site.

    Args:
        limit: Max number of views to return.
        name_filter: If provided, only views whose name contains this
            (case-insensitive) are returned.
    """
    with _session() as server:
        views = _paged(TSC.Pager(server.views), max(limit * 5, limit) if name_filter else limit)
        results = []
        for v in views:
            if name_filter and name_filter.lower() not in v.name.lower():
                continue
            results.append({
                "id": v.id,
                "name": v.name,
                "workbook_id": v.workbook_id,
                "content_url": v.content_url,
            })
            if len(results) >= limit:
                break
        return results


@mcp.tool()
def query_view_data(view_id: str, max_rows: int = 200) -> dict:
    """Fetch the underlying summary data for a view as CSV-parsed rows
    (equivalent to the 'Download Data' / Query View Data REST endpoint).

    Args:
        view_id: The Tableau view LUID (from list_views or get_workbook).
        max_rows: Cap on number of data rows returned (to avoid huge payloads).
    """
    with _session() as server:
        view = server.views.get_by_id(view_id)
        server.views.populate_csv(view)
        raw = b"".join(view.csv).decode("utf-8-sig")
        reader = csv.reader(io.StringIO(raw))
        rows = list(reader)
        header, data_rows = (rows[0], rows[1:]) if rows else ([], [])
        truncated = len(data_rows) > max_rows
        return {
            "columns": header,
            "rows": data_rows[:max_rows],
            "row_count_returned": min(len(data_rows), max_rows),
            "row_count_total": len(data_rows),
            "truncated": truncated,
        }


@mcp.tool()
def download_view_image(view_id: str, output_dir: str = "/tmp") -> dict:
    """Download a PNG image render of a view/dashboard.

    Args:
        view_id: The Tableau view LUID.
        output_dir: Directory to save the PNG into.
    """
    with _session() as server:
        view = server.views.get_by_id(view_id)
        server.views.populate_image(view)
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{view.name.replace(' ', '_')}.png")
        with open(path, "wb") as f:
            f.write(view.image)
        return {"saved_path": path}


@mcp.tool()
def download_view_pdf(view_id: str, output_dir: str = "/tmp") -> dict:
    """Download a PDF render of a view/dashboard.

    Args:
        view_id: The Tableau view LUID.
        output_dir: Directory to save the PDF into.
    """
    with _session() as server:
        view = server.views.get_by_id(view_id)
        server.views.populate_pdf(view)
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{view.name.replace(' ', '_')}.pdf")
        with open(path, "wb") as f:
            f.write(view.pdf)
        return {"saved_path": path}


# ---------------------------------------------------------------------------
# Tools — Data sources
# ---------------------------------------------------------------------------

@mcp.tool()
def list_datasources(limit: int = 50, name_filter: Optional[str] = None) -> list[dict]:
    """List published data sources on the site.

    Args:
        limit: Max number of data sources to return.
        name_filter: If provided, only data sources whose name contains this
            (case-insensitive) are returned.
    """
    with _session() as server:
        datasources = _paged(TSC.Pager(server.datasources), max(limit * 5, limit) if name_filter else limit)
        results = []
        for ds in datasources:
            if name_filter and name_filter.lower() not in ds.name.lower():
                continue
            results.append({
                "id": ds.id,
                "name": ds.name,
                "project_name": ds.project_name,
                "type": ds.datasource_type,
                "content_url": ds.content_url,
                "updated_at": str(ds.updated_at),
            })
            if len(results) >= limit:
                break
        return results


def _vds_post(server: TSC.Server, path: str, body: dict) -> dict:
    """POST to a VizQL Data Service (VDS) endpoint.

    VDS is a separate REST surface from the classic Tableau REST API that
    tableauserverclient wraps (/api/v1/vizql-data-service/...), but it's
    authenticated the same way: the X-Tableau-Auth token from a REST sign-in
    works for VDS calls too, so we reuse the active TSC session's token
    rather than signing in twice.
    """
    url = f"{SERVER_URL.rstrip('/')}/api/v1/vizql-data-service/{path.lstrip('/')}"
    headers = {
        "X-Tableau-Auth": server.auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.post(url, json=body, headers=headers, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"VDS request to {path} failed ({resp.status_code}): {resp.text[:2000]}")
    return resp.json()


@mcp.tool()
def get_datasource_metadata(datasource_id: str) -> dict:
    """Get field-level metadata (names, captions, data types, default
    aggregations, formulas) for a published data source via the VizQL Data
    Service. This is the modern replacement for the old 'list fields' tool —
    use this whenever you need to know what columns/fields a data source has
    before querying it.

    Args:
        datasource_id: The Tableau data source LUID (from list_datasources).
    """
    with _session() as server:
        body = {"datasource": {"datasourceLuid": datasource_id}}
        result = _vds_post(server, "read-metadata", body)
        return result


@mcp.tool()
def query_datasource(datasource_id: str, fields: list[dict], filters: Optional[list[dict]] = None,
                      limit: Optional[int] = None) -> dict:
    """Run a VizQL query against a published data source to answer business
    questions directly from the data (e.g. "top 5 states by sales"), via the
    VizQL Data Service. Use get_datasource_metadata first to discover valid
    field captions.

    Args:
        datasource_id: The Tableau data source LUID.
        fields: List of field specs, e.g.
            [{"fieldCaption": "Customer Name"},
             {"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "Total Sales",
              "sortDirection": "DESC", "sortPriority": 1}]
        filters: Optional list of filter specs. Examples:    
            Top N:
            {"field": {"fieldCaption": "Sub-Category"}, "filterType": "TOP",
             "howMany": 5, "direction": "TOP",
             "fieldToMeasure": {"fieldCaption": "Sales", "function": "SUM"}}

            Date range for any month, year, quarter or custom period.
            Use YYYY-MM-DD, with minDate = first day and maxDate = last day
            of the period the user asked for (28/29/30/31 days as the
            calendar requires, including leap years):
            {"field": {"fieldCaption": "<date field caption>"},
            "filterType": "QUANTITATIVE_DATE", "quantitativeFilterType": "RANGE",
            "minDate": "<YYYY-MM-DD>", "maxDate": "<YYYY-MM-DD>"}

            Examples of the mapping (not fixed values):
              "<Month> <Year>"  -> first to last day of that month
              "<Year>"          -> <Year>-01-01 to <Year>-12-31
              "Q<N> <Year>"     -> first to last day of that quarter
            Use the real date field caption from get_datasource_metadata
            (e.g. "Order Date" or "Ship Date"); if the user doesn't say
            which, use the order date.

            Relative date (e.g. the last 3 months):
            {"field": {"fieldCaption": "Order Date"}, "filterType": "DATE",
             "periodType": "MONTHS", "dateRangeType": "LASTN", "rangeN": 3}

            Specific values:
            {"field": {"fieldCaption": "Category"}, "filterType": "SET",
             "values": ["Furniture"], "exclude": false}

            Use the exact date field caption from get_datasource_metadata.
            Combine several filters by putting them all in the list.
        limit: Optional max number of rows to return.
    """
    with _session() as server:
        query: dict = {"fields": fields}
        if filters:
            query["filters"] = filters
        body: dict = {"datasource": {"datasourceLuid": datasource_id}, "query": query}
        options: dict = {"returnFormat": "OBJECTS"}
        if limit is not None:
            options["rowLimit"] = limit
        body["options"] = options
        result = _vds_post(server, "query-datasource", body)
        return result


@mcp.tool()
def refresh_datasource_extract(datasource_id: str) -> dict:
    """Trigger an extract refresh for a published data source.

    Args:
        datasource_id: The Tableau data source LUID.
    """
    with _session() as server:
        ds = server.datasources.get_by_id(datasource_id)
        job = server.datasources.refresh(ds)
        return {"job_id": job.id, "status": job.status if hasattr(job, "status") else "queued"}


# ---------------------------------------------------------------------------
# Tools — Jobs
# ---------------------------------------------------------------------------

@mcp.tool()
def get_job_status(job_id: str) -> dict:
    """Check the status of an async job (e.g. one started by a refresh call).

    Args:
        job_id: The job ID returned by refresh_workbook_extract or
            refresh_datasource_extract.
    """
    with _session() as server:
        job = server.jobs.get_by_id(job_id)
        return {
            "id": job.id,
            "type": job.type,
            "created_at": str(job.created_at),
            "started_at": str(job.started_at) if job.started_at else None,
            "completed_at": str(job.completed_at) if job.completed_at else None,
            "finish_code": job.finish_code,
            "notes": job.notes,
        }


# ---------------------------------------------------------------------------
# Tools — Users
# ---------------------------------------------------------------------------

@mcp.tool()
def list_users(limit: int = 50, name_filter: Optional[str] = None) -> list[dict]:
    """List users on the site.

    Args:
        limit: Max number of users to return.
        name_filter: If provided, only users whose name/email contains this
            (case-insensitive) are returned.
    """
    with _session() as server:
        users = _paged(TSC.Pager(server.users), max(limit * 5, limit) if name_filter else limit)
        results = []
        for u in users:
            haystack = f"{u.name} {u.fullname or ''} {u.email or ''}".lower()
            if name_filter and name_filter.lower() not in haystack:
                continue
            results.append({
                "id": u.id,
                "name": u.name,
                "fullname": u.fullname,
                "email": u.email,
                "site_role": u.site_role,
            })
            if len(results) >= limit:
                break
        return results


# ---------------------------------------------------------------------------
# Tools — Tableau Pulse (metric definitions + insights)
# ---------------------------------------------------------------------------
# Pulse is a Tableau Cloud feature exposed under /api/-/pulse/... It uses the
# same X-Tableau-Auth token as the rest of the REST API, so we reuse the PAT
# session from _session() exactly like the VizQL Data Service helper above.

_PULSE_GRANULARITY = {
    "day": "GRANULARITY_BY_DAY",
    "week": "GRANULARITY_BY_WEEK",
    "month": "GRANULARITY_BY_MONTH",
    "quarter": "GRANULARITY_BY_QUARTER",
    "year": "GRANULARITY_BY_YEAR",
}
_PULSE_COMPARISON = {
    "previous_period": "TIME_COMPARISON_PREVIOUS_PERIOD",
    "year_ago": "TIME_COMPARISON_YEAR_AGO_PERIOD",
}
_PULSE_RANGE = {
    "current_partial": "RANGE_CURRENT_PARTIAL",
    "last_complete": "RANGE_LAST_COMPLETE",
}
_PULSE_BUNDLE_TYPES = ("ban", "springboard", "detail")


def _pulse_request(server: TSC.Server, method: str, path: str,
                   params: Optional[dict] = None, body: Optional[dict] = None) -> dict:
    """Call a Tableau Pulse REST endpoint (/api/-/pulse/<path>)."""
    url = f"{SERVER_URL.rstrip('/')}/api/-/pulse/{path.lstrip('/')}"
    headers = {"X-Tableau-Auth": server.auth_token, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    resp = requests.request(method, url, params=params, json=body, headers=headers, timeout=90)
    if not resp.ok:
        raise RuntimeError(f"Pulse request {method} {path} failed ({resp.status_code}): {resp.text[:2000]}")
    return resp.json()


def _pulse_definitions(server: TSC.Server) -> list[dict]:
    """Fetch every metric definition on the site (follows pagination)."""
    definitions: list[dict] = []
    token = None
    for _ in range(10):  # safety cap: 10 pages
        params = {"view": "DEFINITION_VIEW_DEFAULT", "page_size": 100}
        if token:
            params["page_token"] = token
        data = _pulse_request(server, "GET", "definitions", params=params)
        definitions.extend(data.get("definitions", []))
        token = data.get("next_page_token")
        if not token:
            break
    return definitions


def _default_metric(server: TSC.Server, defn: dict) -> dict:
    """Return the definition's default metric (falls back to the first one)."""
    metrics = defn.get("metrics") or []
    if not metrics:  # some views omit metrics, so ask for them explicitly
        data = _pulse_request(server, "GET", f"definitions/{defn['metadata']['id']}/metrics")
        metrics = data.get("metrics", [])
    if not metrics:
        raise RuntimeError(f"Definition '{defn['metadata']['name']}' has no metrics.")
    return next((m for m in metrics if m.get("is_default")), metrics[0])


def _build_bundle_request(defn: dict, metric: dict, granularity: Optional[str],
                          comparison: Optional[str], period: Optional[str]) -> dict:
    """Build the insight-bundle request body from a stored definition + metric."""
    spec = defn["specification"]
    stored = metric.get("specification", {})
    stored_period = stored.get("measurement_period", {})

    measurement_period = {
        "granularity": _PULSE_GRANULARITY[granularity] if granularity else stored_period.get(
            "granularity", "GRANULARITY_BY_MONTH"),
        "range": _PULSE_RANGE[period] if period else stored_period.get("range", "RANGE_CURRENT_PARTIAL"),
    }
    comparison_value = (
        _PULSE_COMPARISON[comparison] if comparison
        else stored.get("comparison", {}).get("comparison", "TIME_COMPARISON_PREVIOUS_PERIOD")
    )

    rep = defn.get("representation_options", {})
    representation = {"type": rep.get("type", "NUMBER_FORMAT_TYPE_NUMBER")}
    if rep.get("number_units"):
        representation["number_units"] = rep["number_units"]
    if rep.get("sentiment_type"):
        representation["sentiment_type"] = rep["sentiment_type"]
    if rep.get("currency_code") and rep["currency_code"] != "CURRENCY_CODE_UNSPECIFIED":
        representation["currency_code"] = rep["currency_code"]

    return {
        "bundle_request": {
            "version": 1,
            "options": {
                "output_format": "OUTPUT_FORMAT_TEXT",
                "time_zone": "UTC",
                "language": "LANGUAGE_EN_US",
                "locale": "LOCALE_EN_US",
            },
            "input": {
                "metadata": {
                    "name": defn["metadata"]["name"],
                    "metric_id": metric["id"],
                    "definition_id": defn["metadata"]["id"],
                },
                "metric": {
                    "definition": {
                        "datasource": {"id": spec["datasource"]["id"]},
                        "basic_specification": spec["basic_specification"],
                        "is_running_total": spec.get("is_running_total", False),
                    },
                    "metric_specification": {
                        "filters": stored.get("filters", []),
                        "measurement_period": measurement_period,
                        "comparison": {"comparison": comparison_value},
                    },
                    "extension_options": defn.get("extension_options", {}),
                    "representation_options": representation,
                    "insights_options": defn.get("insights_options", {}),
                },
            },
        }
    }


def _summarise_bundle(bundle: dict, max_per_group: int = 12) -> list[dict]:
    """Reduce a (potentially 200 KB) insight bundle to readable text per group."""
    result = bundle.get("bundle_response", {}).get("result", {})
    seen: set[str] = set()
    groups = []
    for group in result.get("insight_groups", []):
        items = []
        for ins in group.get("insights", []):
            r = ins.get("result", {})
            text = (r.get("markup") or r.get("content") or "").strip()
            if not text or text in seen:  # 'followup' repeats the 'breakdown' group
                continue
            seen.add(text)
            items.append({"type": r.get("type"), "text": text})
            if len(items) >= max_per_group:
                break
        if items:
            groups.append({"group": group.get("type"), "insights": items})
    return groups


@mcp.tool()
def list_pulse_metrics() -> list[dict]:
    """List all Tableau Pulse metric definitions on the site (Tableau Cloud only).

    Returns each metric's name, description, data source, measure, aggregation,
    allowed breakdown dimensions and time granularities. Use this to find the
    exact metric name before calling get_pulse_insights. If two definitions
    share a name, prefer passing definition_id to get_pulse_insights.
    """
    with _session() as server:
        out = []
        for d in _pulse_definitions(server):
            spec = d.get("specification", {})
            basic = spec.get("basic_specification", {})
            ext = d.get("extension_options", {})
            metrics = d.get("metrics") or []
            default = next((m for m in metrics if m.get("is_default")), metrics[0] if metrics else {})
            out.append({
                "definition_id": d["metadata"]["id"],
                "name": d["metadata"]["name"],
                "description": d["metadata"].get("description", ""),
                "datasource_id": spec.get("datasource", {}).get("id"),
                "measure": basic.get("measure", {}).get("field"),
                "aggregation": basic.get("measure", {}).get("aggregation"),
                "time_dimension": basic.get("time_dimension", {}).get("field"),
                "allowed_dimensions": ext.get("allowed_dimensions", []),
                "allowed_granularities": ext.get("allowed_granularities", []),
                "default_metric_id": default.get("id"),
            })
        return out


@mcp.tool()
def get_pulse_insights(metric_name: Optional[str] = None, definition_id: Optional[str] = None,
                       bundle_type: str = "ban", granularity: Optional[str] = None,
                       comparison: Optional[str] = None, period: Optional[str] = None) -> dict:
    """Get Tableau Pulse insights for a metric: current value, change vs a
    comparison period, top/bottom contributors, trend and unusual-change
    insights. Use this for questions like "how is Total Sales doing?" or
    "why did profit ratio change?". For a month-by-month time series, use
    query_datasource instead (the response includes datasource_id).

    Args:
        metric_name: Metric definition name, e.g. "Total Sales" (case-insensitive).
            Ignored when definition_id is given.
        definition_id: Exact metric definition id (from list_pulse_metrics).
        bundle_type: "ban" (current value + change + top insight per dimension,
            default), "springboard" (value + change + top insight) or "detail"
            (also trend, contributors and follow-ups; larger).
        granularity: "day", "week", "month", "quarter" or "year". Defaults to the
            metric's own default. Must be allowed by the definition.
        comparison: "previous_period" or "year_ago" (year-over-year). Defaults
            to the metric's own default.
        period: "current_partial" (period to date) or "last_complete".
    """
    if bundle_type not in _PULSE_BUNDLE_TYPES:
        raise ValueError(f"bundle_type must be one of {_PULSE_BUNDLE_TYPES}")
    for value, allowed, label in ((granularity, _PULSE_GRANULARITY, "granularity"),
                                  (comparison, _PULSE_COMPARISON, "comparison"),
                                  (period, _PULSE_RANGE, "period")):
        if value and value not in allowed:
            raise ValueError(f"{label} must be one of {sorted(allowed)}")
    if not metric_name and not definition_id:
        raise ValueError("Provide metric_name or definition_id.")

    with _session() as server:
        definitions = _pulse_definitions(server)
        if definition_id:
            matches = [d for d in definitions if d["metadata"]["id"].lower() == definition_id.lower()]
        else:
            matches = [d for d in definitions if d["metadata"]["name"].lower() == metric_name.lower()]
        if not matches:
            names = sorted({d["metadata"]["name"] for d in definitions})
            raise ValueError(f"No Pulse metric found. Available metrics: {names}")

        defn = matches[0]
        metric = _default_metric(server, defn)
        body = _build_bundle_request(defn, metric, granularity, comparison, period)
        bundle = _pulse_request(server, "POST", f"insights/{bundle_type}", body=body)

        used = body["bundle_request"]["input"]["metric"]["metric_specification"]
        note = None
        if len(matches) > 1:
            note = (f"{len(matches)} definitions are named '{defn['metadata']['name']}'; used the first. "
                    "Pass definition_id (see list_pulse_metrics) to choose.")
        return {
            "metric": defn["metadata"]["name"],
            "definition_id": defn["metadata"]["id"],
            "datasource_id": defn["specification"]["datasource"]["id"],
            "bundle_type": bundle_type,
            "granularity": used["measurement_period"]["granularity"],
            "period": used["measurement_period"]["range"],
            "comparison": used["comparison"]["comparison"],
            "insights": _summarise_bundle(bundle),
            "note": note,
        }


if __name__ == "__main__":
    mcp.run()
