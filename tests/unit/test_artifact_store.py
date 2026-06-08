"""Tests for the Artifact Store (Module 05)."""

import pytest

from competitive_intel_agents.artifacts import (
    ArtifactStore,
    InMemoryArtifactStore,
    DuplicateArtifactError,
    InvalidArtifactLineageError,
    SQLiteArtifactStore,
)
from competitive_intel_agents.models import AnalysisClaim, ReportDraft, SourceArtifact


def make_source(
    artifact_id: str = "src_001",
    run_id: str = "run_001",
    url: str = "https://example.com/article",
    title: str = "Example Article",
) -> SourceArtifact:
    return SourceArtifact(
        id=artifact_id,
        run_id=run_id,
        url=url,
        title=title,
        snippet="A sample snippet.",
        source_type="web",
    )


def make_claim(
    artifact_id: str = "claim_001",
    run_id: str = "run_001",
    text: str = "Market is growing 15% YoY",
    source_ids: list[str] | None = None,
) -> AnalysisClaim:
    return AnalysisClaim(
        id=artifact_id,
        run_id=run_id,
        text=text,
        source_ids=source_ids or ["src_001"],
        confidence="high",
        reasoning="Based on multiple reports",
    )


def make_report(
    artifact_id: str = "report_001",
    run_id: str = "run_001",
) -> ReportDraft:
    return ReportDraft(
        id=artifact_id,
        run_id=run_id,
        sections={"summary": "A competitive analysis."},
        claim_ids=["claim_001"],
        source_ids=["src_001"],
    )


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_save_and_list_sources(store_factory) -> None:
    """Save sources and retrieve them by run_id."""
    store = store_factory()
    src = make_source("src_001")

    store.save_source(src)
    results = store.list_sources("run_001")

    assert len(results) == 1
    assert results[0] == src


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_save_and_list_claims(store_factory) -> None:
    """Save claims and retrieve only active ones by default."""
    store = store_factory()
    claim = make_claim("claim_001")

    store.save_claim(claim)
    results = store.list_claims("run_001")

    assert len(results) == 1
    assert results[0] == claim
    assert results[0].status == "active"


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_get_latest_report(store_factory) -> None:
    """Retrieve the most recent report for a run_id, or None if absent."""
    store = store_factory()

    assert store.get_latest_report("run_001") is None

    report = make_report("report_001")
    store.save_report(report)
    result = store.get_latest_report("run_001")

    assert result is not None
    assert result.id == "report_001"
    assert result.sections == {"summary": "A competitive analysis."}


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_artifacts_isolated_by_run_id(store_factory) -> None:
    """Artifacts from different runs must not leak into each other."""
    store = store_factory()

    src_a = make_source("src_001", run_id="run_A")
    src_b = make_source("src_002", run_id="run_B")
    claim_a = make_claim("claim_001", run_id="run_A")
    claim_b = make_claim("claim_002", run_id="run_B")

    store.save_source(src_a)
    store.save_source(src_b)
    store.save_claim(claim_a)
    store.save_claim(claim_b)

    assert len(store.list_sources("run_A")) == 1
    assert store.list_sources("run_A")[0].id == "src_001"
    assert len(store.list_claims("run_A")) == 1
    assert store.list_claims("run_A")[0].id == "claim_001"

    assert len(store.list_sources("run_B")) == 1
    assert store.list_sources("run_B")[0].id == "src_002"
    assert len(store.list_claims("run_B")) == 1
    assert store.list_claims("run_B")[0].id == "claim_002"


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_mark_old_claims_as_superseded(store_factory) -> None:
    """After rework, old claims are superseded and only active claims appear by default."""
    store = store_factory()

    old_claim = make_claim("claim_v1", run_id="run_001")
    new_claim = AnalysisClaim(
        id="claim_v2",
        run_id="run_001",
        text="Market is growing 20% YoY",
        source_ids=["src_001"],
        confidence="high",
        version=2,
        supersedes_id="claim_v1",
    )

    store.save_claim(old_claim)
    store.save_claim(new_claim)
    store.mark_superseded("claim_v1", "claim_v2")

    active = store.list_claims("run_001")
    assert len(active) == 1
    assert active[0].id == "claim_v2"

    # Superseded claims are still accessible when explicitly requested
    all_claims = store.list_claims("run_001", status="superseded")
    assert len(all_claims) == 1
    assert all_claims[0].id == "claim_v1"
    assert all_claims[0].status == "superseded"


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_exclude_rejected_artifacts_from_default_reads(store_factory) -> None:
    """Rejected artifacts must not appear in default (active) listings."""
    store = store_factory()

    good_claim = make_claim("claim_good", run_id="run_001")
    bad_claim = make_claim("claim_bad", run_id="run_001", text="Unsupported claim")

    store.save_claim(good_claim)
    store.save_claim(bad_claim)
    store.mark_rejected("claim_bad", "No source evidence")

    active = store.list_claims("run_001")
    assert len(active) == 1
    assert active[0].id == "claim_good"

    # Rejected artifacts are still available for audit
    rejected = store.list_claims("run_001", status="rejected")
    assert len(rejected) == 1
    assert rejected[0].id == "claim_bad"
    assert rejected[0].status == "rejected"


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_mark_superseded_only_affects_target_artifact(store_factory) -> None:
    """mark_superseded must not change the status of unrelated artifacts."""
    store = store_factory()

    claim_a = make_claim("claim_a", run_id="run_001")
    claim_b = make_claim("claim_b", run_id="run_001", text="Another claim")
    claim_c = AnalysisClaim(
        id="claim_a_v2",
        run_id="run_001",
        text="Market is growing 15% YoY (revised)",
        source_ids=["src_001"],
        confidence="high",
        version=2,
        supersedes_id="claim_a",
    )

    store.save_claim(claim_a)
    store.save_claim(claim_b)
    store.save_claim(claim_c)
    store.mark_superseded("claim_a", "claim_a_v2")

    active = store.list_claims("run_001")
    active_ids = {c.id for c in active}
    assert active_ids == {"claim_b", "claim_a_v2"}


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_sqlite_store_persists_across_connections(tmp_path, store_factory) -> None:
    """SQLite-backed store must survive close and reopen."""
    if store_factory is InMemoryArtifactStore:
        pytest.skip("InMemory store does not persist")

    db_path = tmp_path / "artifacts.sqlite"
    first_store = store_factory(db_path)
    src = make_source("src_001")
    first_store.save_source(src)

    second_store = store_factory(db_path)
    assert second_store.list_sources("run_001") == [src]


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_get_latest_report_returns_highest_version(store_factory) -> None:
    """When multiple report versions exist, return the latest version."""
    store = store_factory()

    report_v1 = make_report("report_v1", run_id="run_001")
    report_v2 = ReportDraft(
        id="report_v2",
        run_id="run_001",
        version=2,
        supersedes_id="report_v1",
        sections={"summary": "Revised analysis."},
        claim_ids=["claim_002"],
        source_ids=["src_001", "src_002"],
    )

    store.save_report(report_v1)
    store.save_report(report_v2)

    latest = store.get_latest_report("run_001")
    assert latest is not None
    assert latest.id == "report_v2"


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_get_artifact_returns_current_status_for_audit(store_factory) -> None:
    """Rework needs direct artifact lookup without relying on active listings."""
    store = store_factory()
    claim = make_claim("claim_audit", run_id="run_001")

    store.save_claim(claim)
    store.mark_rejected("claim_audit", "Unsupported claim")

    result = store.get_artifact("claim_audit")

    assert result.id == "claim_audit"
    assert result.status == "rejected"


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_list_artifacts_can_include_all_statuses(store_factory) -> None:
    """Agents need all artifacts for monotonic ids, while reads default to active."""
    store = store_factory()
    claim_v1 = make_claim("claim_v1", run_id="run_001")
    claim_v2 = AnalysisClaim(
        id="claim_v2",
        run_id="run_001",
        text="Revised claim",
        source_ids=["src_001"],
        version=2,
        supersedes_id="claim_v1",
    )
    report_v1 = make_report("report_v1", run_id="run_001")

    store.save_claim(claim_v1)
    store.save_claim(claim_v2)
    store.mark_superseded("claim_v1", "claim_v2")
    store.save_report(report_v1)
    store.mark_rejected("report_v1", "Stale report")

    assert [claim.id for claim in store.list_claims("run_001")] == ["claim_v2"]
    assert {claim.id for claim in store.list_claims("run_001", status=None)} == {
        "claim_v1",
        "claim_v2",
    }
    assert store.get_latest_report("run_001") is None
    assert [report.id for report in store.list_reports("run_001", status=None)] == [
        "report_v1"
    ]


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_rejects_duplicate_artifact_ids(store_factory) -> None:
    """Artifact ids are immutable; rework must write a new id."""
    store = store_factory()
    claim = make_claim("claim_dup", run_id="run_001")

    store.save_claim(claim)

    with pytest.raises(DuplicateArtifactError, match="claim_dup"):
        store.save_claim(claim)


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_supersede_requires_same_run_and_type(store_factory) -> None:
    """Replacement artifacts must not cross run or artifact type boundaries."""
    store = store_factory()
    old_claim = make_claim("claim_old", run_id="run_A")
    wrong_run = AnalysisClaim(
        id="claim_new_wrong_run",
        run_id="run_B",
        text="Revised claim",
        source_ids=["src_001"],
        version=2,
        supersedes_id="claim_old",
    )
    wrong_type = ReportDraft(
        id="report_replacement",
        run_id="run_A",
        sections={"summary": "Not a claim replacement."},
        version=2,
        supersedes_id="claim_old",
    )

    store.save_claim(old_claim)
    store.save_claim(wrong_run)
    store.save_report(wrong_type)

    with pytest.raises(InvalidArtifactLineageError, match="same run_id"):
        store.mark_superseded("claim_old", "claim_new_wrong_run")

    with pytest.raises(InvalidArtifactLineageError, match="same artifact type"):
        store.mark_superseded("claim_old", "report_replacement")


@pytest.mark.parametrize("store_factory", [InMemoryArtifactStore, SQLiteArtifactStore])
def test_supersede_requires_forward_version_and_pointer(store_factory) -> None:
    """Replacement artifacts must be newer and point back to the old artifact."""
    store = store_factory()
    old_claim = make_claim("claim_old", run_id="run_001")
    missing_pointer = AnalysisClaim(
        id="claim_missing_pointer",
        run_id="run_001",
        text="Revised claim",
        source_ids=["src_001"],
        version=2,
    )
    stale_version = AnalysisClaim(
        id="claim_stale_version",
        run_id="run_001",
        text="Another revised claim",
        source_ids=["src_001"],
        version=1,
        supersedes_id="claim_old",
    )

    store.save_claim(old_claim)
    store.save_claim(missing_pointer)
    store.save_claim(stale_version)

    with pytest.raises(InvalidArtifactLineageError, match="supersedes_id"):
        store.mark_superseded("claim_old", "claim_missing_pointer")

    with pytest.raises(InvalidArtifactLineageError, match="version"):
        store.mark_superseded("claim_old", "claim_stale_version")
