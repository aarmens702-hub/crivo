"""Bootstrap cell source, executed at kernel start and after every restart (R16).

Everything defined here is underscore-prefixed so the registry probe (which
skips underscored names) never lists its own machinery.
"""

BOOTSTRAP_SOURCE = '''
# First, so no error below can skip it: the read guard (SC16a), a speed bump,
# not a sandbox (crivo.kernel.readguard names what gets past it). Imported with
# the cwd off sys.path, so a package planted there cannot stand in for it. A
# value that does not parse denies everything, imports below included
import os as _aa_os
import sys as _aa_sys

if "CRIVO_KERNEL_DENY_READ" in _aa_os.environ:
    _aa_path, _aa_cwd = list(_aa_sys.path), _aa_os.path.realpath(_aa_os.getcwd())
    _aa_sys.path[:] = [
        _p for _p in _aa_path if _aa_os.path.realpath(_p or ".") != _aa_cwd
    ]
    try:
        from crivo.kernel import readguard as _aa_readguard
    finally:
        _aa_sys.path[:] = _aa_path
    _aa_readguard.install_from_env(_aa_os.environ["CRIVO_KERNEL_DENY_READ"])

import matplotlib as _aa_mpl
_aa_mpl.use("Agg")
get_ipython().run_line_magic("matplotlib", "inline")

import pandas as _aa_pd
_aa_pd.set_option("display.max_rows", 30)
_aa_pd.set_option("display.max_columns", 20)
_aa_pd.set_option("display.width", 200)


def _analyst_registry_json():
    """Raw facts about user variables (R12): name, type, shape/len, mem_mb."""
    import json as _json
    import sys as _sys
    import types as _types

    _skip = {"In", "Out", "exit", "quit", "open", "get_ipython"}
    entries, omitted = [], 0
    for _name, _val in list(get_ipython().user_ns.items()):
        if _name.startswith("_") or _name in _skip:
            continue
        if isinstance(_val, _types.ModuleType) or callable(_val):
            continue
        _entry = {"name": _name, "type": type(_val).__name__}
        _remote = getattr(_val, "attrs", {})
        if isinstance(_remote, dict) and isinstance(_remote.get("remote"), dict):
            # R12: a frame read from a URL grounds in lineage, so its stamp
            # rides the registry up, but only while the frame still has the
            # fetched rows and columns. A same-shape derivative (a copy, a
            # sort, a cast, cleaned values) still carries it; the Stage 1
            # registry rebuild owns that gap
            _stamp = _remote["remote"]
            try:
                _same = "rows" not in _stamp or len(_val) == _stamp["rows"]
            except TypeError:
                _same = False
            if "columns" in _stamp:
                _cols = getattr(_val, "columns", None)  # a Series has none
                _same = (
                    _same
                    and _cols is not None
                    and ([str(_c) for _c in _cols] == _stamp["columns"])
                )
            if _same:
                _entry["remote"] = _stamp
        _shape = getattr(_val, "shape", None)
        if _shape is not None:
            _entry["shape"] = list(_shape)
        elif hasattr(_val, "__len__"):
            try:
                _entry["len"] = len(_val)
            except TypeError:
                pass
        try:
            if hasattr(_val, "memory_usage"):
                _mem = _val.memory_usage(deep=True)
                _mem = int(_mem.sum()) if hasattr(_mem, "sum") else int(_mem)
            else:
                _mem = _sys.getsizeof(_val)
            _entry["mem_mb"] = round(_mem / 1048576, 2)
        except Exception:
            pass
        if len(entries) < 50:
            entries.append(_entry)
        else:
            omitted += 1
    return _json.dumps({"entries": entries, "omitted": omitted})
'''
