import os
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from hacore.lake import connect_local
from xomtra_mcp.audit import AuditError, AuditRecord, MemoryAuditSink
from xomtra_mcp.config import Settings
from xomtra_mcp.data import DataAccess
from xomtra_mcp.server import create_server

EXT = os.environ.get("XOMTRA_DUCKDB_EXTENSION_DIR") or None
ADMIN = ["xomtra.Admin"]
READER = ["xomtra.Reader"]


def server(data: DataAccess, roles: list[str], audit: Any = None) -> Any:
    settings = Settings(auth_mode="none", host="127.0.0.1", dev_roles=roles)  # type: ignore[arg-type]
    return create_server(settings, data=data, audit=audit or MemoryAuditSink())


async def call(srv: Any, tool: str, **args: Any) -> Any:
    async with Client(srv) as client:
        return (await client.call_tool(tool, args)).data


async def test_tool_list_follows_roles(data: DataAccess) -> None:
    async with Client(server(data, READER)) as client:
        names = {t.name for t in await client.list_tools()}
    assert {"search_catalog", "describe_entity", "get_timeseries", "query_sql"} <= names
    assert "ha_overview" not in names
    async with Client(server(data, [])) as client:
        assert {t.name for t in await client.list_tools()} == {"whoami"}


async def test_search_catalog_hides_denied_entities(data: DataAccess) -> None:
    admin = await call(server(data, ADMIN), "search_catalog")
    reader = await call(server(data, READER), "search_catalog")
    admin_ids = {e["entity_id"] for e in admin["entities"]}
    reader_ids = {e["entity_id"] for e in reader["entities"]}
    assert {"person.jana", "device_tracker.phone"} <= admin_ids
    assert reader_ids == admin_ids - {"person.jana", "device_tracker.phone"}

    found = await call(server(data, READER), "search_catalog", query="teplota obývák")
    assert [e["entity_id"] for e in found["entities"]] == ["sensor.temp"]
    assert found["entities"][0]["kind"] == "measurement"
    counters = await call(server(data, ADMIN), "search_catalog", kind="counter")
    assert [e["entity_id"] for e in counters["entities"]] == ["sensor.energy"]


async def test_reader_does_not_see_attributes(data: DataAccess) -> None:
    sql = "SELECT * FROM states LIMIT 1"
    admin = await call(server(data, ADMIN), "query_sql", sql=sql)
    reader = await call(server(data, READER), "query_sql", sql=sql)
    assert "attributes" in admin["columns"]
    assert "attributes" not in reader["columns"]
    assert "state_value" in reader["columns"]
    with pytest.raises(ToolError, match="attributes"):
        await call(server(data, READER), "query_sql", sql="SELECT attributes FROM states")
    views = await call(server(data, READER), "list_views")
    states = next(v for v in views["views"] if v["name"] == "states")
    assert "attributes" not in {c["name"] for c in states["columns"]}


async def test_describe_entity(data: DataAccess) -> None:
    result = await call(server(data, READER), "describe_entity", entity_id="sensor.temp")
    assert result["entity"]["value_max"] == 23.0
    assert result["statistics"]["unit_of_measurement"] == "°C"
    assert result["latest_state"]["state_value"] is not None


async def test_denied_entity_is_refused_and_audited(data: DataAccess) -> None:
    audit = MemoryAuditSink()
    srv = server(data, READER, audit)
    with pytest.raises(ToolError, match="denied"):
        await call(srv, "describe_entity", entity_id="person.jana")
    with pytest.raises(ToolError, match="denied"):
        await call(srv, "get_timeseries", entity_id="person.jana", start="2d")
    with pytest.raises(ToolError, match="do not allow"):
        await call(srv, "ha_overview")
    assert [(r.tool, r.decision) for r in audit.records] == [
        ("describe_entity", "denied"),
        ("get_timeseries", "denied"),
        ("ha_overview", "denied"),
    ]
    assert all(r.subject == "dev" and r.roles == READER for r in audit.records)


async def test_timeseries_raw_states_and_statistics(data: DataAccess) -> None:
    srv = server(data, READER)
    raw = await call(srv, "get_timeseries", entity_id="sensor.temp", start="1d")
    assert raw["resolution"] == "raw"
    assert raw["source"] == "states"
    assert 20 <= len(raw["points"]) <= 25
    hourly = await call(
        srv, "get_timeseries", entity_id="sensor.temp", start="2d", resolution="hour"
    )
    assert hourly["source"] == "statistics:hour"
    assert hourly["points"][0]["mean"] == 21.0
    daily = await call(
        srv, "get_timeseries", entity_id="binary_sensor.door", start="5d", resolution="day"
    )
    assert daily["source"] == "states"
    assert daily["timezone"] == "Europe/Prague"
    assert daily["points"][-1]["last_state"] == "on"
    with pytest.raises(ToolError, match="Invalid time"):
        await call(srv, "get_timeseries", entity_id="sensor.temp", start="yesterday")


async def test_query_sql_row_level_policy(data: DataAccess) -> None:
    sql = "SELECT domain, count(*) AS n FROM states GROUP BY domain ORDER BY domain"
    admin = await call(server(data, ADMIN), "query_sql", sql=sql)
    reader = await call(server(data, READER), "query_sql", sql=sql)
    assert {r["domain"] for r in admin["rows"]} == {"binary_sensor", "person", "sensor"}
    assert {r["domain"] for r in reader["rows"]} == {"binary_sensor", "sensor"}
    assert reader["columns"] == ["domain", "n"]


async def test_findings_hide_pairs_with_a_denied_entity(data: DataAccess) -> None:
    sql = (
        "SELECT finding_id, entity_group FROM catalog_finding "
        "WHERE finding_type = 'correlation' ORDER BY rank"
    )
    admin = await call(server(data, ADMIN), "query_sql", sql=sql)
    reader = await call(server(data, READER), "query_sql", sql=sql)
    assert [r["finding_id"] for r in admin["rows"]] == ["f1", "f2", "f3"]
    assert [r["finding_id"] for r in reader["rows"]] == ["f1", "f3"]
    # a denied entity is also removed from the group lists
    assert admin["rows"][0]["entity_group"] == ["sensor.temp_copy", "person.jana"]
    assert reader["rows"][0]["entity_group"] == ["sensor.temp_copy"]


async def test_get_findings(data: DataAccess) -> None:
    reader = await call(server(data, READER), "get_findings")
    ids = [f["finding_id"] for f in reader["findings"]]
    # anomalies first, flagged ones (f3, a2) hidden, denied entities (f2, a3) never shown
    assert ids == ["a1", "f1"]
    assert reader["counts"] == {
        "anomaly": {"total": 2, "flagged": 1},
        "correlation": {"total": 2, "flagged": 1},
    }
    a1 = reader["findings"][0]
    assert a1["entity_name"] == "Energie"
    assert a1["unit"] == "kWh"
    assert a1["observed"] == 5.0
    assert "related_entity_id" not in a1  # empty columns are left out
    f1 = reader["findings"][1]
    assert f1["related_name"] == "Vstupní dveře"
    assert f1["entity_group"] == ["sensor.temp_copy"]
    everything = await call(server(data, ADMIN), "get_findings", include_flagged=True)
    assert [f["finding_id"] for f in everything["findings"]] == ["a1", "a2", "a3", "f1", "f2", "f3"]
    only = await call(
        server(data, READER), "get_findings", entity_id="sensor.energy", include_flagged=True
    )
    assert {f["finding_id"] for f in only["findings"]} == {"a1", "a2", "f3"}
    corr = await call(server(data, READER), "get_findings", finding_type="correlation")
    assert [f["finding_id"] for f in corr["findings"]] == ["f1"]
    assert corr["methods"] == [{"finding_type": "correlation", "window_days": 30, "method": "test"}]
    (conf,) = corr["confidence"]
    assert conf["window_days"] == 30
    assert conf["level"] == "low"
    assert conf["group_coverage"] == 0.25
    assert "hypotheses" in conf["note"]
    assert "ungrouped" not in conf
    with pytest.raises(ToolError, match="denied"):
        await call(server(data, READER), "get_findings", entity_id="person.jana")


async def test_get_weekly_summary(data: DataAccess) -> None:
    summary = await call(server(data, READER), "get_weekly_summary")
    assert summary["compared_with"] is not None
    assert [a["finding_id"] for a in summary["anomalies"]] == ["a1"]
    # f2 is new but hidden (person), f3 is new but trivial; f9 is gone
    assert summary["new_correlations"] == []
    assert [c["finding_id"] for c in summary["gone_correlations"]] == ["f9"]
    assert summary["counts"]["anomaly"] == {"total": 2, "flagged": 1}
    admin = await call(server(data, ADMIN), "get_weekly_summary")
    assert [c["finding_id"] for c in admin["new_correlations"]] == ["f2"]
    earlier = await call(server(data, ADMIN), "get_weekly_summary", week=summary["compared_with"])
    assert earlier["compared_with"] is None
    with pytest.raises(ToolError, match="No snapshot"):
        await call(server(data, ADMIN), "get_weekly_summary", week="2020-01-01")


async def test_query_sql_rejections_are_audited(data: DataAccess) -> None:
    audit = MemoryAuditSink()
    srv = server(data, READER, audit)
    for sql, message in [
        ("SELECT * FROM range(5000)", "Table functions"),
        ("SELECT * FROM catalog_drift", "not permitted"),
        ("SELECT nope FROM states", "nope"),
        ("SELECT * FROM read_parquet('/etc/passwd')", "Table functions"),
    ]:
        with pytest.raises(ToolError, match=message):
            await call(srv, "query_sql", sql=sql)
    assert [r.outcome for r in audit.records] == ["error"] * 4
    assert audit.records[0].arguments == {"sql": "SELECT * FROM range(5000)"}

    big = await call(
        srv, "query_sql", sql="SELECT s.* FROM states s, states t, states u LIMIT 5000"
    )
    assert big["truncated"] is True
    assert big["row_count"] == 1000
    assert audit.records[-1].row_count == 1000


async def test_list_views(data: DataAccess) -> None:
    res = await call(server(data, READER), "list_views")
    names = [v["name"] for v in res["views"]]
    assert names == [
        "catalog_entity",
        "catalog_finding",
        "catalog_finding_weekly",
        "entities",
        "states",
        "statistics",
        "statistics_meta",
    ]
    states = next(v for v in res["views"] if v["name"] == "states")
    assert {"name": "state_value", "type": "DOUBLE"} in states["columns"]


async def test_engine_is_locked_down(data: DataAccess) -> None:
    from xomtra_mcp.policy import Access

    access = Access(
        roles=("x",),
        tools=frozenset({"*"}),
        views=frozenset({"*"}),
        max_rows=10,
        known_views=frozenset({"states"}),
    )
    with data._cursor(access) as cur:  # bypass the guard: the engine must still refuse
        for sql in (
            "SELECT * FROM read_csv('/etc/passwd')",
            "SET enable_external_access = true",
            "INSERT INTO lake.silver.states (entity_id) VALUES ('x')",
        ):
            with pytest.raises(Exception):  # noqa: B017, PT011
                cur.execute(sql)


class FailingAudit(MemoryAuditSink):
    async def write(self, record: AuditRecord) -> None:
        raise AuditError("down")


async def test_audit_failure_refuses_the_call(data: DataAccess) -> None:
    with pytest.raises(ToolError, match="Audit is unavailable"):
        await call(server(data, ADMIN, FailingAudit()), "list_views")


async def test_empty_lake(tmp_path: Path) -> None:
    catalog, data_path = str(tmp_path / "c.ducklake"), str(tmp_path / "d") + "/"
    connect_local(catalog, data_path, extension_dir=EXT).close()
    empty = DataAccess.local(catalog, data_path, extension_dir=EXT)
    try:
        srv = server(empty, ADMIN)
        assert (await call(srv, "list_views"))["views"] == []
        # A new installation: no catalog yet, the tools say so instead of a DuckDB error.
        found = await call(srv, "search_catalog")
        assert found["entities"] == []
        assert "not built yet" in found["note"]
        findings = await call(srv, "get_findings")
        assert findings["findings"] == []
        assert "not built yet" in findings["note"]
        with pytest.raises(ToolError, match="not built yet"):
            await call(srv, "describe_entity", entity_id="sensor.x")
    finally:
        empty.close()


async def test_rules_travel_with_data_tools(data: DataAccess) -> None:
    """ADR 080: the key rules are in every data tool description and in findings results."""
    srv = server(data, ADMIN)
    async with Client(srv) as client:
        tools = {t.name: t.description or "" for t in await client.list_tools()}
    for name in (
        "search_catalog",
        "describe_entity",
        "list_views",
        "get_timeseries",
        "get_findings",
        "get_weekly_summary",
        "query_sql",
    ):
        assert "presence, sleep, health" in tools[name], name
        assert "never invented" in tools[name], name
        assert "political or religious" in tools[name], name
        assert "threats to life or health" in tools[name], name
        assert "answer_guidelines of server_info" in tools[name], name
    assert "\n\nxomtra core rules" in tools["get_findings"]
    findings = await call(srv, "get_findings")
    summary = await call(srv, "get_weekly_summary")
    for result in (findings, summary):
        assert "Answer first" in result["answer_guidelines"]
        assert "never invent data" in result["answer_guidelines"]
    # Other results name the active set (ADR 090).
    catalog = await call(srv, "search_catalog")
    assert catalog["answer_guidelines_set"] == "Default"
