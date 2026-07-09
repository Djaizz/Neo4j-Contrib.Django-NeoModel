"""Neo4j driver + zoneinfo compatibility probes (sealed; no live Bolt).

Documents whether the installed neo4j driver still triggers the CPython
``_zoneinfo`` SIGSEGV when ``tzinfo.utcoffset`` receives a neo4j ``DateTime``.
Crash probes run in subprocesses so pytest is not killed by segfaults.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo

import neo4j
import pytest
from neo4j.time import DateTime as Neo4jDateTime

from agent_neo.util.django_neomodel.models import coerce_to_fixed_offset_for_neo4j


FACILITY_ZONE = ZoneInfo("Asia/Kolkata")
FACILITY_LOCAL_DATETIME = datetime(2026, 5, 1, 9, 0, tzinfo=FACILITY_ZONE)


def _run_probe_subprocess(probe_code: str, *, timeout_seconds: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", probe_code],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


@pytest.mark.unit
def test_installed_neo4j_driver_version_is_recorded() -> None:
    """Pin the environment under test so CI/local drift is visible in failures."""
    assert neo4j.__version__ == "6.2.0"


@pytest.mark.unit
def test_zoneinfo_utcoffset_accepts_python_datetime() -> None:
    offset = FACILITY_LOCAL_DATETIME.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 5.5 * 3600


@pytest.mark.unit
def test_upstream_zoneinfo_neo4j_datetime_still_segfaults_in_subprocess() -> None:
    """Direct probe: ZoneInfo.utcoffset(neo4j_datetime) on installed stack.

    As of neo4j 6.2.0 + CPython 3.14, this still exits with SIGSEGV — the
    upstream bug is not fixed. If this starts passing (exit 0), revisit whether
    coercion patch can be removed.
    """
    probe_code = textwrap.dedent(
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from neo4j.time import DateTime as Neo4jDateTime

        facility_local_datetime = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        native = Neo4jDateTime.from_native(facility_local_datetime)
        ZoneInfo("Asia/Kolkata").utcoffset(native)
        print("unexpected success")
        """
    )
    completed_process = _run_probe_subprocess(probe_code)
    assert completed_process.returncode != 0, (
        "Expected crash or error for ZoneInfo.utcoffset(neo4j_datetime); "
        f"stdout={completed_process.stdout!r} stderr={completed_process.stderr!r}"
    )
    if completed_process.returncode == -11:
        return  # SIGSEGV — historical failure mode; coercion still required.
    pytest.fail(
        "ZoneInfo.utcoffset(neo4j_datetime) failed without SIGSEGV; "
        f"exit={completed_process.returncode} stderr={completed_process.stderr!r}"
    )


@pytest.mark.unit
def test_from_native_zoneinfo_without_coercion_still_unsafe_in_subprocess() -> None:
    """from_native + ZoneInfo remains unsafe: utc_offset/str paths still crash."""
    probe_code = textwrap.dedent(
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from neo4j.time import DateTime as Neo4jDateTime

        facility_local_datetime = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        converted = Neo4jDateTime.from_native(facility_local_datetime)
        print(converted.utc_offset())
        """
    )
    completed_process = _run_probe_subprocess(probe_code)
    assert completed_process.returncode != 0


@pytest.mark.unit
def test_from_native_zoneinfo_with_coercion_is_stable() -> None:
    coerced = coerce_to_fixed_offset_for_neo4j(FACILITY_LOCAL_DATETIME)
    converted = Neo4jDateTime.from_native(coerced)
    assert converted.tzinfo is not None
    zone_key = getattr(coerced.tzinfo, "key", None)
    if zone_key:
        assert zone_key == "Asia/Kolkata"
    assert converted.utc_offset() is not None


@pytest.mark.unit
def test_coercion_preserves_instant_and_offset() -> None:
    coerced = coerce_to_fixed_offset_for_neo4j(FACILITY_LOCAL_DATETIME)
    assert coerced == FACILITY_LOCAL_DATETIME
    assert coerced.utcoffset() == FACILITY_LOCAL_DATETIME.utcoffset()
