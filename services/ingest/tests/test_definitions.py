from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dagster import SensorResult, SkipReason, build_sensor_context

from xomtra_ingest import tasks
from xomtra_ingest.__main__ import main
from xomtra_ingest.definitions import build_definitions, restate_after_catchup
from xomtra_ingest.settings import IngestSettings


def test_definitions_load_with_schedules() -> None:
    defs = build_definitions(IngestSettings(timezone="Europe/Prague"))
    jobs = {j.name for j in defs.resolve_all_job_defs()}
    assert {
        "ingest_hourly",
        "retention_daily",
        "catalog_daily",
        "findings_weekly",
        "history_backfill",
        "silver_restate",
    } <= jobs
    schedules = {s.job_name: s for s in defs.schedules or []}  # type: ignore[union-attr]
    assert schedules["ingest_hourly"].execution_timezone == "Europe/Prague"
    assert schedules["catalog_daily"].cron_schedule == "15 4 * * *"
    assert schedules["findings_weekly"].cron_schedule == "0 7 * * 1"


def test_restate_sensor(monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    gaps = [(start, start + timedelta(hours=5), 10), (start, start + timedelta(hours=8), 20)]
    monkeypatch.setattr(
        tasks, "pending_gaps", lambda after: [g for g in gaps if g[2] > (after or 0)]
    )

    result = restate_after_catchup(build_sensor_context())
    assert isinstance(result, SensorResult)
    assert result.cursor == "20"
    [request] = result.run_requests or []
    assert request.run_key == "catchup-20"
    config = request.run_config["ops"]["restate_silver"]["config"]
    assert config == {"start": start.isoformat(), "end": (start + timedelta(hours=8)).isoformat()}

    skipped = restate_after_catchup(build_sensor_context(cursor="20"))
    assert isinstance(skipped, SkipReason)


def test_parse_time() -> None:
    assert tasks.parse_time("2026-01-01") == datetime(2026, 1, 1, tzinfo=UTC)
    rel = tasks.parse_time("3d")
    assert abs((datetime.now(UTC) - rel) - timedelta(days=3)) < timedelta(seconds=5)


def test_settings_defaults_and_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XOMTRA_OPS_PG_PASSWORD", "p@ss/word")
    s = IngestSettings()
    assert s.states_retention_days == 365
    assert s.statistics_5min_retention_days == 365
    assert s.statistics_hour_retention_days == 1825
    assert s.ops_pg_uri("dagster").endswith(":p%40ss%2Fword@postgres:5432/dagster")
    with pytest.raises(ValueError, match="not connected"):
        IngestSettings(ha_url="").require_ha()


def test_cli_requires_command() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_catalog_daily_runs_correlations_after_profile() -> None:
    defs = build_definitions(IngestSettings())
    job = defs.resolve_job_def("catalog_daily")
    deps = job.graph.dependencies
    assert {n.name for n in job.graph.node_defs} == {
        "profile_catalog",
        "sync_outside_temperature",
        "find_correlations",
        "find_anomalies",
    }
    assert any("find_correlations" in str(k) for k in deps)
    assert any("find_anomalies" in str(k) for k in deps)


def test_correlation_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = IngestSettings()
    assert s.correlation_windows_days == [365, 30]
    assert s.correlation_outside_temp == ""
    monkeypatch.setenv("XOMTRA_CORRELATION_WINDOWS_DAYS", "[30, 90, 30]")
    monkeypatch.setenv("XOMTRA_CORRELATION_OUTSIDE_TEMP", "sensor.outdoor")
    s = IngestSettings()
    assert s.correlation_windows_days == [90, 30]
    assert s.correlation_outside_temp == "sensor.outdoor"
    with pytest.raises(ValueError, match=r"7\.\.1825"):
        IngestSettings(correlation_windows_days=[3])


def test_cli_correlations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tasks, "find_correlations", lambda settings: [{"window_days": 30}])
    assert main(["correlations"]) == 0
    assert '"window_days": 30' in capsys.readouterr().out


def test_outside_temperature_off_by_default() -> None:
    assert tasks.sync_outside_temperature(IngestSettings()) == {
        "skipped": "XOMTRA_OPEN_METEO_ENABLED is off"
    }
    with pytest.raises(ValueError, match="https"):
        IngestSettings(open_meteo_url="http://example.org")


def test_cli_anomalies_and_weekly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tasks, "find_anomalies", lambda settings: {"anomalies": 3})
    monkeypatch.setattr(tasks, "snapshot_findings", lambda settings: {"findings": 5})
    assert main(["anomalies"]) == 0
    assert '"anomalies": 3' in capsys.readouterr().out
    assert main(["findings-weekly"]) == 0
    assert '"findings": 5' in capsys.readouterr().out


def test_anomalies_can_be_switched_off() -> None:
    assert tasks.find_anomalies(IngestSettings(anomalies_enabled=False)) == {
        "skipped": "XOMTRA_ANOMALIES_ENABLED is off"
    }


def test_label_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    assert IngestSettings().labels.analysis == ["xomtra_no_analysis", "xomtra_no_ingest"]
    monkeypatch.setenv("XOMTRA_LABEL_NO_INGEST", " private ")
    monkeypatch.setenv("XOMTRA_LABEL_NO_ANALYSIS", "skip_analysis")
    labels = IngestSettings().labels
    assert (labels.no_ingest, labels.no_analysis) == ("private", "skip_analysis")
    monkeypatch.setenv("XOMTRA_LABEL_NO_ANALYSIS", "  ")
    with pytest.raises(ValueError, match="label"):
        IngestSettings()


def test_lite_edition_retention_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XOMTRA_EDITION", "lite")
    s = IngestSettings()
    assert (s.states_retention_days, s.statistics_5min_retention_days) == (90, 90)
    assert s.statistics_hour_retention_days == 5 * 365
    monkeypatch.setenv("XOMTRA_STATES_RETENTION_DAYS", "30")
    assert IngestSettings().states_retention_days == 30
    monkeypatch.delenv("XOMTRA_EDITION")
    monkeypatch.delenv("XOMTRA_STATES_RETENTION_DAYS")
    assert IngestSettings().states_retention_days == 365


def test_stream_waits_for_the_ha_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hacore.ha_connection import HAConnection
    from xomtra_ingest.__main__ import wait_for_ha

    answers = [None, None, HAConnection("http://ha:8123", "t", "stored")]

    class Fake:
        invalidated = 0

        def get(self) -> HAConnection | None:
            return answers.pop(0)

        def invalidate(self) -> None:
            Fake.invalidated += 1

    monkeypatch.setattr(IngestSettings, "ha_resolver", lambda self: Fake())
    heartbeat = tmp_path / "hb"
    slept: list[float] = []
    url, token = wait_for_ha(IngestSettings(heartbeat_file=heartbeat), poll=5, sleep=slept.append)
    assert (url, token) == ("http://ha:8123", "t")
    assert slept == [5, 5]
    assert Fake.invalidated == 2
    assert heartbeat.exists()  # healthy while waiting


def test_catalog_on_new_installation_syncs_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """No silver before the first hourly ingest: the catalog runs the sync first."""
    calls: list[str] = []
    silver = iter([False, True])
    monkeypatch.setattr(tasks, "_has_silver_entities", lambda: next(silver))
    monkeypatch.setattr(tasks, "sync_registries", lambda: calls.append("registries"))
    monkeypatch.setattr(tasks, "sync_statistics", lambda s=None: calls.append("statistics"))
    monkeypatch.setattr(tasks, "run_transform", lambda: calls.append("transform"))

    class Profile:
        entities, drift = 3, 0

    class Lake:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(tasks, "open_lake", Lake)
    monkeypatch.setattr(tasks.catalog, "profile", lambda con, window: Profile())
    assert tasks.profile_catalog(IngestSettings()) == {"entities": 3, "drift": 0}
    assert calls == ["registries", "statistics", "transform"]


def test_catalog_without_data_explains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_has_silver_entities", lambda: False)
    for name in ("sync_registries", "run_transform"):
        monkeypatch.setattr(tasks, name, lambda: None)
    monkeypatch.setattr(tasks, "sync_statistics", lambda s=None: None)
    with pytest.raises(RuntimeError, match="Home Assistant is connected"):
        tasks.profile_catalog(IngestSettings())
