"""The kernel read guard (#96, SC16a).

When CRIVO_KERNEL_DENY_READ names paths, kernel code that opens, lists or
imports from them, or starts any process, gets a PermissionError, and each
refusal is one JSON line on fd 2, where the host reads it from the
supervisor's stderr log. The guard is back after every restart.

Two harnesses:
- a real subprocess kernel, as tests/test_kernel_env.py runs one, for the
  wiring: the env allowlist, bootstrap, the stderr log and a restart;
- a plain child interpreter that calls `readguard.install` itself, for the
  route matrix. An audit hook can never be removed, so it is never installed
  in the pytest process.

It is a speed bump, not a sandbox. Every hole the module names is pinned here
as a passing test, so a docstring that claims more than the guard does fails
one: the metadata, native-reader and dir_fd holes in the HOLES matrix, the
helper-patch tamper in its own test, and the builtin `_posixsubprocess`
re-import in a skipped test on the builds where it is a hole. Bootstrap's
strip of the cwd from sys.path for the guard's own import is pinned by the
real-kernel restart-crash test. Left unpinned:
- the TOCTOU race (timing, not reproducible in a unit test);
- the cwd shadow of imports after the guard: bootstrap strips the cwd only
  for the guard's own import, so a module planted there still replaces a
  later one (the restart-crash test uses exactly that to crash bootstrap);
- a writable sys.path entry outside the cwd (a site-packages .pth file, or
  the editable crivo source itself): what a cell writes there, the next
  kernel imports.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from crivo.kernel.client import (
    DisplayItem,
    ExecResult,
    KernelClient,
    StreamOut,
    _child_env,
)

SUBPROCESS_ARGV = [sys.executable, "-m", "crivo.kernel.supervisor"]
ENV = "CRIVO_KERNEL_DENY_READ"

SENTINEL = "SENTINEL-7f3a-denied-row"
ALLOWED_TEXT = "carve-out-row-inside-the-deny-root"
PUBLIC_TEXT = "public-row-beside-the-deny-root"
MARKERS = {
    "sentinel": SENTINEL,
    "secret_name": "secret.txt",
    "allowed": ALLOWED_TEXT,
    "public": PUBLIC_TEXT,
    "lead_zero_id": "00417",
}

# A messy export: quoted thousands, sentinels, ids that lose their zeros as
# ints, an impossible date. The denied copy carries the sentinel in a row.
DENIED_CSV = (
    "account_id,holder,amount,posted\n"
    '00417,"Okafor, R.","1,204.50",2024-03-01\n'
    "00981,N/A,-,03/02/2024\n"
    f"007,{SENTINEL},(312.00),2024-13-01\n"
)
ALLOWED_CSV = 'account_id,amount\n00417,"1,204.50"\n00981,N/A\n'


@pytest.fixture(autouse=True)
def _no_deny_var_from_the_shell(monkeypatch):
    """A dev shell that exports the var must not guard a kernel some other
    test starts, nor unguard one this file expects to see guarded."""
    monkeypatch.delenv(ENV, raising=False)


def _plant(root) -> dict[str, str]:
    """A deny root with a carve-out inside it, a prefix sibling, an outside
    dir with symlinks pointing in, and somewhere to copy to."""
    denied = root / "denied"
    allowed = denied / "allowed_sub"
    denied2 = root / "denied2"
    outside = root / "outside"
    out = root / "out"
    for d in (allowed, denied / "sub", denied2, outside, out):
        d.mkdir(parents=True)
    (denied / "secret.txt").write_text(f"account_id,note\n00417,{SENTINEL}\n")
    (denied / "accounts.csv").write_text(DENIED_CSV)
    for name in ("movable.txt", "replaceable.txt", "shippable.txt"):
        (denied / name).write_text(SENTINEL)
    (denied / "sub" / "deep.txt").write_text(SENTINEL)
    (denied / "crivo_rg_leaky.py").write_text(
        f"import os\nos.environ['CRIVO_RG_LEAKY_RAN'] = '1'\nVALUE = {SENTINEL!r}\n"
    )
    (allowed / "ok.txt").write_text(ALLOWED_TEXT)
    (allowed / "ok.csv").write_text(ALLOWED_CSV)
    (allowed / "crivo_rg_ok.py").write_text(f"VALUE = {ALLOWED_TEXT!r}\n")
    (allowed / "escape.txt").symlink_to(denied / "secret.txt")
    (denied2 / "public.txt").write_text(PUBLIC_TEXT)
    (outside / "public.txt").write_text(PUBLIC_TEXT)
    (outside / "link.txt").symlink_to(denied / "secret.txt")
    (outside / "linkdir").symlink_to(denied, target_is_directory=True)
    (root / "denylink").symlink_to(denied, target_is_directory=True)
    # Three more deny roots, one per directory-move route, so a move the guard
    # wrongly allows cannot knock another route's paths over: a deny root under
    # a holder with siblings, one two levels down, and one to move itself.
    nest, nest2, nest3 = root / "nest", root / "nest2", root / "nest3"
    for vault in (
        nest / "holder" / "vault",
        nest2 / "mid" / "vault2",
        nest3 / "vault3",
    ):
        vault.mkdir(parents=True)
        (vault / "secret.txt").write_text(SENTINEL)
    for sibling in ("sibling", "sibling2"):
        (nest / sibling).mkdir()
        (nest / sibling / "notes.txt").write_text(PUBLIC_TEXT)
    return {
        "root": str(root),
        "denied": str(denied),
        "allowed": str(allowed),
        "denied2": str(denied2),
        "outside": str(outside),
        "out": str(out),
        "denylink": str(root / "denylink"),
        "nest": str(nest),
        "nest2": str(nest2),
        "nest3": str(nest3),
        "vault": str(nest / "holder" / "vault"),
        "vault2": str(nest2 / "mid" / "vault2"),
        "vault3": str(nest3 / "vault3"),
        "secret": str(denied / "secret.txt"),
        "secret_case": str(root / "DENIED" / "secret.txt"),
        "csv": str(denied / "accounts.csv"),
        "movable": str(denied / "movable.txt"),
        "replaceable": str(denied / "replaceable.txt"),
        "shippable": str(denied / "shippable.txt"),
        "leaky": str(denied / "crivo_rg_leaky.py"),
        "true": shutil.which("true") or "/usr/bin/true",
    }


# -- the plain-child harness ------------------------------------------------

# Runs each route after install and reports only an outcome and which markers
# its value held, never the value. Before each route it writes a marker line
# to fd 2, so the guard's lines can be attributed to the route that drew them.
HARNESS = r"""
import json, os, sys
cfg = json.loads(sys.argv[1])
P = cfg["paths"]
from crivo.kernel import readguard
import ctypes, glob, importlib.util, pathlib, shutil, subprocess
import multiprocessing as mp
import numpy as np
import pandas as pd
import pyarrow.csv
if cfg["install"]:
    readguard.install(cfg["deny"], cfg["allow"])
for name, src in cfg["routes"]:
    os.write(2, (json.dumps({"rg_route": name}) + "\n").encode())
    cwd, path = os.getcwd(), list(sys.path)
    ns = {
        "P": P, "os": os, "sys": sys, "ctypes": ctypes, "glob": glob,
        "importlib": importlib, "pathlib": pathlib, "shutil": shutil,
        "subprocess": subprocess, "np": np, "pd": pd, "pyarrow": pyarrow,
        "mp": mp, "readguard": readguard,
    }
    try:
        exec(compile(src, "<route " + name + ">", "exec"), ns)
        outcome = "ok"
    except PermissionError as exc:
        guard = str(exc).startswith("crivo read guard")
        outcome = "refused" if guard else "PermissionError"
    except Exception as exc:
        outcome = type(exc).__name__
    finally:
        os.chdir(cwd)
        sys.path[:] = path
    text = repr(ns.get("got"))
    has = {k: v in text for k, v in cfg["markers"].items()}
    line = json.dumps({"route": name, "outcome": outcome, "has": has})
    os.write(1, (line + "\n").encode())
"""

REFUSED = {
    "open": 'got = open(P["secret"]).read()',
    "open_binary": 'got = open(P["secret"], "rb").read()',
    "open_append": 'got = open(P["secret"], "a")',
    "open_write_new": 'got = open(P["denied"] + "/planted.txt", "w").write("x")',
    "os_open": 'got = os.read(os.open(P["secret"], os.O_RDONLY), 4096)',
    "os_open_the_root_itself": 'got = os.open(P["denied"], os.O_RDONLY)',
    "path_read_text": 'got = pathlib.Path(P["secret"]).read_text()',
    "pandas_read_csv": 'got = pd.read_csv(P["csv"], dtype=str)',
    "numpy_fromfile": 'got = np.fromfile(P["secret"], dtype=np.uint8).tobytes()',
    "listdir": 'got = os.listdir(P["denied"])',
    "listdir_nested": 'got = os.listdir(P["denied"] + "/sub")',
    "listdir_cwd_after_chdir": 'os.chdir(P["denied"])\ngot = os.listdir()',
    "scandir": 'got = [e.name for e in os.scandir(P["denied"])]',
    "path_iterdir": 'got = list(pathlib.Path(P["denied"]).iterdir())',
    "glob": 'got = glob.glob(P["denied"] + "/*")',
    "glob_root_dir": 'got = glob.glob("*", root_dir=P["denied"])',
    "copyfile_out": 'got = shutil.copyfile(P["secret"], P["out"] + "/copy.txt")',
    "copytree_out": 'got = shutil.copytree(P["denied"], P["out"] + "/tree")',
    "import_from_sys_path": (
        'sys.path.insert(0, P["denied"])\n'
        "import crivo_rg_leaky\n"
        "got = crivo_rg_leaky.VALUE"
    ),
    "import_from_file_location": (
        'spec = importlib.util.spec_from_file_location("crivo_rg_loc", P["leaky"])\n'
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "got = mod.VALUE"
    ),
    "relative_after_chdir": 'os.chdir(P["root"])\ngot = open("denied/secret.txt").read()',
    "dotdot_from_outside": 'got = open(P["outside"] + "/../denied/secret.txt").read()',
    "dotdot_relative": 'os.chdir(P["outside"])\ngot = open("../denied/secret.txt").read()',
    "dotdot_out_of_the_allow_root": 'got = open(P["allowed"] + "/../secret.txt").read()',
    "unnormalised_slashes": 'got = open(P["denied"] + "//sub/./deep.txt").read()',
    "symlink_from_outside": 'got = open(P["outside"] + "/link.txt").read()',
    "symlinked_dir_from_outside": 'got = os.listdir(P["outside"] + "/linkdir")',
    "symlink_out_of_the_allow_root": 'got = open(P["allowed"] + "/escape.txt").read()',
    "bytes_path_open": 'got = open(os.fsencode(P["secret"]), "rb").read()',
    "bytes_path_listdir": 'got = os.listdir(os.fsencode(P["denied"]))',
    # a second name for the inode, or the file itself moved, would resolve
    # outside the deny root and read freely, so the move is what is refused
    "hard_link_out": (
        'os.link(P["secret"], P["out"] + "/hard.txt")\n'
        'got = open(P["out"] + "/hard.txt").read()'
    ),
    "rename_out": (
        'os.rename(P["movable"], P["out"] + "/moved.txt")\n'
        'got = open(P["out"] + "/moved.txt").read()'
    ),
    "replace_out": (
        'os.replace(P["replaceable"], P["out"] + "/replaced.txt")\n'
        'got = open(P["out"] + "/replaced.txt").read()'
    ),
    # shutil.move catches the refused rename and falls back to copy + unlink
    "shutil_move_out": (
        'shutil.move(P["shippable"], P["out"] + "/shipped.txt")\n'
        'got = open(P["out"] + "/shipped.txt").read()'
    ),
    # moving a directory that holds a deny root moves the root out from under
    # the guard (decided on #96): the parent, a grandparent, the root itself
    "rename_the_parent_of_a_deny_root": (
        'os.rename(P["nest"] + "/holder", P["nest"] + "/holder_moved")\n'
        'got = open(P["nest"] + "/holder_moved/vault/secret.txt").read()'
    ),
    "replace_the_grandparent_of_a_deny_root": (
        'os.replace(P["nest2"], P["root"] + "/nest2_moved")\n'
        'got = open(P["root"] + "/nest2_moved/mid/vault2/secret.txt").read()'
    ),
    "rename_the_deny_root_itself": (
        'os.rename(P["vault3"], P["nest3"] + "/vault3_moved")\n'
        'got = open(P["nest3"] + "/vault3_moved/secret.txt").read()'
    ),
}

# Writes, copies, links and moves that, refused, must leave nothing behind:
# route -> (what must not exist, what must still exist or None).
LEAVES_NOTHING = {
    "open_write_new": (("denied", "planted.txt"), None),
    "copyfile_out": (("out", "copy.txt"), None),
    "copytree_out": (("out", "tree"), None),
    "hard_link_out": (("out", "hard.txt"), None),
    "rename_out": (("out", "moved.txt"), ("denied", "movable.txt")),
    "replace_out": (("out", "replaced.txt"), ("denied", "replaceable.txt")),
    "shutil_move_out": (("out", "shipped.txt"), ("denied", "shippable.txt")),
    "rename_the_parent_of_a_deny_root": (
        ("nest", "holder_moved"),
        ("vault", "secret.txt"),
    ),
    "replace_the_grandparent_of_a_deny_root": (
        ("root", "nest2_moved"),
        ("vault2", "secret.txt"),
    ),
    "rename_the_deny_root_itself": (
        ("nest3", "vault3_moved"),
        ("vault3", "secret.txt"),
    ),
}

# Listers that swallow an OSError (glob, os.walk, Path.glob) or wrap it
# (pandas through urllib). They may come back empty instead of raising; what
# matters is that nothing from the deny root comes back and the try is logged.
WITHHELD = {
    "glob_wildcard_above_the_root": 'got = glob.glob(P["root"] + "/den*/*")',
    "os_walk": 'got = list(os.walk(P["denied"]))',
    "path_glob": 'got = list(pathlib.Path(P["denied"]).glob("*"))',
    "pandas_file_url": 'got = pd.read_csv("file://" + P["csv"], dtype=str)',
}

# The legitimate reads beside each refusal (AGENTS.md, "Refusing looks like
# rigour"): route -> the marker its value must hold, or None.
PINNED = {
    "allow_root_inside_the_deny_root_reads": (
        'got = open(P["allowed"] + "/ok.txt").read()',
        "allowed",
    ),
    "allow_root_inside_the_deny_root_lists": ('got = os.listdir(P["allowed"])', None),
    "allow_root_inside_the_deny_root_imports": (
        'sys.path.insert(0, P["allowed"])\nimport crivo_rg_ok\ngot = crivo_rg_ok.VALUE',
        "allowed",
    ),
    "allow_root_pandas_keeps_leading_zeros": (
        'got = pd.read_csv(P["allowed"] + "/ok.csv", dtype=str)["account_id"].tolist()',
        "lead_zero_id",
    ),
    "prefix_sibling_reads": (
        'got = open(P["denied2"] + "/public.txt").read()',
        "public",
    ),
    "prefix_sibling_lists": ('got = os.listdir(P["denied2"])', None),
    "outside_reads": ('got = open(P["outside"] + "/public.txt").read()', "public"),
    "parent_of_the_deny_root_lists": ('got = os.listdir(P["root"])', None),
    "write_outside": (
        'with open(P["out"] + "/result.csv", "w") as f:\n    got = f.write("id\\n")',
        None,
    ),
    "pandas_roundtrip_outside": (
        (
            'pd.DataFrame({"id": ["00417"]}).to_csv(P["out"] + "/clean.csv", index=False)\n'
            'got = pd.read_csv(P["out"] + "/clean.csv", dtype=str)["id"].tolist()'
        ),
        "lead_zero_id",
    ),
    "reopen_an_allowed_fd": (
        'got = os.fdopen(os.open(P["outside"] + "/public.txt", os.O_RDONLY)).read()',
        "public",
    ),
    "fresh_imports_after_install": (
        "import fractions, openpyxl, sqlite3, statistics\ngot = statistics.median([3, 1, 2])",
        None,
    ),
    "stdlib_import_with_the_deny_root_on_sys_path": (
        (
            'sys.path.insert(0, P["denied"])\n'
            'sys.modules.pop("colorsys", None)\n'
            "import colorsys\n"
            "got = colorsys.rgb_to_hsv(1, 0, 0)"
        ),
        None,
    ),
    # links and moves are refused only when the source is in the deny root
    "link_outside_the_deny_root": (
        (
            'os.link(P["outside"] + "/public.txt", P["out"] + "/public_link.txt")\n'
            'got = open(P["out"] + "/public_link.txt").read()'
        ),
        "public",
    ),
    "rename_outside_the_deny_root": (
        (
            'with open(P["out"] + "/draft.csv", "w") as f:\n    f.write("id\\n00417\\n")\n'
            'os.rename(P["out"] + "/draft.csv", P["out"] + "/final.csv")\n'
            'got = open(P["out"] + "/final.csv").read()'
        ),
        "lead_zero_id",
    ),
    "replace_outside_the_deny_root": (
        (
            'with open(P["out"] + "/next.csv", "w") as f:\n    f.write("id\\n00417\\n")\n'
            'os.replace(P["out"] + "/next.csv", P["out"] + "/final.csv")\n'
            'got = open(P["out"] + "/final.csv").read()'
        ),
        "lead_zero_id",
    ),
    "shutil_move_outside_the_deny_root": (
        (
            'with open(P["out"] + "/tmp.csv", "w") as f:\n    f.write("id\\n00417\\n")\n'
            'shutil.move(P["out"] + "/tmp.csv", P["out"] + "/kept.csv")\n'
            'got = open(P["out"] + "/kept.csv").read()'
        ),
        "lead_zero_id",
    ),
    # a directory beside one that holds a deny root, holding none itself
    "rename_a_sibling_of_a_dir_holding_a_deny_root": (
        (
            'os.rename(P["nest"] + "/sibling", P["nest"] + "/sibling_renamed")\n'
            'got = open(P["nest"] + "/sibling_renamed/notes.txt").read()'
        ),
        "public",
    ),
    "replace_a_sibling_of_a_dir_holding_a_deny_root": (
        (
            'os.replace(P["nest"] + "/sibling2", P["nest"] + "/sibling2_moved")\n'
            'got = open(P["nest"] + "/sibling2_moved/notes.txt").read()'
        ),
        "public",
    ),
    # the legitimate twin of each lister and copier that has no pin of its own:
    # the same call on paths the guard does not touch still works
    "glob_outside_the_deny_root": ('got = glob.glob(P["outside"] + "/*")', None),
    "glob_root_dir_is_a_sibling": ('got = glob.glob("*", root_dir=P["denied2"])', None),
    "scandir_a_sibling": ('got = [e.name for e in os.scandir(P["denied2"])]', None),
    "copyfile_outside_the_deny_root": (
        (
            'shutil.copyfile(P["outside"] + "/public.txt", P["out"] + "/pub_copy.txt")\n'
            'got = open(P["out"] + "/pub_copy.txt").read()'
        ),
        "public",
    ),
    # a tree with no symlink into the deny root (copytree follows links, so
    # outside/, which has one, would be refused on the followed file)
    "copytree_a_tree_with_no_link_inward": (
        (
            'shutil.copytree(P["denied2"], P["out"] + "/tree_ok")\n'
            'got = open(P["out"] + "/tree_ok/public.txt").read()'
        ),
        "public",
    ),
    # lazy stdlib imports a cell may reach only after install; the guard must
    # not refuse the modules that themselves wrap process starts
    "lazy_import_multiprocessing_util": (
        "import multiprocessing.util\ngot = multiprocessing.util.__name__",
        None,
    ),
    "lazy_import_concurrent_futures_process": (
        "import concurrent.futures.process\ngot = concurrent.futures.process.__name__",
        None,
    ),
    "lazy_import_asyncio_subprocess": (
        "import asyncio.subprocess\ngot = asyncio.subprocess.__name__",
        None,
    ),
    "lazy_import_pty": ("import pty\ngot = pty.__name__", None),
}

CTYPES_READ = """\
libc = ctypes.CDLL(None)
libc.open.argtypes = [ctypes.c_char_p, ctypes.c_int]
libc.open.restype = ctypes.c_int
libc.read.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
libc.read.restype = ctypes.c_ssize_t
fd = libc.open(os.fsencode(P["secret"]), os.O_RDONLY)
buf = ctypes.create_string_buffer(4096)
n = libc.read(fd, buf, 4096)
libc.close(fd)
got = buf.raw[: max(n, 0)]
"""

# Known holes: route -> the marker that shows it got through, or None.
HOLES = {
    # stat is not an audited event, so existence and size still answer
    "stat_and_exists": (
        'got = (os.path.exists(P["secret"]), os.stat(P["secret"]).st_size > 0)',
        None,
    ),
    # native code never raises a Python audit event
    "ctypes_libc_read": (CTYPES_READ, "sentinel"),
    "pyarrow_native_csv_reader": (
        'got = pyarrow.csv.read_csv(P["csv"]).to_pydict()',
        "sentinel",
    ),
    # the `open` event carries the path but not the dir_fd it is relative to
    "open_relative_to_a_dir_fd": (
        (
            'os.chdir(P["outside"])\n'
            'dfd = os.open(P["root"], os.O_RDONLY)\n'
            'got = os.read(os.open("denied/secret.txt", os.O_RDONLY, dir_fd=dfd), 4096)'
        ),
        "sentinel",
    ),
}

CASE_VARIANT = {"case_variant": 'got = open(P["secret_case"]).read()'}

# Last, and execv last of all: if it is not refused the child is gone.
PROCESS = {
    "subprocess_run": 'got = subprocess.run([P["true"]]).returncode',
    "os_system": 'got = os.system(P["true"])',
    "os_popen": 'got = os.popen(P["true"]).read()',
    "os_posix_spawn": 'got = os.waitpid(os.posix_spawn(P["true"], ["true"], {}), 0)',
    "os_spawnv": 'got = os.spawnv(os.P_WAIT, P["true"], ["true"])',
    "os_fork": "pid = os.fork()\nif pid == 0:\n    os._exit(0)\ngot = os.waitpid(pid, 0)",
    "os_forkpty": (
        "pid, fd = os.forkpty()\n"
        "if pid == 0:\n    os._exit(0)\n"
        "os.close(fd)\n"
        "got = os.waitpid(pid, 0)"
    ),
    # multiprocessing's spawn and forkserver go straight to
    # _posixsubprocess.fork_exec, which raises no audit event; fork goes
    # through os.fork. A builtin target pickles by reference for spawn.
    "mp_spawn_process": (
        'p = mp.get_context("spawn").Process(target=os.getpid)\n'
        "p.start()\n"
        "p.join(60)\n"
        "got = p.exitcode"
    ),
    "mp_forkserver_process": (
        'p = mp.get_context("forkserver").Process(target=os.getpid)\n'
        "p.start()\n"
        "p.join(60)\n"
        "got = p.exitcode"
    ),
    "mp_fork_process": (
        'p = mp.get_context("fork").Process(target=os.getpid)\n'
        "p.start()\n"
        "p.join(60)\n"
        "got = p.exitcode"
    ),
    # the low-level call multiprocessing's spawn makes, reached directly: the
    # guard swaps it (and subprocess's own name for it) for one that refuses
    "subprocess_fork_exec_direct": "got = subprocess._fork_exec()",
    # a fresh `import` statement would rebind an unwrapped fork_exec; the
    # import event fires for a re-import after a pop, extension or builtin
    "posixsubprocess_plain_reimport": (
        'sys.modules.pop("_posixsubprocess", None)\n'
        "import _posixsubprocess\n"
        'got = "reimported"'
    ),
    "os_execv": 'os.execv(P["true"], ["true"])',
}

ALL_ROUTES = (
    list(REFUSED.items())
    + list(WITHHELD.items())
    + [(name, src) for name, (src, _) in PINNED.items()]
    + list(CASE_VARIANT.items())
    + [(name, src) for name, (src, _) in HOLES.items()]
    + list(PROCESS.items())
)


def _run_child(paths, *, deny, allow, routes, install=True) -> dict:
    cfg = {
        "paths": paths,
        "deny": deny,
        "allow": allow,
        "routes": routes,
        "markers": MARKERS,
        "install": install,
    }
    env = {k: v for k, v in os.environ.items() if k != ENV}
    proc = subprocess.run(
        [sys.executable, "-c", HARNESS, json.dumps(cfg)],
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
        timeout=120,
        check=False,
    )
    results = {}
    for obj in _json_lines(proc.stdout):
        if "route" in obj:
            results[obj["route"]] = obj
    logs, current = {}, None
    for obj in _json_lines(proc.stderr):
        if "rg_route" in obj:
            current = obj["rg_route"]
            logs[current] = []
        elif "readguard" in obj and current is not None:
            logs[current].append(obj)
    return {
        "rc": proc.returncode,
        "results": results,
        "logs": logs,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _json_lines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _tail(run) -> str:
    return run["stderr"][-1500:].replace(SENTINEL, "<sentinel>")


def _route(run, name) -> dict:
    assert name in run["results"], (
        f"route {name!r} never reported (child exit {run['rc']}): {_tail(run)}"
    )
    return run["results"][name]


@pytest.fixture(scope="module")
def guarded_child(tmp_path_factory):
    """One child runs every route under deny=[denied and the three vaults],
    allow=[denied/allowed_sub].

    Lazy, so a failure surfaces inside a test, not as a fixture ERROR."""
    cache = {}

    def get():
        if "run" not in cache:
            paths = _plant(tmp_path_factory.mktemp("child"))
            cache["paths"] = paths
            cache["run"] = _run_child(
                paths,
                deny=[paths[k] for k in ("denied", "vault", "vault2", "vault3")],
                allow=[paths["allowed"]],
                routes=ALL_ROUTES,
            )
        return cache["run"], cache["paths"]

    return get


@pytest.mark.parametrize("route", list(REFUSED))
def test_a_denied_route_is_refused_and_logged(guarded_child, route):
    """open in any mode, os.open, pathlib, pandas and numpy readers, listdir,
    scandir, glob, copyfile, copytree, import, a link, rename, replace or
    shutil.move out of the root, and a rename of the root or of a directory
    above it, reached by a relative path, `..`, a symlink, a bytes path or
    loose slashes: each is a PermissionError from the guard, and each writes a
    {"readguard": event, "path": ...} line."""
    run, _ = guarded_child()
    r = _route(run, route)
    assert r["outcome"] == "refused", f"{route}: {r['outcome']}"
    lines = run["logs"].get(route, [])
    assert lines, f"{route}: refused but nothing logged to fd 2"
    for line in lines:
        assert isinstance(line.get("readguard"), str) and "path" in line, line


@pytest.mark.parametrize("route", list(LEAVES_NOTHING))
def test_a_refused_write_copy_link_or_move_leaves_nothing_behind(guarded_child, route):
    """A write into the deny root, or a copy, link or move out of it, is
    refused before anything changes: no planted file, no copy, no half-copied
    tree, no second name, and a moved file is still where it was."""
    run, paths = guarded_child()
    assert _route(run, route)["outcome"] == "refused", route
    absent, present = LEAVES_NOTHING[route]
    left = os.path.join(paths[absent[0]], absent[1])
    assert not os.path.lexists(left), f"{route} left {absent[0]}/{absent[1]} behind"
    if present is not None:
        kept = os.path.join(paths[present[0]], present[1])
        assert os.path.exists(kept), f"{route} moved {present[0]}/{present[1]} away"


@pytest.mark.parametrize("route", list(WITHHELD))
def test_a_lister_that_swallows_the_refusal_returns_nothing_from_the_deny_root(
    guarded_child, route
):
    """glob over a wildcard above the root, os.walk and Path.glob catch the
    OSError and come back empty; pandas on a file:// URL wraps it in a
    URLError. Either way no name or row from the deny root comes back, and the
    attempt is still logged (caught doing so)."""
    run, _ = guarded_child()
    r = _route(run, route)
    assert not r["has"]["sentinel"], f"{route}: a denied row came back"
    assert not r["has"]["secret_name"], f"{route}: a denied file name came back"
    assert run["logs"].get(route), f"{route}: the refused read was not logged"


@pytest.mark.parametrize("route", list(PROCESS))
def test_every_process_start_is_refused_whatever_the_path(guarded_child, route):
    """A child process is outside the audit hook (`cat` of a denied file would
    just work), so every start is refused, even of /usr/bin/true. forkpty is
    how IPython's `!` shell escape starts one; multiprocessing's spawn and
    forkserver start methods, a direct subprocess._fork_exec, and a fresh
    `import _posixsubprocess` that would rebind an unwrapped fork_exec, all
    reach the low level with no process-start audit event of their own."""
    run, _ = guarded_child()
    r = _route(run, route)
    assert r["outcome"] == "refused", f"{route}: {r['outcome']}"
    assert run["logs"].get(route), f"{route}: refused but nothing logged"


@pytest.mark.parametrize("route", list(PINNED))
def test_the_legitimate_read_beside_each_refusal_still_works(guarded_child, route):
    """An allow root nested in the deny root reads, lists and imports; a
    `denied2/` sibling reads (a path component match, not a string prefix);
    outside files and the deny root's parent read and list; writes and pandas
    round trips outside work; an fd reopens; fresh stdlib and third-party
    imports work after install, even with the deny root on sys.path; and a
    link, rename, replace or shutil.move entirely outside the root works, as
    does a rename of a directory beside one that holds a deny root; glob,
    scandir, copyfile and a link-free copytree on paths the guard does not
    touch work; and the lazy stdlib modules that wrap process starts import."""
    run, _ = guarded_child()
    r = _route(run, route)
    assert r["outcome"] == "ok", f"{route}: {r['outcome']}"
    want = PINNED[route][1]
    if want is not None:
        assert r["has"][want], f"{route}: read, but not the expected content"


@pytest.mark.parametrize("route", list(HOLES))
def test_a_known_hole_stays_documented_until_it_is_closed(guarded_child, route):
    """Pinned so the module docstring cannot claim more than the guard does:
    stat and exists are not audited; ctypes and pyarrow's native CSV reader
    open files below Python; the `open` event does not carry dir_fd. Closing
    one of these on purpose means flipping its test and its line in the
    docstring."""
    run, _ = guarded_child()
    r = _route(run, route)
    assert r["outcome"] == "ok", f"{route}: {r['outcome']} (hole closed? update both)"
    want = HOLES[route][1]
    if want is not None:
        assert r["has"][want], f"{route}: got through, but read nothing"


def test_a_cell_can_switch_the_guard_off_by_patching_its_helper(tmp_path):
    """A named hole (the module docstring: "one assignment to a helper"): the
    guard's machinery runs in the same interpreter as model code, which can
    reassign `readguard._refuse` to a no-op and then read a denied file. This
    is why the guard is a speed bump, not a sandbox. Its own child, since the
    patch would unguard every later route in the shared one."""
    paths = _plant(tmp_path)
    route = 'readguard._refuse = lambda *a, **k: None\ngot = open(P["secret"]).read()'
    run = _run_child(
        paths,
        deny=[paths["denied"]],
        allow=[paths["allowed"]],
        routes=[("tamper", route)],
    )
    r = _route(run, "tamper")
    assert r["outcome"] == "ok", (
        f"the tamper was blocked (hole closed?): {r['outcome']}"
    )
    assert r["has"]["sentinel"], "patched the helper but the read returned nothing"


@pytest.mark.skipif(
    "_posixsubprocess" in sys.builtin_module_names,
    reason="a builtin _posixsubprocess re-imports with no audit event: a known "
    "hole named in readguard's docstring, not a refusal",
)
def test_reimporting_the_fork_exec_module_is_refused_where_it_is_a_file(tmp_path):
    """Where `_posixsubprocess` is an extension (the usual CPython build), a
    re-import of it through importlib after a pop raises the import event, so
    the guard refuses it before an unwrapped fork_exec can come back. A
    reload succeeds quietly (the extension is not re-initialised, so the
    wrapper stays) and the spawn after it is what is refused. On a build where
    the module is a builtin the importlib re-import raises no event and is a
    hole, so the test skips there."""
    paths = _plant(tmp_path)
    routes = {
        "importlib_reimport_then_spawn": (
            'sys.modules.pop("_posixsubprocess", None)\n'
            'importlib.import_module("_posixsubprocess")\n'
            'p = mp.get_context("spawn").Process(target=os.getpid)\n'
            "p.start()\n"
            "p.join(60)\n"
            "got = p.exitcode"
        ),
        "reload_then_spawn": (
            "import _posixsubprocess\n"
            "importlib.reload(_posixsubprocess)\n"
            'p = mp.get_context("spawn").Process(target=os.getpid)\n'
            "p.start()\n"
            "p.join(60)\n"
            "got = p.exitcode"
        ),
    }
    run = _run_child(
        paths,
        deny=[paths["denied"]],
        allow=[paths["allowed"]],
        routes=list(routes.items()),
    )
    for name in routes:
        r = _route(run, name)
        assert r["outcome"] == "refused", f"{name}: {r['outcome']}"
        assert run["logs"].get(name), f"{name}: refused but nothing logged"


def test_a_case_variant_of_the_deny_root_is_refused_where_the_fs_ignores_case(
    guarded_child,
):
    """On a case-insensitive filesystem (macOS APFS by default) `DENIED/` is
    the deny root, and os.path.realpath keeps the caller's casing, so a plain
    string compare would let it through. Refused, not pinned as a hole.
    Skipped on a case-sensitive filesystem, where the variant names no file."""
    run, paths = guarded_child()
    if not os.path.exists(paths["secret_case"]):
        pytest.skip("case-sensitive filesystem: the case variant names no file")
    r = _route(run, "case_variant")
    assert r["outcome"] == "refused", f"case variant: {r['outcome']}"
    assert not r["has"]["sentinel"]


def test_no_route_puts_a_denied_row_in_any_output(guarded_child):
    """Every route reports, and the sentinel row appears nowhere in the
    child's stdout or stderr, the guard's own log lines included."""
    run, _ = guarded_child()
    missing = [name for name, _ in ALL_ROUTES if name not in run["results"]]
    assert not missing, f"routes never reported: {missing}; {_tail(run)}"
    # booleans first, so a failure never prints the output that holds the row
    in_stdout = SENTINEL in run["stdout"]
    in_stderr = SENTINEL in run["stderr"]
    assert not in_stdout, "a denied row reached the child's stdout"
    assert not in_stderr, "a denied row reached the child's stderr"


EMPTY_DENY_READS = ("open", "listdir", "import_from_sys_path")


@pytest.fixture(scope="module")
def empty_deny_child(tmp_path_factory):
    """One child under install([], []): the reads, then every process start."""
    cache = {}

    def get():
        if "run" not in cache:
            paths = _plant(tmp_path_factory.mktemp("empty"))
            routes = [(n, REFUSED[n]) for n in EMPTY_DENY_READS]
            cache["run"] = _run_child(
                paths, deny=[], allow=[], routes=routes + list(PROCESS.items())
            )
        return cache["run"]

    return get


def test_an_empty_deny_list_refuses_no_read(empty_deny_child):
    """install([], []) leaves every read, listing and import alone."""
    run = empty_deny_child()
    for name in EMPTY_DENY_READS:
        assert _route(run, name)["outcome"] == "ok", name
        assert not run["logs"].get(name), f"{name}: nothing was refused, yet it logged"
    assert _route(run, "open")["has"]["sentinel"]
    assert _route(run, "import_from_sys_path")["has"]["sentinel"]


def test_an_empty_deny_list_still_refuses_every_process_start(empty_deny_child):
    """Process starts are refused whenever the guard is installed, whatever
    the deny list holds (decided on #96): a process is outside the hook. That
    includes multiprocessing's spawn, forkserver and fork start methods."""
    run = empty_deny_child()
    outcomes = {name: _route(run, name)["outcome"] for name in PROCESS}
    started = sorted(name for name, out in outcomes.items() if out != "refused")
    assert not started, f"started with an empty deny list: {started}"
    unlogged = sorted(name for name in PROCESS if not run["logs"].get(name))
    assert not unlogged, f"refused but not logged: {unlogged}"


# A value that does not parse fails closed (decided on #96): bootstrap installs
# the guard with the whole filesystem denied, logs one line saying so, and
# refuses process starts. Run here through the real BOOTSTRAP_SOURCE, with a
# stand-in for get_ipython, so the test does not depend on where the parsing
# lives. A marker on fd 2 separates install-time lines from the probes' lines.
MALFORMED_PROBE = r"""
import json, os, subprocess, sys
paths = json.loads(sys.argv[1])
from crivo.kernel.bootstrap import BOOTSTRAP_SOURCE

class _Shell:
    user_ns = {}
    def __getattr__(self, name):
        return lambda *args, **kwargs: None

try:
    exec(BOOTSTRAP_SOURCE, {"get_ipython": lambda: _Shell()})
    boot = "ok"
except Exception as exc:
    boot = type(exc).__name__
os.write(2, b'{"rg_route": "probes"}\n')

def attempt(fn):
    try:
        fn()
    except PermissionError as exc:
        guard = str(exc).startswith("crivo read guard")
        return "refused" if guard else "PermissionError"
    except Exception as exc:
        return type(exc).__name__
    return "ok"

seen = {
    "boot": boot,
    "open": attempt(lambda: open(paths["outside"] + "/public.txt").read()),
    "spawn": attempt(lambda: subprocess.run([paths["true"]])),
}
os.write(1, (json.dumps(seen) + "\n").encode())
"""

MALFORMED_VALUES = {
    "truncated_json": '{"deny": ["/srv/crivo/bench"], "allow": [',
    "a_bare_path": "/srv/crivo/bench",
    "deny_is_a_string_not_a_list": '{"deny": "/srv/crivo/bench", "allow": []}',
    # set but empty: json.loads("") raises, so this fails closed, not open
    "set_but_empty": "",
}


def _parse_lines(lines: list[dict]) -> list[dict]:
    """The guard's lines that say the value did not parse. The builder's
    target wording is "did not parse"; any line holding "pars" counts."""
    return [ln for ln in lines if "pars" in json.dumps(ln).lower()]


@pytest.mark.parametrize("value", list(MALFORMED_VALUES))
def test_a_malformed_deny_value_fails_closed(tmp_path, value):
    """A typo in the var must not leave the kernel unguarded: bootstrap
    denies the whole filesystem, so an open of a file no deny root names is
    refused, a process start is refused, and one line says why."""
    paths = _plant(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != ENV}
    env[ENV] = MALFORMED_VALUES[value]
    proc = subprocess.run(
        [sys.executable, "-c", MALFORMED_PROBE, json.dumps(paths)],
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
        timeout=120,
        check=False,
    )
    tail = proc.stderr[-1500:].replace(SENTINEL, "<sentinel>")
    assert proc.returncode == 0, tail
    reported = _json_lines(proc.stdout)
    assert reported, f"the probe reported nothing: {tail}"
    seen = reported[-1]
    assert (seen["open"], seen["spawn"]) == ("refused", "refused"), seen
    head, _, _ = proc.stderr.partition('{"rg_route": "probes"}')
    at_install = [o for o in _json_lines(head) if "readguard" in o]
    assert len(_parse_lines(at_install)) == 1, (
        f"want one readguard line saying the value did not parse: {at_install}"
    )


# A well-formed value, but bootstrap raises *after* the guard is installed: the
# guard must stay on. The stub shell's run_line_magic (the matplotlib inline
# magic) raises, so the imports below it never run.
FAILOPEN_PROBE = r"""
import json, os, subprocess, sys
paths = json.loads(sys.argv[1])
from crivo.kernel.bootstrap import BOOTSTRAP_SOURCE

class _Shell:
    user_ns = {}
    def run_line_magic(self, *args, **kwargs):
        raise RuntimeError("the inline magic blew up after the guard installed")
    def __getattr__(self, name):
        return lambda *args, **kwargs: None

try:
    exec(BOOTSTRAP_SOURCE, {"get_ipython": lambda: _Shell()})
    boot = "ok"
except Exception as exc:
    boot = type(exc).__name__

def attempt(fn):
    try:
        fn()
    except PermissionError as exc:
        return "refused" if str(exc).startswith("crivo read guard") else "PermissionError"
    except Exception as exc:
        return type(exc).__name__
    return "ok"

seen = {
    "boot": boot,
    "denied": attempt(lambda: open(paths["secret"]).read()),
    "allowed": attempt(lambda: open(paths["allowed"] + "/ok.txt").read()),
    "spawn": attempt(lambda: subprocess.run([paths["true"]])),
}
os.write(1, (json.dumps(seen) + "\n").encode())
"""


def test_a_bootstrap_that_crashes_after_the_guard_still_leaves_it_on(tmp_path):
    """Fail-open regression (cheap): the guard installs first in bootstrap, so
    a crash in a later line (here the inline magic) must not take it down. A
    denied open and a process start are both refused; the deny root was named,
    not the whole filesystem, so there is no parse-failure line, and the
    carve-out still reads."""
    paths = _plant(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != ENV}
    env[ENV] = json.dumps({"deny": [paths["denied"]], "allow": [paths["allowed"]]})
    proc = subprocess.run(
        [sys.executable, "-c", FAILOPEN_PROBE, json.dumps(paths)],
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
        timeout=120,
        check=False,
    )
    tail = proc.stderr[-1500:].replace(SENTINEL, "<sentinel>")
    assert proc.returncode == 0, tail
    reported = _json_lines(proc.stdout)
    assert reported, f"the probe reported nothing: {tail}"
    seen = reported[-1]
    assert seen["boot"] == "RuntimeError", (
        f"bootstrap should crash at the magic: {seen}"
    )
    assert (seen["denied"], seen["spawn"]) == ("refused", "refused"), seen
    assert seen["allowed"] == "ok", seen
    at_install = [o for o in _json_lines(proc.stderr) if "readguard" in o]
    assert not _parse_lines(at_install), (
        f"a named deny root should not log a parse: {at_install}"
    )


@pytest.mark.parametrize(
    "spelling", ["through_a_symlink", "with_dotdot_and_a_trailing_slash"]
)
def test_a_deny_root_is_matched_however_it_is_spelled(tmp_path, spelling):
    """The deny root is resolved too: a symlink to it, or a `..` path with a
    trailing slash, guards the real directory and nothing beside it."""
    paths = _plant(tmp_path)
    deny = {
        "through_a_symlink": paths["denylink"],
        "with_dotdot_and_a_trailing_slash": paths["outside"] + "/../denied/",
    }[spelling]
    routes = [
        ("open", REFUSED["open"]),
        ("outside_reads", PINNED["outside_reads"][0]),
        ("prefix_sibling_reads", PINNED["prefix_sibling_reads"][0]),
    ]
    run = _run_child(paths, deny=[deny], allow=[], routes=routes)
    assert _route(run, "open")["outcome"] == "refused"
    assert _route(run, "outside_reads")["outcome"] == "ok"
    assert _route(run, "prefix_sibling_reads")["outcome"] == "ok"


def test_importing_the_module_installs_nothing(tmp_path):
    """Only install() guards. Importing crivo.kernel.readguard (as the host
    may) leaves reads and process starts alone."""
    paths = _plant(tmp_path)
    routes = [("open", REFUSED["open"]), ("subprocess_run", PROCESS["subprocess_run"])]
    run = _run_child(paths, deny=[], allow=[], routes=routes, install=False)
    assert _route(run, "open")["outcome"] == "ok"
    assert _route(run, "subprocess_run")["outcome"] == "ok"


def test_the_var_guards_the_kernel_and_not_the_host_that_imports_crivo(tmp_path):
    """The bench host sets the var for its kernel. `import crivo` there must
    start no process and install no guard: the host still reads and spawns."""
    paths = _plant(tmp_path)
    probe = (
        "import json, subprocess, sys\n"
        "started = []\n"
        "events = ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.fork',\n"
        "          'os.forkpty', 'os.exec', 'os.spawn')\n"
        "sys.addaudithook(lambda e, a: started.append(e) if e in events else None)\n"
        "import crivo, crivo.kernel.client\n"
        "seen = list(started)\n"
        f"ok_read = {SENTINEL!r} in open({paths['secret']!r}).read()\n"
        f"rc = subprocess.run([{paths['true']!r}]).returncode\n"
        "print(json.dumps({'started': seen, 'read': ok_read, 'rc': rc}))\n"
    )
    env = dict(os.environ)
    env[ENV] = json.dumps({"deny": [paths["denied"]], "allow": []})
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1500:].replace(SENTINEL, "<sentinel>")
    seen = json.loads(proc.stdout.strip().splitlines()[-1])
    assert seen == {"started": [], "read": True, "rc": 0}


def test_the_deny_list_reaches_the_kernel_env(monkeypatch):
    """The env allowlist carries the var to the supervisor, and so to the
    kernel and its bootstrap. The value is paths, not a secret."""
    value = json.dumps({"deny": ["/srv/crivo/bench"], "allow": []})
    monkeypatch.setenv(ENV, value)
    carried = _child_env().get(ENV)  # not inline: a failure would print the env
    assert carried == value


# -- the real kernel ------------------------------------------------------------

KERNEL_PRELUDE = """\
import json, os, subprocess

def _rg_try(fn, want=None):
    try:
        got = fn()
    except PermissionError as exc:
        if str(exc).startswith("crivo read guard"):
            return "refused"
        return "PermissionError"
    except Exception as exc:
        return type(exc).__name__
    if want is not None and want not in str(got):
        return "ok, without the expected content"
    return "ok"
"""

DENIED_OPEN = ("open(P['secret']).read()", None)
ALLOWED_OPEN = ("open(P['allowed'] + '/ok.txt').read()", ALLOWED_TEXT)
SIBLING_OPEN = ("open(P['denied2'] + '/public.txt').read()", PUBLIC_TEXT)
SUBPROCESS_RUN = ("subprocess.run([P['true']]).returncode", None)


def _kernel_cell(kc, paths, body: str):
    """Runs prelude + body; the body's last line evaluates to a JSON string."""
    code = KERNEL_PRELUDE + f"P = json.loads({json.dumps(paths)!r})\n" + body
    events = list(kc.execute(code, timeout_s=120))
    result = events[-1]
    assert isinstance(result, ExecResult) and result.status == "ok", result
    return json.loads(ast.literal_eval(result.value)), events, result


def _kernel_probe(kc, paths, checks: dict[str, tuple[str, str | None]]):
    body = "json.dumps({\n"
    for name, (expr, want) in checks.items():
        body += f"    {name!r}: _rg_try(lambda: {expr}, {want!r}),\n"
    body += "})\n"
    seen, events, _ = _kernel_cell(kc, paths, body)
    return seen, events


def _leaked(events) -> bool:
    """Whether the sentinel row reached any event a cell sent back. A bool,
    so a failing assert never prints the output that holds the row."""
    parts = []
    for ev in events:
        if isinstance(ev, StreamOut):
            parts.append(ev.text)
        elif isinstance(ev, DisplayItem):
            parts.append(ev.payload)
        elif isinstance(ev, ExecResult):
            parts.append(f"{ev.value} {ev.error}")
    return SENTINEL in "\n".join(parts)


def _guard_lines(log) -> list[dict]:
    if not log.exists():
        return []
    return [o for o in _json_lines(log.read_text(errors="replace")) if "readguard" in o]


def _wait_for_guard_lines(log, done, timeout_s: float = 5.0) -> list[dict]:
    """ipykernel relays the kernel's fd 2 through a pipe thread, so a line
    can land in the log a moment after the cell's result."""
    deadline = time.monotonic() + timeout_s
    while True:
        lines = _guard_lines(log)
        if done(lines) or time.monotonic() > deadline:
            return lines
        time.sleep(0.05)


@pytest.fixture(scope="module")
def guarded_kernel(tmp_path_factory):
    """One kernel started with deny=[denied], allow=[denied/allowed_sub].

    The var is set only around start(): _child_env copies the environment
    then. Lazy, so a start failure surfaces inside a test."""
    holder = {}

    def get():
        if "kc" not in holder:
            root = tmp_path_factory.mktemp("guarded")
            paths = _plant(root)
            kc = KernelClient(workspace_dir=root / "ws", transport_argv=SUBPROCESS_ARGV)
            holder["kc"] = kc
            value = json.dumps({"deny": [paths["denied"]], "allow": [paths["allowed"]]})
            with pytest.MonkeyPatch.context() as mp:
                mp.setenv(ENV, value)
                assert kc.start().proto == 1
            holder["paths"] = paths
            holder["log"] = root / "ws" / "supervisor.stderr.log"
        return holder

    yield get
    if "kc" in holder:
        holder["kc"].close()


def test_a_cell_open_of_a_denied_file_is_refused_and_logged(guarded_kernel):
    """The issue's first case: the cell gets the guard's PermissionError, no
    denied row reaches the cell output, and the supervisor's stderr log holds
    {"readguard": "open", "path": <the denied file>}."""
    g = guarded_kernel()
    seen, events = _kernel_probe(g["kc"], g["paths"], {"denied": DENIED_OPEN})
    assert seen["denied"] == "refused", seen
    leaked = _leaked(events)
    assert not leaked, "a denied row reached the cell output"
    secret = os.path.realpath(g["paths"]["secret"])

    def logged(lines):
        return any(
            ln.get("readguard") == "open"
            and os.path.realpath(str(ln.get("path"))) == secret
            for ln in lines
        )

    lines = _wait_for_guard_lines(g["log"], logged)
    assert logged(lines), f"no open line for the denied file in the log: {lines}"


def test_a_cell_reads_the_allowed_paths_while_the_guard_is_on(guarded_kernel):
    """The carve-out inside the deny root and the `denied2/` sibling read,
    with pandas too, in the same cell where the denied file is refused."""
    g = guarded_kernel()
    checks = {
        "denied": DENIED_OPEN,
        "allowed": ALLOWED_OPEN,
        "sibling": SIBLING_OPEN,
        "allowed_csv": (
            (
                "__import__('pandas').read_csv(P['allowed'] + '/ok.csv', dtype=str)"
                "['account_id'].tolist()"
            ),
            "00417",
        ),
    }
    seen, _ = _kernel_probe(g["kc"], g["paths"], checks)
    assert seen["denied"] == "refused", f"precondition, the guard is off: {seen}"
    assert seen == {
        "denied": "refused",
        "allowed": "ok",
        "sibling": "ok",
        "allowed_csv": "ok",
    }


def test_a_cell_cannot_start_a_process(guarded_kernel):
    """subprocess.run, os.system and the notebook's own shell escape are all
    refused; `cat` of the denied file through any of them would bypass the
    hook, so no denied row reaches the cell output."""
    g = guarded_kernel()
    checks = {
        "subprocess_run": SUBPROCESS_RUN,
        "os_system": ("os.system(P['true'])", None),
        "shell_escape": ("get_ipython().system('cat ' + P['secret'])", None),
    }
    seen, events = _kernel_probe(g["kc"], g["paths"], checks)
    assert seen == {
        "subprocess_run": "refused",
        "os_system": "refused",
        "shell_escape": "refused",
    }
    leaked = _leaked(events)
    assert not leaked, "a denied row reached the cell output"

    def logged(lines):
        return {"subprocess.Popen", "os.system"} <= {
            ln.get("readguard") for ln in lines
        }

    assert logged(_wait_for_guard_lines(g["log"], logged)), "process refusals unlogged"


def test_the_bootstrap_still_runs_under_the_guard(guarded_kernel):
    """Bootstrap ran to the end with the guard on: its pandas options are set,
    the registry reports a frame, and an inline plot still renders."""
    g = guarded_kernel()
    body = (
        "import matplotlib.pyplot as plt\n"
        "import pandas as pd\n"
        "df_rg = pd.read_csv(P['allowed'] + '/ok.csv', dtype=str)\n"
        "plt.plot([1, 2, 3])\n"
        "plt.show()\n"
        "json.dumps({\n"
        "    'denied': _rg_try(lambda: open(P['secret']).read()),\n"
        "    'max_rows': pd.get_option('display.max_rows'),\n"
        "    'ids': df_rg['account_id'].tolist(),\n"
        "})\n"
    )
    seen, events, result = _kernel_cell(g["kc"], g["paths"], body)
    assert seen["denied"] == "refused", f"precondition, the guard is off: {seen}"
    assert seen["max_rows"] == 30
    assert seen["ids"] == ["00417", "00981"]
    frames = {e["name"]: e for e in result.registry}
    assert frames.get("df_rg", {}).get("shape") == [2, 2], result.registry
    assert any(isinstance(e, DisplayItem) and e.mime == "image/png" for e in events)


def test_the_guard_is_back_after_a_kernel_restart(guarded_kernel):
    """restart() reruns bootstrap, and with it install: the denied file and a
    process start are refused again, the carve-out still reads, and the new
    refusals are logged."""
    g = guarded_kernel()
    before = len(_guard_lines(g["log"]))
    g["kc"].restart()
    checks = {"denied": DENIED_OPEN, "allowed": ALLOWED_OPEN, "spawn": SUBPROCESS_RUN}
    seen, events = _kernel_probe(g["kc"], g["paths"], checks)
    assert seen == {"denied": "refused", "allowed": "ok", "spawn": "refused"}
    leaked = _leaked(events)
    assert not leaked, "a denied row reached the cell output"
    lines = _wait_for_guard_lines(g["log"], lambda ls: len(ls) >= before + 2)
    assert len(lines) >= before + 2, "the refusals after restart were not logged"


CRASH_TEXT = "planted to crash bootstrap"
CELL_MODULE_TEXT = "a-cell-module-from-the-cwd"

# Planted in the kernel's cwd by a guarded cell (the cwd is not under a deny
# root, so writing there is allowed):
# - matplotlib.py, which bootstrap imports right after the guard, so the
#   restarted bootstrap crashes there;
# - a stand-in crivo.kernel.readguard whose install does nothing: the guard
#   would be off if bootstrap imported it, which its cwd strip prevents;
# - a module of the cell's own, which must still import once the strip has
#   put sys.path back.
CWD_PLANT = {
    "matplotlib.py": f"raise RuntimeError({CRASH_TEXT!r})\n",
    "crivo/__init__.py": "",
    "crivo/kernel/__init__.py": "",
    "crivo/kernel/readguard.py": (
        "def install(deny, allow):\n    pass\n\n"
        "def install_from_env(value):\n    pass\n"
    ),
    "crivo_rg_cellmod.py": f"VALUE = {CELL_MODULE_TEXT!r}\n",
}


def test_a_bootstrap_crash_after_restart_still_leaves_the_guard_on(
    tmp_path, monkeypatch
):
    """Fail-open regression on a real kernel. The kernel's cwd is on its
    sys.path, so a cell can plant modules there. After restart:
    (a) bootstrap crashed on the planted matplotlib, but the guard installed
        first, so a denied open is still refused and the carve-out reads;
    (b) the guard bootstrap imported is the real one, not the stand-in in the
        cwd (bootstrap strips the cwd from sys.path for that import);
    (c) the supervisor log holds the bootstrap error, so the plant was reached;
    (d) a cell still imports its own module from the cwd, so the strip put
        sys.path back.
    Its own kernel, started under a chdir, so the shared guarded_kernel is
    untouched."""
    paths = _plant(tmp_path)
    monkeypatch.chdir(tmp_path)  # the kernel inherits this as its cwd
    log = tmp_path / "ws" / "supervisor.stderr.log"
    kc = KernelClient(workspace_dir=tmp_path / "ws", transport_argv=SUBPROCESS_ARGV)
    try:
        value = json.dumps({"deny": [paths["denied"]], "allow": [paths["allowed"]]})
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv(ENV, value)
            assert kc.start().proto == 1
        plant = (
            "import json, pathlib\n"
            f"for rel, text in json.loads({json.dumps(CWD_PLANT)!r}).items():\n"
            "    target = pathlib.Path(rel)\n"
            "    target.parent.mkdir(parents=True, exist_ok=True)\n"
            "    target.write_text(text)\n"
            '"planted"'
        )
        planted = list(kc.execute(plant, timeout_s=60))[-1]
        assert isinstance(planted, ExecResult) and planted.status == "ok", planted
        crashed_before = CRASH_TEXT in log.read_text(errors="replace")
        kc.restart()
        checks = {
            "denied": DENIED_OPEN,
            "allowed": ALLOWED_OPEN,
            "spawn": SUBPROCESS_RUN,
            "cell_module": ("__import__('crivo_rg_cellmod').VALUE", CELL_MODULE_TEXT),
        }
        seen, events = _kernel_probe(kc, paths, checks)
        where, _, _ = _kernel_cell(
            kc,
            paths,
            "import sys\n"
            "json.dumps(getattr(sys.modules.get('crivo.kernel.readguard'),"
            " '__file__', None))\n",
        )
    finally:
        kc.close()
    log_text = log.read_text(errors="replace")
    # (a)
    assert {k: seen[k] for k in ("denied", "allowed", "spawn")} == {
        "denied": "refused",
        "allowed": "ok",
        "spawn": "refused",
    }, seen
    assert not _leaked(events), "a denied row reached the cell output"
    # (b)
    assert where is not None, "no crivo.kernel.readguard in the restarted kernel"
    cwd = os.path.realpath(tmp_path)
    loaded = os.path.realpath(where)
    assert not loaded.startswith(cwd + os.sep), (
        f"bootstrap imported the guard from the cwd: {loaded}"
    )
    # (c)
    assert not crashed_before, "the first start already crashed: the plant came early"
    assert "bootstrap error" in log_text and CRASH_TEXT in log_text, (
        "no bootstrap error in the supervisor log: the plant was never reached"
    )
    # (d)
    assert seen["cell_module"] == "ok", (
        f"a cell could not import its own module from the cwd: {seen['cell_module']}"
    )


def test_without_the_var_a_cell_reads_and_spawns_as_before(tmp_path):
    """No var, no guard: the same cells read the file, list the dir and start
    processes, and the log holds no guard line."""
    paths = _plant(tmp_path)
    kc = KernelClient(workspace_dir=tmp_path / "ws", transport_argv=SUBPROCESS_ARGV)
    try:
        assert kc.start().proto == 1
        checks = {
            "denied": ("open(P['secret']).read()", SENTINEL),
            "listdir": ("os.listdir(P['denied'])", "secret.txt"),
            "spawn": SUBPROCESS_RUN,
            "shell_escape": ("get_ipython().system(P['true'])", None),
        }
        seen, _ = _kernel_probe(kc, paths, checks)
    finally:
        kc.close()
    assert seen == {
        "denied": "ok",
        "listdir": "ok",
        "spawn": "ok",
        "shell_escape": "ok",
    }
    assert _guard_lines(tmp_path / "ws" / "supervisor.stderr.log") == []
