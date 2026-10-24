"""The remote (HTTP) reader: `read_url` fetches a URL with stdlib urllib and
returns a sentinel-safe DataFrame, format decided by Content-Type then the URL
extension. The servers here serve real bytes over localhost so the fetch path is
genuinely exercised — no urllib mocking."""

import functools
import hashlib
import json
import socket
import threading
from datetime import UTC, datetime, timedelta
from http.server import (
    BaseHTTPRequestHandler,
    SimpleHTTPRequestHandler,
    ThreadingHTTPServer,
)
from typing import ClassVar

import pytest


@pytest.fixture
def http_server(tmp_path):
    """A localhost HTTP server over a temp dir holding `data.json` (an object
    with a nested records array) and `data.csv` (with an 'N/A' sentinel). Yields
    the base URL and shuts the server down after."""
    (tmp_path / "data.json").write_text(
        json.dumps(
            {
                "data": {
                    "items": [
                        {"id": "1", "city": "Vancouver"},
                        {"id": "2", "city": "Toronto"},
                    ]
                }
            }
        )
    )
    (tmp_path / "data.csv").write_text("id,note\n1,ok\n2,N/A\n")

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class _ControlHandler(BaseHTTPRequestHandler):
    """Serves a body and Content-Type each test shapes, and records the last
    request's User-Agent and path (query included) — so the fetch discipline
    (header, byte cap, format decision, what URL was asked for) can be
    asserted against real bytes."""

    body = b""
    content_type = "application/octet-stream"
    last_user_agent = None
    last_path = None

    def do_GET(self):
        cls = type(self)
        cls.last_user_agent = self.headers.get("User-Agent")
        cls.last_path = self.path
        self.send_response(200)
        self.send_header("Content-Type", cls.content_type)
        self.end_headers()
        self.wfile.write(cls.body)

    def log_message(self, *args):  # keep the test output quiet
        pass


@pytest.fixture
def control_server():
    """A localhost server whose one response every test shapes via
    `_ControlHandler` class attributes. Yields (base_url, handler_class)."""
    _ControlHandler.body = b""
    _ControlHandler.content_type = "application/octet-stream"
    _ControlHandler.last_user_agent = None
    _ControlHandler.last_path = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ControlHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _ControlHandler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class _RouteHandler(BaseHTTPRequestHandler):
    """Answers each path from a table the test fills, `path -> (status,
    headers, body)`, and 404s anything else, so a redirect chain (a hop and
    its target) is served as real bytes."""

    routes: ClassVar[dict] = {}

    def do_GET(self):
        status, headers, body = type(self).routes.get(self.path, (404, {}, b""))
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the test output quiet
        pass


@pytest.fixture
def route_server():
    """A localhost server answering from `_RouteHandler.routes`, which each
    test fills. Yields (base_url, handler_class)."""
    _RouteHandler.routes = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RouteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _RouteHandler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _closed_port() -> int:
    """A localhost port nothing listens on: bound, then released, so a
    connection to it is refused at once rather than timing out."""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_read_url_json_walks_records_path(http_server) -> None:
    """A JSON object with a nested records array: `records_path='data.items'`
    walks into the parsed object to that list and builds the frame from it."""
    from crivo.readers.remote import read_url

    df = read_url(f"{http_server}/data.json", records_path="data.items")

    assert list(df.columns) == ["id", "city"]
    assert df["city"].tolist() == ["Vancouver", "Toronto"]


def test_read_url_csv_keeps_sentinel(http_server) -> None:
    """A CSV served over HTTP: rows come back and the 'N/A' cell survives as a
    string the detection engine can see, not silently coerced to NaN."""
    from crivo.readers.remote import read_url

    df = read_url(f"{http_server}/data.csv")

    assert list(df.columns) == ["id", "note"]
    assert (df["note"] == "N/A").sum() == 1


def test_read_url_json_toplevel_array_without_records_path(
    http_server, tmp_path
) -> None:
    """A top-level JSON array with no `records_path` is used as the records list
    directly."""
    from crivo.readers.remote import read_url

    (tmp_path / "arr.json").write_text(json.dumps([{"a": "1"}, {"a": "2"}]))

    df = read_url(f"{http_server}/arr.json")

    assert df["a"].tolist() == ["1", "2"]


def test_read_url_network_failure_raises_clear_error() -> None:
    """A fetch that cannot connect raises a clear RuntimeError naming the source,
    not a bare urllib error or a silent timeout (the `--network none` sandbox)."""
    import socket

    from crivo.readers.remote import read_url

    # Bind a port, then close it, so the connection is refused.
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()

    with pytest.raises(RuntimeError, match="fetch failed"):
        read_url(f"http://127.0.0.1:{closed_port}/data.json", records_path="data")


def test_read_url_sends_a_user_agent(control_server) -> None:
    """The request carries our own User-Agent, not urllib's default."""
    from crivo.readers import remote

    base, handler = control_server
    handler.content_type = "application/json"
    handler.body = json.dumps([{"a": "1"}]).encode()

    remote.read_url(f"{base}/data.json")

    assert handler.last_user_agent == remote.USER_AGENT


def test_read_url_refuses_oversize_bodies(control_server, monkeypatch) -> None:
    """Arc W3/H5: a body past the cap is REFUSED with the limit named — never
    silently truncated (a clipped download is a frame that LOOKS complete,
    worse than no frame at all). CRIVO_HTTP_MAX_BYTES is the knob; a body
    inside the cap still reads whole."""
    import pytest

    from crivo.readers import remote

    base, handler = control_server
    handler.content_type = "text/csv"
    handler.body = b"id,note\n1,a\n2,b\n3,c\n"
    monkeypatch.setenv("CRIVO_HTTP_MAX_BYTES", str(len(b"id,note\n1,a\n")))

    with pytest.raises(RuntimeError, match="CRIVO_HTTP_MAX_BYTES"):
        remote.read_url(f"{base}/data.csv")

    monkeypatch.setenv("CRIVO_HTTP_MAX_BYTES", str(len(handler.body)))
    df = remote.read_url(f"{base}/data.csv")
    assert df["note"].tolist() == ["a", "b", "c"]


def test_read_url_decides_format_by_content_type_then_extension(
    control_server,
) -> None:
    """Content-Type decides first (application/json vs text/csv/text/plain);
    a generic type falls back to the URL's .json/.csv extension; neither raises
    a clear ValueError."""
    from crivo.readers.remote import read_url

    base, handler = control_server

    # Generic content-type: the .json extension routes it to JSON.
    handler.content_type = "application/octet-stream"
    handler.body = json.dumps([{"a": "1"}]).encode()
    assert read_url(f"{base}/x.json")["a"].tolist() == ["1"]

    # Generic content-type: the .csv extension routes it to CSV (sentinel kept).
    handler.content_type = "application/octet-stream"
    handler.body = b"a\nN/A\n"
    assert read_url(f"{base}/x.csv")["a"].tolist() == ["N/A"]

    # text/plain is treated as CSV even with no useful extension.
    handler.content_type = "text/plain"
    handler.body = b"a\nhi\n"
    assert read_url(f"{base}/x")["a"].tolist() == ["hi"]

    # Content-Type wins over extension: application/json on a .csv URL is JSON.
    handler.content_type = "application/json"
    handler.body = json.dumps([{"a": "1"}]).encode()
    assert read_url(f"{base}/x.csv")["a"].tolist() == ["1"]

    # Neither a known content-type nor a known extension: a clear error.
    handler.content_type = "application/octet-stream"
    handler.body = b"mystery"
    with pytest.raises(ValueError):
        read_url(f"{base}/mystery")


def test_remote_bad_records_path_errors_clearly(control_server) -> None:
    """A wrong records_path must name itself, not surface a bare KeyError the
    caller can't tie back to the argument they passed."""
    from crivo.readers import remote

    base, handler = control_server
    handler.content_type = "application/json"
    handler.body = json.dumps({"data": {"items": [{"a": 1}]}}).encode()

    with pytest.raises(ValueError, match="records_path") as excinfo:
        remote.read_url(f"{base}/d.json", records_path="data.MISSING")
    assert "MISSING" in str(excinfo.value)


def test_remote_http_error_is_not_blamed_on_the_sandbox(route_server) -> None:
    """A real 404/500 (the server answered) must not be reported as an
    unreachable-sandbox failure — HTTPError is a URLError subclass, so it has to
    be distinguished. The 404 comes from a localhost server, never a lookup."""
    from crivo.readers import remote

    base, _ = route_server  # no routes: every path is a 404

    with pytest.raises(RuntimeError, match="404") as excinfo:
        remote.read_url(f"{base}/d.json")
    assert "unreachable" not in str(excinfo.value)


def test_read_url_stamps_the_remote_lineage_facts(http_server, tmp_path) -> None:
    """A frame read from a URL carries its own lineage on `attrs["remote"]`:
    the URL asked for, when it was fetched (UTC), the sha256 of the bytes the
    server sent, and the row and column facts of the frame built from them.
    Both the CSV branch (through the public `crivo.read`) and the JSON branch
    stamp; without it the kernel registry has nothing to carry up, and an
    answer built on remote data cannot name its source."""
    import crivo
    from crivo.readers.remote import read_url

    url = f"{http_server}/data.csv"
    served = hashlib.sha256((tmp_path / "data.csv").read_bytes()).hexdigest()
    before = datetime.now(UTC).replace(microsecond=0)
    frame = crivo.read(url)
    after = datetime.now(UTC)

    remote = frame.attrs.get("remote", {})
    assert remote.get("uri") == url
    assert remote.get("sha256") == served
    assert remote.get("rows") == 2
    assert remote.get("columns") == ["id", "note"]
    fetched = datetime.fromisoformat(remote.get("fetched_at", ""))
    assert fetched.utcoffset() == timedelta(0), "fetched_at must be UTC"
    assert before <= fetched <= after

    json_url = f"{http_server}/data.json"
    served = hashlib.sha256((tmp_path / "data.json").read_bytes()).hexdigest()
    nested = read_url(json_url, records_path="data.items")
    remote = nested.attrs.get("remote", {})
    assert remote.get("uri") == json_url
    assert remote.get("sha256") == served
    assert remote.get("rows") == 2
    assert remote.get("columns") == ["id", "city"]


def test_the_remote_hash_is_of_the_bytes_that_arrived(control_server) -> None:
    """The hash is what a re-fetch is compared against, so it must be of the
    bytes the server sent, not of the text after decoding. A Windows-1252
    ledger served as text/csv with no charset decodes as utf-8 with
    replacement characters, so hashing the decoded text gives a different
    digest than hashing the payload."""
    from crivo.readers.remote import read_url

    base, handler = control_server
    handler.content_type = "text/csv"
    handler.body = (
        "supplier_id,supplier,amount\n"
        '00412,Café Lumière,"£1,200.50"\n'
        "00077,Société Générale,N/A\n"
        "01999,Crème Brûlée Ltd,-999\n"
    ).encode("cp1252")
    served = hashlib.sha256(handler.body).hexdigest()

    frame = read_url(f"{base}/ledger.csv")

    assert len(frame) == 3
    remote = frame.attrs.get("remote", {})
    assert remote.get("sha256") == served
    assert remote.get("rows") == 3


def test_read_url_stamps_the_uri_without_its_query_or_fragment(
    control_server,
) -> None:
    """Regression for #56. A query string is where an API key rides
    (`?token=...`), and `attrs["remote"]["uri"]` travels into the kernel
    registry and on to shareable output. The stamp keeps scheme, host, port
    and path only. The fetch still sends the query, so the server answers the
    request it was asked for."""
    from crivo.readers.remote import read_url

    base, handler = control_server
    handler.content_type = "text/csv"
    handler.body = b"supplier_id,amount\n00412,1200.50\n00077,N/A\n"
    served = hashlib.sha256(handler.body).hexdigest()

    frame = read_url(f"{base}/x.csv?token=abc#frag")

    assert handler.last_path == "/x.csv?token=abc", "the fetch lost the query"
    remote = frame.attrs.get("remote", {})
    assert remote.get("uri") == f"{base}/x.csv"
    assert remote.get("sha256") == served
    # the digest is hex and could hold "abc" by chance: it is pinned to the
    # served bytes above, then taken out before the search
    stamped = json.dumps(frame.attrs, default=str).replace(served, "")
    for part in ("token", "abc", "frag"):
        assert part not in stamped, f"{part!r} reached the lineage stamp"


def test_read_url_fetches_the_full_url_but_stamps_it_without_credentials(
    monkeypatch,
) -> None:
    """Regression for #56. A `user:secret@` URL is fetched as given but
    stamped without its userinfo or query. `_fetch` is replaced by a recorder
    serving canned bytes, because urllib takes the userinfo for part of the
    host and cannot fetch this URL live (#241)."""
    from crivo.readers import remote

    body = "supplier_id,amount\n00412,1200.50\n00077,N/A\n"
    served = hashlib.sha256(body.encode()).hexdigest()
    fetched = []

    def record(url):
        fetched.append(url)
        return body, "text/csv", served

    monkeypatch.setattr(remote, "_fetch", record)
    url = "http://user:secret@127.0.0.1:9/x.csv?token=abc"

    frame = remote.read_url(url)

    assert fetched == [url], "the fetch must get the URL as given"
    stamp = frame.attrs.get("remote", {})
    assert stamp.get("uri") == "http://127.0.0.1:9/x.csv"
    stamped = json.dumps(frame.attrs, default=str).replace(served, "")
    for part in ("secret", "token", "abc"):
        assert part not in stamped, f"{part!r} reached the lineage stamp"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param(
            "http://user:secret@127.0.0.1:8000/x.csv?token=abc",
            "http://127.0.0.1:8000/x.csv",
            id="userinfo-port-query",
        ),
        pytest.param(
            "https://apitoken@h/exports/x.json",
            "https://h/exports/x.json",
            id="token-as-username",
        ),
        pytest.param("http://u:p@[::1]:8080/x", "http://[::1]:8080/x", id="ipv6"),
        pytest.param(
            "http://us%40er:p%3Ass@h/x", "http://h/x", id="percent-encoded-userinfo"
        ),
        pytest.param("http://u:p@ss@h/x", "http://h/x", id="at-in-password"),
        pytest.param("http://h/x?e=a@b.c", "http://h/x", id="at-in-query"),
        pytest.param("http://h:8080?k=v", "http://h:8080", id="no-path"),
        pytest.param(
            "https://h:8443/x.csv#frag", "https://h:8443/x.csv", id="fragment"
        ),
    ],
)
def test_strip_url_credentials_keeps_scheme_host_port_and_path(url, expected) -> None:
    """Regression for #56. Userinfo, query and fragment go; scheme, host,
    port and path stay. The host is what follows the last `@` of the netloc,
    so an `@` inside a password does not leave half the password behind."""
    from crivo.readers import remote

    assert hasattr(remote, "strip_url_credentials"), (
        "crivo.readers.remote has no strip_url_credentials"
    )
    assert remote.strip_url_credentials(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://127.0.0.1:8000/x.csv", id="ipv4-port"),
        pytest.param(
            "https://data.example.org:8443/exports/2026/ledger.json",
            id="host-port-deep-path",
        ),
        pytest.param("http://[::1]:8080/x.csv", id="ipv6-port"),
        pytest.param(
            "https://h:443/exports/q3%20ledger.csv", id="percent-encoded-path"
        ),
        pytest.param("http://h/users/@me/x.csv", id="at-in-path"),
    ],
)
def test_strip_url_credentials_leaves_a_plain_url_unchanged(url) -> None:
    """Regression for #56. A URL with nothing to strip comes back byte for
    byte: the port, a percent-encoded path and an `@` in the path all
    survive, so the stamp still names the source it was read from."""
    from crivo.readers import remote

    assert hasattr(remote, "strip_url_credentials"), (
        "crivo.readers.remote has no strip_url_credentials"
    )
    assert remote.strip_url_credentials(url) == url


def test_read_url_refuses_non_web_schemes(tmp_path) -> None:
    """`read_url` fetches http(s) only. Given a file:// URL, urllib would read
    the local file and hand it back as if it were a download; given ftp:// it
    would open an FTP session. Both are refused up front, before any read."""
    from crivo.readers.remote import read_url

    local = tmp_path / "ledger.csv"
    local.write_text("supplier_id,amount\n00412,1200.50\n")

    for url in (local.as_uri(), f"ftp://127.0.0.1:{_closed_port()}/x.csv"):
        with pytest.raises(ValueError, match="fetch refused"):
            read_url(url)


def test_read_url_refuses_a_redirect_to_ftp(route_server) -> None:
    """An http URL that redirects to ftp:// is refused with the scheme named,
    for every redirect status urllib follows (urllib's own check lets ftp
    through). A redirect that stays on the web, relative or absolute, is still
    followed: the refusal is about the scheme, not about redirects."""
    from crivo.readers.remote import read_url

    base, handler = route_server
    ftp = f"ftp://127.0.0.1:{_closed_port()}/x.csv"
    handler.routes = {
        "/ledger.csv": (200, {"Content-Type": "text/csv"}, b"id,note\n1,ok\n"),
        "/moved": (302, {"Location": "/ledger.csv"}, b""),
        "/moved-abs": (301, {"Location": f"{base}/ledger.csv"}, b""),
    }
    codes = (301, 302, 303, 307, 308)
    for code in codes:
        handler.routes[f"/hop{code}"] = (code, {"Location": ftp}, b"")

    assert read_url(f"{base}/moved")["note"].tolist() == ["ok"]
    assert read_url(f"{base}/moved-abs")["note"].tolist() == ["ok"]

    for code in codes:
        with pytest.raises(RuntimeError, match="non-web scheme"):
            read_url(f"{base}/hop{code}")


def test_read_refuses_file_and_ftp_urls(http_server, tmp_path) -> None:
    """`crivo.read("file://...")` used to fall through to the local-file
    reader and die with a FileNotFoundError for 'file:/...', a lie about what
    went wrong. A URL scheme crivo does not read is refused by name. The
    neighbours still read: an http URL, a local path, and a Windows drive path
    (no `://`, so it is a path, never a scheme)."""
    from crivo import readers

    assert len(readers.read(f"{http_server}/data.csv")) == 2
    assert len(readers.read(tmp_path / "data.csv")) == 2
    with pytest.raises(FileNotFoundError):
        readers.read("C:\\exports\\ledger.csv")

    for scheme, url in (
        ("file", (tmp_path / "data.csv").as_uri()),
        ("ftp", "ftp://127.0.0.1/exports/ledger.csv"),
    ):
        # FileNotFoundError is caught too, so the old fall-through to the
        # local-file reader fails on the assertion below that names it
        with pytest.raises((ValueError, FileNotFoundError)) as excinfo:
            readers.read(url)
        assert excinfo.type is ValueError, (
            f"{scheme}:// fell through to the local-file reader"
        )
        assert f"does not read {scheme}://" in str(excinfo.value)


def test_read_still_sends_database_urls_to_the_sql_reader(
    tmp_path, monkeypatch
) -> None:
    """The refusal of unread URL schemes sits after the SQL branch, so a
    database URL is never refused as an unknown scheme: `sqlite:///` (whose
    `.db` ending does not make it a bare file) and a `postgresql+driver://`
    URL reach the SQL reader, with a query and, by scheme alone, without one.
    The SQL reader is replaced by a recorder, so no SQLAlchemy or database is
    needed: this pins the dispatch, not the read."""
    from crivo import readers
    from crivo.readers import sql

    sentinel = object()
    calls = []

    def record(source, query=None, **kwargs):
        calls.append((source, query, kwargs))
        return sentinel

    monkeypatch.setattr(sql, "read_sql", record)

    for url, query in (
        (f"sqlite:///{tmp_path}/t.db", "select 1"),
        ("postgresql+psycopg://x/y", "select 1"),
        (f"sqlite:///{tmp_path}/t.db", None),
        ("postgresql+psycopg://x/y", None),
    ):
        scheme = url.split("://")[0]
        calls.clear()
        try:
            got = readers.read(url, query=query)
        except ValueError as exc:
            pytest.fail(f"{scheme}:// (query={query!r}) was refused: {exc}")
        assert got is sentinel, f"{scheme}:// did not reach the SQL reader"
        assert calls == [(url, query, {})]
