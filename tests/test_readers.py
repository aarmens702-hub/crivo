"""The `readers` package: `aa.read` dispatches a source — a path, a database, a
URL — to the right reader, keeping the sentinel-safe discipline throughout."""

import re

import pandas as pd
import pytest

import crivo


def test_readers_read_a_local_csv_keeps_sentinels(tmp_path) -> None:
    """The baseline: a local path still reads, and 'N/A' survives as a string
    the detection engine can see (not silently coerced to NaN)."""
    from crivo import readers

    path = tmp_path / "d.csv"
    pd.DataFrame({"id": ["1", "2", "3"], "val": ["10", "N/A", "30"]}).to_csv(
        path, index=False
    )

    df = readers.read(path)

    assert list(df.columns) == ["id", "val"]
    assert (df["val"].astype(str) == "N/A").sum() == 1


def test_short_cp1252_file_falls_back_to_cp1252(tmp_path) -> None:
    """A short file whose only non-utf-8 byte lands in the last 3 bytes must
    still fall back to cp1252 — the 8KB-boundary forgiveness only applies when
    the sample was actually truncated, not to a genuine short-file bad byte."""
    from crivo import checkup

    path = tmp_path / "short.csv"
    # £ (0xA3 in cp1252) three bytes from the end
    path.write_bytes("name,price\nrow,£5\n".encode("cp1252"))

    df = checkup.load(path)

    assert list(df.columns) == ["name", "price"]
    assert df.attrs.get("encoding") == "cp1252"


def test_cloud_schemes_fail_clearly_not_as_a_mangled_local_path() -> None:
    """s3://gs://az:// are deferred — the user must get a clear message, not a
    FileNotFoundError from the file reader treating 's3://…' as a local path."""
    import pytest

    from crivo import readers

    for uri in ("s3://bucket/key.csv", "gs://bucket/key.csv", "az://c/key.csv"):
        with pytest.raises(NotImplementedError, match="cloud"):
            readers.read(uri)


def test_compressed_csv_gets_the_same_sniff_as_a_plain_csv(tmp_path) -> None:
    """A semicolon .csv.gz must read like a semicolon .csv — the compressed path
    must not bypass checkup.load's delimiter sniff and collapse 3 columns to 1."""
    import gzip

    from crivo.readers import files

    path = tmp_path / "semi.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("id;amount;note\n1;1000;ok\n2;2000;N/A\n")

    df = files.read_file(path)

    assert list(df.columns) == ["id", "amount", "note"]
    assert (df["note"].astype(str) == "N/A").sum() == 1


def vendor_payments() -> pd.DataFrame:
    """12 rows of a vendor-payments export as a Spark job writes it: vendor
    ids zero-padded to 5 digits, money as strings with a currency sign and
    thousands separators, an "N/A" and a "-" sentinel, and the region the
    hive layout partitions on (7 North rows, 5 South)."""
    return pd.DataFrame(
        {
            "vendor_id": [f"{i:05d}" for i in (7, 8, 9, 10, 11, 12, 103, 104, 1001)]
            + ["01002", "01003", "20004"],
            "amount": ["$1,300.50", "$85.00", "N/A", "$12,004.10", "-", "$7.25"] * 2,
            "region": ["North"] * 7 + ["South"] * 5,
        }
    )


def build_directory(directory, entries) -> None:
    """Lay out `directory` from relative entries: a trailing "/" makes an
    empty folder, a ".parquet" name gets a real part, anything else is an
    empty marker file (_SUCCESS, .DS_Store, a .crc checksum)."""
    directory.mkdir()
    for entry in entries:
        target = directory / entry
        if entry.endswith("/"):
            target.mkdir(parents=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.endswith(".parquet"):
            vendor_payments().to_parquet(target, index=False)
        else:
            target.touch()


# the bookkeeping a Spark or Hadoop job leaves beside (or instead of) its parts;
# pyarrow skips every name that starts with "_" or "."
SPARK_MARKERS = ["_SUCCESS", ".DS_Store", "._SUCCESS.crc", "_committed_0"]


@pytest.mark.parametrize(
    "surface", [crivo.read, crivo.diagnose], ids=["read", "diagnose"]
)
@pytest.mark.parametrize(
    "dirname, entries",
    [
        ("exports", []),
        ("spend.parquet", ["_SUCCESS"]),
        ("spend.parquet", SPARK_MARKERS),
        ("spend", ["region=north/"]),
        ("spend.parquet", ["_temporary/0/part-0.parquet"]),
    ],
    ids=[
        "empty",
        "success-marker-only",
        "markers-and-hidden-files",
        "empty-hive-partition",
        "uncommitted-temporary-part",
    ],
)
def test_a_directory_with_no_parquet_parts_is_refused_not_clean(
    tmp_path, surface, dirname, entries
) -> None:
    """Regression for #44. A directory with no parquet parts pyarrow will
    read (empty, a Spark output holding only _SUCCESS and its checksums, an
    empty hive partition, or a job that died with its part still under
    _temporary/) reads as a 0 x 0 frame, and `crivo.diagnose` called it
    clean: 0 rows, no findings. The CLI refuses these since #14; the library
    must too, naming the directory. The Spark and hive folders below are the
    twins it must still read."""
    directory = tmp_path / dirname
    build_directory(directory, entries)

    with pytest.raises(ValueError, match=rf"{re.escape(dirname)}: no parquet parts"):
        surface(directory)


@pytest.mark.parametrize("dirname", ["spend", "spend.parquet"])
def test_a_spark_folder_with_markers_beside_its_parts_reads_every_row(
    tmp_path, dirname
) -> None:
    """Regression for #44. The legitimate twin of the refusal above: the same
    markers and hidden checksums, beside two uneven parts, read every row
    through `crivo.read` and `crivo.diagnose`, leading zeros intact."""
    frame = vendor_payments()
    directory = tmp_path / dirname
    build_directory(directory, [*SPARK_MARKERS, ".part-00000.parquet.crc"])
    frame.iloc[:7].to_parquet(directory / "part-00000.parquet", index=False)
    frame.iloc[7:].to_parquet(directory / "part-00001.parquet", index=False)

    out = crivo.read(directory)

    assert len(out) == 12  # 7 + 5
    assert sorted(out["vendor_id"]) == sorted(frame["vendor_id"])
    assert crivo.diagnose(directory).to_dict()["rows"] == 12


@pytest.mark.parametrize("dirname", ["spend", "spend.parquet"])
def test_a_hive_partitioned_folder_reads_every_row(tmp_path, dirname) -> None:
    """Regression for #44. The twin of the empty-partition refusal: a hive
    layout (spend/region=north/part-0.parquet, region=south/...) is a
    directory whose parts sit one level down, and it still reads whole. The
    region comes back as a partition column, so only rows and ids are
    pinned here."""
    frame = vendor_payments()
    directory = tmp_path / dirname
    directory.mkdir()
    (directory / "_SUCCESS").touch()
    for region, part in frame.groupby("region"):
        folder = directory / f"region={region.lower()}"
        folder.mkdir()
        part.drop(columns="region").to_parquet(folder / "part-0.parquet", index=False)

    out = crivo.read(directory)

    assert len(out) == 12  # 7 north + 5 south
    assert sorted(out["vendor_id"]) == sorted(frame["vendor_id"])
    assert crivo.diagnose(directory).to_dict()["rows"] == 12
