"""Read access to the lake for MCP tools (ADR 039).

One DuckDB process-wide connection attaches the lake READ_ONLY and is then locked down:
no file or network access outside the lake's data path, no Python replacement scans,
configuration locked. Every tool call works on its own cursor, where the views the
caller may read are created as temporary views that already exclude the entities their
policy denies; queries can only name those views (``xomtra_mcp.sqlguard``).
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

import duckdb

from hacore.lake import LAKE_ALIAS, LakeSettings, connect, connect_local, sql_literal
from xomtra_mcp import sqlguard
from xomtra_mcp.policy import Access

logger = logging.getLogger(__name__)

type Row = dict[str, Any]
Resolution = Literal["auto", "raw", "5minute", "hour", "day"]


@dataclass(frozen=True, slots=True)
class View:
    name: str
    source: str  # relative to the lake alias
    entity_columns: tuple[str, ...]  # a row is hidden if any of them is a denied entity
    description: str
    # Lists of entity ids: denied entities are removed from them (the row stays).
    entity_lists: tuple[str, ...] = ()


VIEWS: dict[str, View] = {
    v.name: v
    for v in (
        View(
            "entities",
            "silver.entities",
            ("entity_id",),
            "Current entities: name, domain, device, area, floor, labels, unit, "
            "device_class, state_class, flags.",
        ),
        View(
            "states",
            "silver.states",
            ("entity_id",),
            "Every state change: entity_id, state (text), state_value (number or NULL), "
            "is_missing, attributes (JSON; hidden for some roles), last_changed, "
            "last_updated (UTC).",
        ),
        View(
            "statistics",
            "silver.statistics",
            ("statistic_id",),
            "Home Assistant long-term statistics per period ('5minute', 'hour'): "
            "mean/min/max for measurements, state/sum for counters; period_start in UTC.",
        ),
        View(
            "statistics_meta",
            "silver.statistics_meta",
            ("statistic_id",),
            "Statistics metadata: unit the values are stored in, has_mean, has_sum.",
        ),
        View(
            "catalog_entity",
            "catalog.entity",
            ("entity_id",),
            "Entity catalog with a profile of the last 30 days: kind, changes per day, "
            "numeric/missing share, value quantiles, top states, stale, range_shift.",
        ),
        View(
            "catalog_drift",
            "catalog.drift",
            ("entity_id",),
            "Changes between daily catalog profiles: new/removed entities, metadata "
            "changes, stopped/resumed reporting, range shifts.",
        ),
        View(
            "catalog_finding",
            "catalog.finding",
            ("entity_id", "related_entity_id"),
            "Findings of the daily analysis (prefer the get_findings tool). finding_type "
            "'correlation': entity_id (metric mean/delta/share of state) leads "
            "related_entity_id by lag_hours; score = correlation of hourly residuals after "
            "the daily/weekly cycle and the outside temperature; q_value = FDR. "
            "'anomaly': unusual hours period_start..period_end of one entity; score = peak "
            "robust z against the same hour of the week, observed/expected = mean value, "
            "n_eff = anomalous hours. 'change_point': lasting level shift from period_start; "
            "score = shift in robust deviations, observed/expected = level after/before. "
            "flags (trivial or explained findings): duplicate_suspect, same_device, short, "
            "weather, level_shift, common_factor (shared or hidden driver), indirect "
            "(explained by the series in explained_by), same_area (both in one HA area), "
            "house_context (explained by the residents' presence), "
            "dismissed (an admin chose not to see it), "
            "unstable (does not replicate in "
            "both halves of the window), trivial (expected relation, code in trivial_rule: "
            "T1 one device, T2 one quantity twice, T3 helper and source, T4 one quantity "
            "twice in one area, T5 known physics, T6 collection artefact); p_value = "
            "calibrated p-value of the pair; usefulness = R0 = sqrt(strength * evidence) "
            "in [0, 1] (strength of the effect, evidence from q_value); action_category = "
            "fault, savings, automation, behaviour, none or unclassified (public "
            "rulebook, rules_version); rank 1 = most useful within type and window "
            "(unflagged first; ranking_version). Provenance: analyzer (correlations or "
            "anomalies), pack and pack_version (parameter pack, here home), source_instance "
            "(data source instance, here ha); NULL in rows written by earlier versions.",
            ("entity_group", "related_group", "explained_by"),
        ),
        View(
            "catalog_finding_weekly",
            "catalog.finding_weekly",
            ("entity_id", "related_entity_id"),
            "Weekly snapshots of catalog_finding (prefer get_weekly_summary): week_start = "
            "local Monday of the summarised week, snapshot_at, then the finding columns.",
            ("entity_group", "related_group", "explained_by"),
        ),
    )
}
KNOWN_VIEWS = frozenset(VIEWS)

SEARCH_COLUMNS = (
    "entity_id, name, domain, area_name, floor_name, device_name, manufacturer, model, "
    "unit_of_measurement, device_class, state_class, kind, changes_per_day, last_seen, "
    "stale"
)
# Errors whose message helps the caller fix the query; others are reported generically.
_USER_ERRORS = (
    duckdb.ParserException,
    duckdb.BinderException,
    duckdb.CatalogException,
    duckdb.ConversionException,
    duckdb.InvalidInputException,
    duckdb.OutOfRangeException,
    duckdb.InterruptException,
)


# A new installation builds its catalog with the first run of the daily catalog job.
CATALOG_NOT_READY = (
    "The catalog is not built yet: a new installation builds it with the daily catalog "
    "job (04:15 in the installation's time zone), after the history from Home Assistant "
    "has loaded. Until then the entities are not searchable here; the administrator can "
    "build it now with `xomtra-ingest catalog` in the container dagster-daemon. Raw "
    "data may already be in the views of list_views."
)


class QueryFailed(RuntimeError):  # noqa: N818 - message is shown to the caller
    """A query failed; the message is safe to show to the caller."""


def jsonable(value: Any) -> Any:  # noqa: PLR0911 - one return per type
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def parse_time(value: str | None, *, now: datetime | None = None) -> datetime:
    """ISO date/time (UTC if no offset) or relative ``<n>d`` / ``<n>h`` before now."""
    now = now or datetime.now(UTC)
    if not value:
        return now
    v = value.strip().lower()
    if v[:-1].isdigit() and v[-1] in "dh":
        n = int(v[:-1])
        return now - (timedelta(days=n) if v[-1] == "d" else timedelta(hours=n))
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as err:
        raise ValueError(f"Invalid time {value!r}: use ISO 8601 or e.g. '7d', '12h'") from err
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class DataAccess:
    """Lake queries for MCP tools, always under a caller's :class:`Access`."""

    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        *,
        timezone: str = "UTC",
        query_timeout: float = 30.0,
    ) -> None:
        self._con = con
        self.timezone = timezone
        self.query_timeout = query_timeout

    @classmethod
    def from_settings(
        cls, settings: LakeSettings, *, timezone: str = "UTC", query_timeout: float = 30.0
    ) -> DataAccess:
        con = connect(settings, read_only=True)
        lockdown(con, [settings.data_path])
        return cls(con, timezone=timezone, query_timeout=query_timeout)

    @classmethod
    def local(
        cls, catalog: str, data_path: str, *, extension_dir: str | None = None, **kwargs: Any
    ) -> DataAccess:
        con = connect_local(catalog, data_path, extension_dir=extension_dir, read_only=True)
        lockdown(con, [data_path])
        return cls(con, **kwargs)

    def close(self) -> None:
        self._con.close()

    @contextmanager
    def trusted_cursor(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Cursor on the whole (read-only, locked-down) lake for fixed internal SQL of the
        admin GUI. Never pass user SQL here; that goes through :meth:`query_sql`."""
        cur = self._con.cursor()
        try:
            yield cur
        finally:
            cur.close()

    # ---- per-call cursor -----------------------------------------------------------

    @contextmanager
    def _cursor(self, access: Access) -> Iterator[duckdb.DuckDBPyConnection]:
        cur = self._con.cursor()
        try:
            deny = " OR ".join(f"{{col}} GLOB {sql_literal(p)}" for p in access.deny_entities)
            # A fresh installation has no silver or catalog yet: skip what does not exist.
            existing = {
                r[0]
                for r in cur.execute(
                    "SELECT schema_name || '.' || table_name FROM duckdb_tables() "
                    "WHERE database_name = $db UNION ALL "
                    "SELECT schema_name || '.' || view_name FROM duckdb_views() "
                    "WHERE database_name = $db",
                    {"db": LAKE_ALIAS},
                ).fetchall()
            }
            columns: dict[str, set[str]] = {}
            for table, column in cur.execute(
                "SELECT schema_name || '.' || table_name, column_name FROM duckdb_columns() "
                "WHERE database_name = $db",
                {"db": LAKE_ALIAS},
            ).fetchall():
                columns.setdefault(table, set()).add(column)
            for view in VIEWS.values():
                if view.source not in existing:
                    continue
                hidden_rows = " OR ".join(
                    f"coalesce({deny.format(col=col)}, FALSE)" for col in view.entity_columns
                )
                where = f" WHERE NOT ({hidden_rows})" if deny else ""
                hidden = access.columns_hidden_in(view.name)
                exclude = f" EXCLUDE ({', '.join(hidden)})" if hidden else ""
                # A list column added in a later release may be missing until the
                # ingest service has upgraded the table.
                lists = [
                    c
                    for c in view.entity_lists
                    if c not in hidden and c in columns.get(view.source, {c})
                ]
                replace = (
                    " REPLACE ("
                    + ", ".join(
                        f"list_filter({c}, lambda x: NOT coalesce({deny.format(col='x')}, "
                        f"FALSE)) AS {c}"
                        for c in lists
                    )
                    + ")"
                    if deny and lists
                    else ""
                )
                cur.execute(
                    f"CREATE TEMP VIEW {view.name} AS "
                    f"SELECT *{exclude}{replace} FROM {LAKE_ALIAS}.{view.source}{where}"
                )
            yield cur
        finally:
            cur.close()

    def _timed[T](self, cur: duckdb.DuckDBPyConnection, fn: Callable[[], T]) -> T:
        timer = threading.Timer(self.query_timeout, cur.interrupt)
        timer.start()
        try:
            return fn()
        except duckdb.InterruptException as err:
            raise QueryFailed(f"Query cancelled after {self.query_timeout:g} s") from err
        except _USER_ERRORS as err:
            raise QueryFailed(str(err).splitlines()[0]) from err
        except duckdb.Error as err:
            logger.warning("Query failed: %s", err)
            raise QueryFailed("Query failed") from err
        finally:
            timer.cancel()

    @staticmethod
    def _rows(cur: duckdb.DuckDBPyConnection, limit: int | None = None) -> list[Row]:
        cols = [d[0] for d in cur.description or []]
        data = cur.fetchmany(limit) if limit is not None else cur.fetchall()
        return [{c: jsonable(v) for c, v in zip(cols, r, strict=True)} for r in data]

    @staticmethod
    def _has_view(cur: duckdb.DuckDBPyConnection, name: str) -> bool:
        """Whether :meth:`_cursor` created the view (its lake table exists)."""
        return (
            cur.execute(
                "SELECT 1 FROM duckdb_views() WHERE temporary AND view_name = ?", [name]
            ).fetchone()
            is not None
        )

    # ---- tools ---------------------------------------------------------------------

    def list_views(self, access: Access) -> list[Row]:
        out = []
        with self._cursor(access) as cur:
            for name in access.allowed_views:
                try:
                    cols = cur.execute(f"DESCRIBE {name}").fetchall()
                except duckdb.CatalogException:
                    continue  # not created yet (fresh installation)
                out.append(
                    {
                        "name": name,
                        "description": VIEWS[name].description,
                        "columns": [{"name": c[0], "type": c[1]} for c in cols],
                    }
                )
        return out

    def search_catalog(
        self,
        access: Access,
        *,
        query: str = "",
        domain: str | None = None,
        area: str | None = None,
        kind: str | None = None,
        include_disabled: bool = False,
        limit: int = 50,
    ) -> Row:
        limit = max(1, min(limit, access.max_rows, 500))
        where = ["TRUE"]
        params: list[Any] = []
        haystack = (
            "lower(concat_ws(' ', entity_id, name, area_name, floor_name, device_name, "
            "manufacturer, model, device_class, unit_of_measurement, kind))"
        )
        for token in query.lower().split()[:10]:
            where.append(f"contains({haystack}, ?)")
            params.append(token)
        if domain:
            where.append("domain = ?")
            params.append(domain)
        if area:
            where.append("(lower(area_name) = lower(?) OR lower(floor_name) = lower(?))")
            params += [area, area]
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if not include_disabled:
            where.append("NOT coalesce(disabled, FALSE)")
        sql = (
            f"SELECT {SEARCH_COLUMNS} FROM catalog_entity WHERE {' AND '.join(where)} "
            f"ORDER BY changes_per_day DESC NULLS LAST, entity_id LIMIT {limit + 1}"
        )
        with self._cursor(access) as cur:
            if not self._has_view(cur, "catalog_entity"):
                return {
                    "entities": [],
                    "row_count": 0,
                    "truncated": False,
                    "note": CATALOG_NOT_READY,
                }
            rows = self._timed(cur, lambda: self._rows(cur.execute(sql, params)))
        return {
            "entities": rows[:limit],
            "row_count": min(len(rows), limit),
            "truncated": len(rows) > limit,
        }

    def describe_entity(self, access: Access, entity_id: str) -> Row:
        access.require_entity(entity_id)
        with self._cursor(access) as cur:
            if not self._has_view(cur, "catalog_entity"):
                raise QueryFailed(CATALOG_NOT_READY)

            def run() -> Row:
                cur.execute("SELECT * FROM catalog_entity WHERE entity_id = ?", [entity_id])
                found = self._rows(cur)
                if not found:
                    raise QueryFailed(f"Entity {entity_id} is not in the catalog")
                entity = found[0]
                cur.execute(
                    "SELECT state, state_value, last_changed, last_updated FROM states "
                    "WHERE entity_id = ? AND last_updated >= now() - INTERVAL 30 DAY "
                    "ORDER BY last_updated DESC LIMIT 1",
                    [entity_id],
                )
                latest = self._rows(cur)
                cur.execute(
                    "SELECT detected_at, drift_type, field, old_value, new_value "
                    "FROM catalog_drift WHERE entity_id = ? ORDER BY detected_at DESC LIMIT 20",
                    [entity_id],
                )
                drift = self._rows(cur)
                cur.execute("SELECT * FROM statistics_meta WHERE statistic_id = ?", [entity_id])
                stats = self._rows(cur)
                return {
                    "entity": entity,
                    "latest_state": latest[0] if latest else None,
                    "statistics": stats[0] if stats else None,
                    "drift": drift,
                    "row_count": 1,
                }

            return self._timed(cur, run)

    def get_timeseries(
        self,
        access: Access,
        entity_id: str,
        *,
        start: datetime,
        end: datetime,
        resolution: Resolution = "auto",
    ) -> Row:
        access.require_entity(entity_id)
        access.require_view("states")
        if end <= start:
            raise ValueError("end must be after start")
        span = end - start
        if resolution == "auto":
            if span <= timedelta(days=2):
                resolution = "raw"
            elif span <= timedelta(days=31):
                resolution = "hour"
            else:
                resolution = "day"
        limit = access.max_rows
        with self._cursor(access) as cur:

            def run() -> Row:
                has_stats = False
                if resolution != "raw" and access.can_view("statistics"):
                    period = "5minute" if resolution == "5minute" else "hour"
                    found = cur.execute(
                        "SELECT count(*) FROM statistics WHERE statistic_id = ? "
                        "AND period = ? AND period_start >= ? AND period_start < ?",
                        [entity_id, period, start, end],
                    ).fetchone()
                    has_stats = bool(found and found[0])
                if has_stats:
                    source, sql, params = self._statistics_sql(entity_id, resolution, start, end)
                else:
                    source, sql, params = self._states_sql(entity_id, resolution, start, end)
                cur.execute(sql, params)
                points = self._rows(cur, limit + 1)
                return {
                    "entity_id": entity_id,
                    "source": source,
                    "resolution": resolution,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "timezone": self.timezone if resolution == "day" else "UTC",
                    "points": points[:limit],
                    "row_count": min(len(points), limit),
                    "truncated": len(points) > limit,
                }

            return self._timed(cur, run)

    def _bucket(self, resolution: str, column: str) -> str:
        if resolution == "day":
            tz = sql_literal(self.timezone)
            return f"timezone({tz}, date_trunc('day', timezone({tz}, {column})))"
        interval = {"5minute": "5 minutes", "hour": "1 hour"}[resolution]
        return f"time_bucket(INTERVAL '{interval}', {column})"

    def _statistics_sql(
        self, entity_id: str, resolution: str, start: datetime, end: datetime
    ) -> tuple[str, str, list[Any]]:
        period = "5minute" if resolution == "5minute" else "hour"
        bucket = self._bucket(resolution, "period_start")
        sql = (
            f"SELECT {bucket} AS t, avg(mean) AS mean, min(min) AS min, max(max) AS max, "
            "arg_max(state, period_start) AS state, arg_max(sum, period_start) AS sum "
            "FROM statistics WHERE statistic_id = ? AND period = ? "
            "AND period_start >= ? AND period_start < ? GROUP BY ALL ORDER BY t"
        )
        return f"statistics:{period}", sql, [entity_id, period, start, end]

    def _states_sql(
        self, entity_id: str, resolution: str, start: datetime, end: datetime
    ) -> tuple[str, str, list[Any]]:
        if resolution == "raw":
            sql = (
                "SELECT last_updated AS t, state, state_value AS value FROM states "
                "WHERE entity_id = ? AND last_updated >= ? AND last_updated < ? "
                "ORDER BY last_updated"
            )
        else:
            bucket = self._bucket(resolution, "last_updated")
            sql = (
                f"SELECT {bucket} AS t, avg(state_value) AS mean, min(state_value) AS min, "
                "max(state_value) AS max, arg_max(state, last_updated) AS last_state, "
                "count(*) AS changes FROM states "
                "WHERE entity_id = ? AND last_updated >= ? AND last_updated < ? "
                "GROUP BY ALL ORDER BY t"
            )
        return "states", sql, [entity_id, start, end]

    def query_sql(self, access: Access, sql: str) -> Row:
        allowed = frozenset(access.allowed_views)
        guarded = sqlguard.check(sql, allowed, max_rows=access.max_rows)
        with self._cursor(access) as cur:
            started = time.monotonic()

            def run() -> tuple[list[str], list[Row]]:
                cur.execute(guarded.sql)
                cols = [d[0] for d in cur.description or []]
                return cols, self._rows(cur, access.max_rows + 1)

            columns, rows = self._timed(cur, run)
        return {
            "columns": columns,
            "rows": rows[: access.max_rows],
            "row_count": min(len(rows), access.max_rows),
            "truncated": len(rows) > access.max_rows,
            "views": sorted(guarded.views),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }

    # ---- findings (ADR 047, 048) ---------------------------------------------------

    def _finding_select(
        self, access: Access, source: str, extra: str = "", *, names: bool = True
    ) -> str:
        """Finding columns with entity names when the role may read the catalog."""
        cols = extra + (
            "f.finding_type, f.window_days, f.rank, f.entity_id, f.metric, f.state, "
            "f.related_entity_id, f.related_metric, f.related_state, f.lag_hours, f.score, "
            "f.q_value, f.p_value, f.n_eff, f.observed, f.expected, f.flags, f.explained_by, "
            "f.entity_group, f.usefulness, f.action_category, f.trivial_rule, "
            "coalesce(f.hidden, len(coalesce(f.flags, [])) > 0) AS hidden, "
            "f.related_group, f.period_start, f.period_end, f.first_detected_at, "
            "f.detected_at, f.finding_id"
        )
        if not (names and access.can_view("catalog_entity")):
            return f"SELECT {cols} FROM {source} AS f"
        return (
            f"SELECT {cols}, e.name AS entity_name, e.area_name AS entity_area, "
            "e.unit_of_measurement AS unit, r.name AS related_name, "
            "r.area_name AS related_area, r.unit_of_measurement AS related_unit "
            f"FROM {source} AS f "
            "LEFT JOIN catalog_entity AS e ON e.entity_id = f.entity_id "
            "LEFT JOIN catalog_entity AS r ON r.entity_id = f.related_entity_id"
        )

    @staticmethod
    def _compact(row: Row) -> Row:
        """Drop empty values: a finding of one type leaves the other types' columns
        empty, and the caller reads fewer tokens."""
        return {k: v for k, v in row.items() if v not in (None, []) and k != "hidden"}

    def get_findings(
        self,
        access: Access,
        *,
        finding_type: str | None = None,
        entity_id: str | None = None,
        window_days: int | None = None,
        include_flagged: bool = False,
        new_since: datetime | None = None,
        limit: int = 20,
    ) -> Row:
        access.require_view("catalog_finding")
        if entity_id:
            access.require_entity(entity_id)
        limit = max(1, min(limit, access.max_rows, 200))
        where = ["TRUE"]
        params: list[Any] = []
        if finding_type:
            where.append("f.finding_type = ?")
            params.append(finding_type)
        if entity_id:
            where.append(
                "(f.entity_id = ? OR f.related_entity_id = ? "
                "OR list_contains(f.entity_group, ?) OR list_contains(f.related_group, ?))"
            )
            params += [entity_id] * 4
        if window_days:
            where.append("f.window_days = ?")
            params.append(window_days)
        if new_since:
            where.append("f.first_detected_at >= ?")
            params.append(new_since)
        flagged = "coalesce(f.hidden, len(coalesce(f.flags, [])) > 0)"
        base = f"FROM catalog_finding AS f WHERE {' AND '.join(where)}"
        order = (
            "ORDER BY CASE finding_type WHEN 'anomaly' THEN 0 WHEN 'change_point' THEN 1 "
            "ELSE 2 END, window_days, rank"
        )
        show = "TRUE" if include_flagged else f"NOT ({flagged})"
        with self._cursor(access) as cur:
            if not self._has_view(cur, "catalog_finding"):
                return {
                    "findings": [],
                    "row_count": 0,
                    "truncated": False,
                    "counts": {},
                    "flagged_hidden": not include_flagged,
                    "methods": [],
                    "confidence": [],
                    "note": CATALOG_NOT_READY,
                }
            select = self._finding_select(
                access, "catalog_finding", names=self._has_view(cur, "catalog_entity")
            )
            sql = (
                f"SELECT * FROM ({select}) AS f "
                f"WHERE {' AND '.join(where)} AND {show} {order} LIMIT {limit + 1}"
            )

            def run() -> Row:
                counts = cur.execute(
                    f"SELECT f.finding_type, count(*) AS total, "
                    f"count(*) FILTER (WHERE {flagged}) AS flagged {base} GROUP BY ALL "
                    "ORDER BY 1",
                    params,
                ).fetchall()
                methods = cur.execute(
                    "SELECT DISTINCT f.finding_type, f.window_days, f.method, "
                    f"f.ranking_version {base} ORDER BY 1, 2",
                    params,
                ).fetchall()
                rows = self._rows(cur.execute(sql, params))
                return {
                    "findings": [self._compact(r) for r in rows[:limit]],
                    "row_count": min(len(rows), limit),
                    "truncated": len(rows) > limit,
                    "counts": {
                        str(t): {"total": int(n), "flagged": int(fl)} for t, n, fl in counts
                    },
                    "flagged_hidden": not include_flagged,
                    "methods": [
                        self._compact(
                            {"finding_type": t, "window_days": w, "method": m, "ranking": r}
                        )
                        for t, w, m, r in methods
                    ],
                    "confidence": self._run_confidence(),
                }

            return self._timed(cur, run)

    def _run_confidence(self) -> list[Row]:
        """Confidence of the last correlation runs (ADR 067): aggregate counts only, so
        every reader may see it; read with the trusted cursor (no view)."""
        with self.trusted_cursor() as cur:
            try:
                rows = cur.execute(
                    "SELECT window_days, confidence, reasons, series, entities, "
                    "group_coverage FROM lake.catalog.analysis_run "
                    "WHERE finding_type = 'correlation' ORDER BY window_days DESC"
                ).fetchall()
            except duckdb.Error:
                return []  # no run table yet (before the first run of 0.5)
        return [
            {
                "window_days": w,
                "level": level,
                "reasons": list(reasons or []),
                "series": series,
                "entities": entities,
                "group_coverage": coverage,
                "note": (
                    "low power: treat the correlations as hypotheses; complete the HA "
                    "areas to raise it"
                    if level == "low"
                    else None
                ),
            }
            for w, level, reasons, series, entities, coverage in rows
        ]

    def get_weekly_summary(self, access: Access, *, week: date | None = None, top: int = 10) -> Row:
        access.require_view("catalog_finding_weekly")
        top = max(1, min(top, 50))
        tz = ZoneInfo(self.timezone)
        with self._cursor(access) as cur:

            def run() -> Row:
                try:
                    weeks = [
                        r[0]
                        for r in cur.execute(
                            "SELECT DISTINCT week_start FROM catalog_finding_weekly ORDER BY 1 DESC"
                        ).fetchall()
                    ]
                except duckdb.CatalogException:
                    weeks = []
                if not weeks:
                    return {"week_start": None, "note": "No weekly snapshot yet"}
                chosen = (
                    weeks[0]
                    if week is None
                    else next((w for w in weeks if w <= week < w + timedelta(days=7)), None)
                )
                if chosen is None:
                    raise QueryFailed(
                        f"No snapshot for the week of {week}; available weeks: "
                        + ", ".join(w.isoformat() for w in weeks[:12])
                    )
                previous = next((w for w in weeks if w < chosen), None)
                select = self._finding_select(
                    access,
                    "catalog_finding_weekly",
                    extra="f.week_start, ",
                    names=self._has_view(cur, "catalog_entity"),
                )
                cur.execute(
                    f"SELECT * FROM ({select}) WHERE week_start IN (?, ?)", [chosen, previous]
                )
                rows = self._rows(cur)
                return _summarise(rows, chosen, previous, tz, top)

            return self._timed(cur, run)


def _is_trivial(row: Row) -> bool:
    hidden = row.get("hidden")
    return bool(row.get("flags")) if hidden is None else bool(hidden)


def _summarise(rows: list[Row], week: date, previous: date | None, tz: ZoneInfo, top: int) -> Row:
    """Sections of a weekly summary from the rows of two snapshots."""
    current = [r for r in rows if r["week_start"] == week.isoformat()]
    before = [r for r in rows if previous and r["week_start"] == previous.isoformat()]
    start = datetime.combine(week, datetime.min.time(), tz).astimezone(UTC)
    end = start + timedelta(days=7)

    def in_week(r: Row) -> bool:
        ps = r.get("period_start")
        return ps is not None and start <= datetime.fromisoformat(ps) < end

    def strongest(items: list[Row]) -> list[Row]:
        ranked = sorted(
            items,
            key=lambda r: (-float(r.get("usefulness") or 0), -abs(float(r.get("score") or 0))),
        )
        return [
            {
                k: v
                for k, v in r.items()
                if v not in (None, []) and k not in {"week_start", "hidden"}
            }
            for r in ranked[:top]
        ]

    corr_now = {r["finding_id"]: r for r in current if r["finding_type"] == "correlation"}
    corr_before = {r["finding_id"]: r for r in before if r["finding_type"] == "correlation"}
    counts: dict[str, dict[str, int]] = {}
    for r in current:
        c = counts.setdefault(r["finding_type"], {"total": 0, "flagged": 0})
        c["total"] += 1
        c["flagged"] += int(_is_trivial(r))
    return {
        "week_start": week.isoformat(),
        "week_end": (week + timedelta(days=6)).isoformat(),
        "compared_with": previous.isoformat() if previous else None,
        "counts": counts,
        "anomalies": strongest(
            [
                r
                for r in current
                if r["finding_type"] == "anomaly" and in_week(r) and not _is_trivial(r)
            ]
        ),
        "change_points": strongest(
            [
                r
                for r in current
                if r["finding_type"] == "change_point" and in_week(r) and not _is_trivial(r)
            ]
        ),
        "new_correlations": strongest(
            [r for i, r in corr_now.items() if i not in corr_before and not _is_trivial(r)]
            if previous
            else []
        ),
        "gone_correlations": strongest(
            [r for i, r in corr_before.items() if i not in corr_now and not _is_trivial(r)]
        ),
        "note": "Flagged (trivial or explained) findings are counted but not listed; "
        "use get_findings with include_flagged for them.",
    }


def lockdown(con: duckdb.DuckDBPyConnection, allowed_paths: list[str]) -> None:
    """Restrict a connection whose lake is already attached (read-only) for user SQL."""
    paths = ", ".join(sql_literal(p) for p in allowed_paths)
    # Cursors of this connection inherit global settings: results are always in UTC.
    con.execute("SET GLOBAL TimeZone = 'UTC'")
    con.execute(f"SET allowed_directories = [{paths}]")
    con.execute("SET enable_external_access = false")
    con.execute("SET python_enable_replacements = false")
    con.execute("SET lock_configuration = true")
