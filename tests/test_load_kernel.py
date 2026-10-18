"""Loading real-world files into a real kernel.

diagnose.load learned the cp1252 fallback when HM Treasury's March 2026 file
crashed it; the agent's own LOAD_TEMPLATE is a second copy of the same read and
kept the hardcoded utf-8-sig. A live /load of the same real file dies inside
the kernel before the variable exists — this pins the fallback at the seam
diagnose's test cannot reach.
"""

import contextlib
import functools
import hashlib
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from crivo.loop import Session

SUBPROCESS_ARGV = [sys.executable, "-m", "crivo.kernel.supervisor"]


def test_a_windows_encoded_export_loads_into_the_kernel(tmp_path) -> None:
    csv = tmp_path / "spend.csv"
    rows = "Supplier,Amount\n" + "\n".join(f"V{i},£{i}25.00" for i in range(30))
    csv.write_bytes(rows.encode("cp1252"))

    session = Session(
        workspace=tmp_path / "ws",
        data_dir=tmp_path,
        transport_argv=SUBPROCESS_ARGV,
        skills_dir=tmp_path / "skills",
    )
    try:
        session.load(str(csv), "spend")
        assert any(d["variable"] == "spend" for d in session.datasets), (
            "the cp1252 file never became a kernel variable"
        )
    finally:
        session.close()


def test_resume_rebuilds_a_usable_session(tmp_path) -> None:
    """P5 R9/AC6: no daemon, no socket — a resumed session is a new process
    reading an old log. It must come back with its datasets loaded into a
    fresh kernel, its history carrying the dataset profiles, its numbering
    continuing, and a /why chain that still resolves from disk."""
    from crivo import provenance

    csv = tmp_path / "tiny.csv"
    csv.write_text("a,b\n1,2\n3,4\n")
    first = Session(
        workspace=tmp_path / "ws",
        data_dir=tmp_path,
        transport_argv=SUBPROCESS_ARGV,
        skills_dir=tmp_path / "skills",
    )
    first.load(str(csv), "tiny")
    session_id = first.session_id
    first.close()

    second = Session(
        workspace=tmp_path / "ws",
        data_dir=tmp_path,
        transport_argv=SUBPROCESS_ARGV,
        skills_dir=tmp_path / "skills",
        resume=session_id,
    )
    try:
        assert second.session_id == session_id
        assert [d["variable"] for d in second.datasets] == ["tiny"]
        assert second.datasets[0]["sha256"] == first.datasets[0]["sha256"]

        result = None
        for ev in second.client.execute("tuple(tiny.shape)", timeout_s=60):
            result = ev
        assert result.status == "ok", result.error
        assert result.value == "(2, 2)", "the dataset must be loaded, not just listed"

        assert any(
            "<dataset variable='tiny'>" in m["content"] for m in second.history
        ), "the model's view of the data must survive the resume"

        dag = provenance.build(second.session_dir)
        assert dag, "the /why chain must still resolve from disk"
    finally:
        second.close()


def test_the_agent_loads_with_the_same_policy_diagnose_does(tmp_path) -> None:
    """LOAD_TEMPLATE was a second, weaker copy of the loader: no delimiter
    sniff (a semicolon CSV became one column) and pandas' default NA handling
    (read_csv coerced 'N/A' to NaN at load time, silently repairing d04's
    evidence before diagnosis ever ran — so diagnose and a live /clean of the
    same file disagreed about sentinel counts). One loader, one policy: the
    kernel cell now calls diagnose.load."""
    csv = tmp_path / "eu.csv"
    csv.write_text("region;amount\nnorth;12\nsouth;N/A\neast;9\nwest;N/A\n")

    session = Session(
        workspace=tmp_path / "ws",
        data_dir=tmp_path,
        transport_argv=SUBPROCESS_ARGV,
        skills_dir=tmp_path / "skills",
    )
    try:
        session.load(str(csv), "eu")
        result = None
        for ev in session.client.execute(
            "assert eu.shape[1] == 2, f'sniff failed: {list(eu.columns)}'\n"
            "assert (eu['amount'] == 'N/A').sum() == 2, 'N/A must survive load'\n"
            "'ok'",
            timeout_s=60,
        ):
            result = ev
        assert result.status == "ok", result.error
    finally:
        session.close()


def test_the_registry_carries_a_frames_remote_stamp(tmp_path) -> None:
    """R12's kernel half: readers.remote.read_url stamps frame.attrs['remote']
    inside the kernel, and the registry probe must carry it up, or the host can
    never ground remote data in lineage."""
    session = Session(
        workspace=tmp_path / "ws",
        data_dir=tmp_path,
        transport_argv=SUBPROCESS_ARGV,
        skills_dir=tmp_path / "skills",
    )
    try:
        result = None
        for ev in session.client.execute(
            "import pandas as pd\n"
            "feed = pd.DataFrame({'a': [1, 2]})\n"
            "feed.attrs['remote'] = {'uri': 'https://x/f.csv', 'sha256': 'ab' * 32,\n"
            "                        'fetched_at': '2026-08-14T21:00:00+00:00'}\n"
            "'stamped'",
            timeout_s=60,
        ):
            result = ev
        assert result.status == "ok", result.error
        (entry,) = [e for e in result.registry if e["name"] == "feed"]
        assert entry.get("remote", {}).get("sha256") == "ab" * 32
    finally:
        session.close()


@contextlib.contextmanager
def _serving(directory):
    """Serve `directory` over localhost for the kernel to fetch from; yields
    the base URL."""
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _remote_variables(session) -> list[str]:
    return [d["variable"] for d in session.datasets if d.get("remote")]


def test_a_filtered_copy_of_a_remote_frame_is_not_a_second_source(tmp_path) -> None:
    """pandas copies attrs onto a derived frame, so `big = feed[feed.a > 1]`
    inherits the stamp of the payload it was cut from. Forwarded, the session
    records `big` as a second remote dataset carrying the raw payload's hash:
    false lineage. The probe forwards a stamp only while the frame still has
    the fetched row count; `feed` itself keeps its stamp."""
    session = Session(
        workspace=tmp_path / "ws",
        data_dir=tmp_path,
        transport_argv=SUBPROCESS_ARGV,
        skills_dir=tmp_path / "skills",
    )
    try:
        result = None
        for ev in session.client.execute(
            "import pandas as pd\n"
            "feed = pd.DataFrame({'a': [1, 2]})\n"
            "feed.attrs['remote'] = {'uri': 'https://x/f.csv', 'sha256': 'cd' * 32,\n"
            "                        'fetched_at': '2026-10-17T09:00:00+00:00',\n"
            "                        'rows': 2}\n"
            "big = feed[feed.a > 1]\n"
            "'filtered'",
            timeout_s=60,
        ):
            result = ev
        assert result.status == "ok", result.error
        by_name = {e["name"]: e for e in result.registry}
        assert by_name["feed"].get("remote", {}).get("sha256") == "cd" * 32
        assert "remote" not in by_name["big"], "a filtered copy is not the payload"

        session._stamp_registry(result.registry, 1)
        assert _remote_variables(session) == ["feed"]
    finally:
        session.close()


def test_a_frame_read_from_a_url_in_the_kernel_is_one_remote_source(
    tmp_path,
) -> None:
    """End to end: `crivo.read(url)` in the kernel stamps the frame, the
    registry carries the stamp up, and the session records exactly one remote
    dataset whose hash is the served file's. What is cut from the frame is not
    a second source: a filtered copy (fewer rows), a column projection (other
    columns) and a single column as a Series (no columns at all, which the
    probe must survive rather than break the registry over)."""
    served = tmp_path / "srv"
    served.mkdir()
    ledger = served / "ledger.csv"
    ledger.write_text(
        "supplier_id,supplier,amount\n"
        "00412,Acme Ltd,1200.50\n"
        "00077,Globex,N/A\n"
        "01999,Initech,-999\n"
    )
    digest = hashlib.sha256(ledger.read_bytes()).hexdigest()

    session = Session(
        workspace=tmp_path / "ws",
        data_dir=tmp_path,
        transport_argv=SUBPROCESS_ARGV,
        skills_dir=tmp_path / "skills",
    )
    try:
        with _serving(served) as base:
            url = f"{base}/ledger.csv"
            result = None
            for ev in session.client.execute(
                "import crivo\n"
                f"feed = crivo.read({url!r})\n"
                "big = feed[feed['amount'] != 'N/A']\n"
                "ids = feed[['supplier_id']]\n"
                "col = feed['supplier']\n"
                "'read'",
                timeout_s=60,
            ):
                result = ev
        assert result.status == "ok", result.error
        by_name = {e["name"]: e for e in result.registry}
        assert {"feed", "big", "ids", "col"} <= set(by_name), (
            "the registry probe broke on a variable cut from the frame"
        )
        remote = by_name["feed"].get("remote", {})
        assert remote.get("uri") == url
        assert remote.get("sha256") == digest
        for derived in ("big", "ids", "col"):
            assert "remote" not in by_name[derived], (
                f"{derived} was cut from the payload, not fetched"
            )

        session._stamp_registry(result.registry, 1)
        assert _remote_variables(session) == ["feed"]
    finally:
        session.close()
