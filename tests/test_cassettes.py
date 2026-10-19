"""Every committed cassette replays green and holds no rows (EV3, #66).

A green replay proves the harness and the referee on recorded model outputs:
the same calls, gates, fixes, cleaned frame and scores. It proves nothing
about model behaviour, which the ledger measures. The scan is the gate that
keeps rows out of the repo, so it runs here, in CI, before a cassette reaches
dev."""

import pytest

from tests import replay

CASSETTES = sorted(replay.CASSETTES.glob("*.json"))


def test_there_is_a_cassette_to_replay():
    """An empty folder would pass both parametrized tests below vacuously."""
    assert CASSETTES, f"no cassette in {replay.CASSETTES}"


@pytest.mark.parametrize("path", CASSETTES, ids=lambda p: p.stem)
def test_a_committed_cassette_replays_green(path, tmp_path, monkeypatch):
    replay.replay(replay.load(path), tmp_path, monkeypatch)


@pytest.mark.parametrize("path", CASSETTES, ids=lambda p: p.stem)
def test_a_committed_cassette_holds_no_rows(path):
    problems = replay.scan(replay.load(path), path.stem, nbytes=path.stat().st_size)
    assert not problems, "\n".join(problems)
