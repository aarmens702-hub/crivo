"""A read guard for the kernel: refuse reads under denied paths, and any process.

`install(deny, allow)` adds one `sys.addaudithook`. After it, kernel code gets a
`PermissionError("crivo read guard: ...")` when it opens a path (any mode),
lists one (`os.listdir`, `os.scandir`, `glob.glob`), copies one
(`shutil.copyfile`, `shutil.copytree`), links, renames or replaces one away
(`os.link`, `os.rename`, `os.replace`) or imports a module from one, and that
path resolves under a deny root and not under an allow root. Renaming a
directory that holds a deny root is refused too, since that moves the root
out from under the guard. Every process start is refused whatever its path
(`subprocess.Popen`, `os.system`, the `os.exec*`, `os.posix_spawn` and
`os.spawn*` families, `os.fork`, `os.forkpty`), even with an empty deny list:
a child process is outside the hook, so `cat` of a denied file would just
work. `_posixsubprocess.fork_exec` raises no audit event, so install also
swaps it (and subprocess's own name for it) for one that refuses, and refuses
a fresh import of the module: that is how multiprocessing's spawn and
forkserver start methods start a process. Each refusal first writes one
JSON line, `{"readguard": <event>, "path": <path>}`, to fd 2, which in the
subprocess transport is the supervisor's stderr log.

Paths are matched after `os.path.realpath` (symlinks, `..`, relative paths,
the roots too), by whole path component, and case-folded where the filesystem
ignores case. Importing this module installs nothing. Bootstrap installs it
first, when `CRIVO_KERNEL_DENY_READ` is set (`install_from_env`), and a value
that does not parse denies the whole filesystem rather than nothing.

This is a speed bump, not a sandbox. What gets past it:
- metadata: `os.stat`, `os.path.exists` and the like still answer;
- native code: ctypes, and native readers such as pyarrow's CSV reader, which
  open files below Python;
- `os.open(..., dir_fd=...)`: the `open` event carries the path, not the
  directory it is relative to;
- a race: the check and the open are two steps, so a thread that swaps a
  symlink between them can get a denied file;
- tampering: any code in the process can switch it off, with ctypes or with
  one assignment to a helper here (`_refuse`, say);
- writes outside the deny roots: the kernel can write wherever its user can,
  so it can plant code that runs later, unguarded or ahead of the guard. A
  `.pth` file in site-packages runs at the next interpreter start, before
  bootstrap, and nothing logs it; an editable install's crivo.pth points at
  `src/`, so the guard's own source is writable. The working directory is one
  case: IPython puts it on the kernel's sys.path after the stdlib and just
  ahead of site-packages, so a module a cell plants there shadows a
  site-packages one for later imports; and a kernel restarted after it died
  gets a new supervisor, where `python -m` puts the cwd first, so a planted
  package can replace the supervisor or this module;
- where `_posixsubprocess` is a builtin rather than a file, re-importing it
  through importlib raises no audit event, so the original `fork_exec` comes
  back.
The deny list is not secret, and `docker exec` does not forward the variable,
so the guard runs in the subprocess transport only.
"""

import json
import os
import sys
import threading
from importlib.machinery import EXTENSION_SUFFIXES

ENV_VAR = "CRIVO_KERNEL_DENY_READ"

_PROCESS_EVENTS = frozenset(
    ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn")
    + ("os.fork", "os.forkpty")  # forkpty: how IPython's `!` starts a shell
)
_PATH_EVENTS = frozenset(
    ("open", "os.listdir", "os.scandir", "os.link", "os.rename", "import")
    + ("shutil.copyfile", "shutil.copytree", "glob.glob", "glob.glob/2")
)
_FOLDING_PLATFORMS = ("darwin", "win32")


def install(deny: list[str], allow: list[str]) -> None:
    """Refuse reads under `deny` (less `allow`) and every process start, for good.

    An audit hook cannot be removed, so this lasts until the process exits.
    """
    deny_roots = tuple(_root(p) for p in deny)
    allow_roots = tuple(_root(p) for p in allow)
    process_events, path_events = _PROCESS_EVENTS, _PATH_EVENTS
    busy = threading.local()
    _wrap_fork_exec()

    def refused(path):
        return (
            path is not None
            and _inside(path, deny_roots)
            and not _inside(path, allow_roots)
        )

    def first_refused(*paths):
        for path in paths:
            resolved = _resolve(path)
            if refused(resolved):
                return resolved
        return None

    def check(event, args):
        """The denied path this event would touch, or None."""
        if event in ("open", "os.listdir", "os.scandir", "os.link"):
            return first_refused(args[0])
        if event in ("shutil.copyfile", "shutil.copytree"):
            return first_refused(args[0], args[1])
        if event == "os.rename":  # os.replace raises it too
            src = _resolve(args[0])
            # moving a deny root's parent would carry the root out from under it
            if refused(src) or (src and _holds(src, deny_roots)):
                return src
            return None
        if event == "glob.glob":
            return first_refused(_glob_base(args[0]))
        if event == "glob.glob/2":  # root_dir: glob swallows the inner refusal
            if args[2] is None:
                return None
            return first_refused(_glob_base(args[0], args[2]))
        if event == "import":
            if args[1] is not None:  # an extension module, loaded below `open`
                return first_refused(args[1])
            return _import_source(args[0], args[2], refused)
        return None

    def hook(event, args):
        # the name first: this runs on every audit event in the process
        start = event in process_events or (
            # a fresh _posixsubprocess would bring back the unwrapped fork_exec
            event == "import" and str(args[0]).rpartition(".")[2] == "_posixsubprocess"
        )
        if not (start or event in path_events) or getattr(busy, "on", False):
            return
        busy.on = True  # anything the check calls can raise audit events
        try:
            path = _program(event, args) if start else check(event, args)
        finally:
            busy.on = False
        if start or path is not None:
            _refuse(event, path, start)

    sys.addaudithook(hook)


def install_from_env(value: str) -> None:
    """Install from the text of CRIVO_KERNEL_DENY_READ: {"deny": [...], "allow": [...]}.

    A value that does not parse, or has the wrong shape, fails closed: the
    whole filesystem is denied and one readguard line says why.
    """
    try:
        cfg = json.loads(value)
        deny, allow = cfg["deny"], cfg.get("allow", [])
        if not (_strings(deny) and _strings(allow)):
            raise TypeError("deny and allow must be lists of paths")
    except (ValueError, TypeError, KeyError, AttributeError):
        _log(
            {
                "readguard": "config",
                "path": None,
                "error": f"{ENV_VAR} did not parse; the whole filesystem is denied",
            }
        )
        deny, allow = [os.sep], []
    install(deny, allow)


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _root(path) -> tuple[str, bool]:
    resolved = os.path.realpath(os.fsdecode(path))
    folds = _folds_case(resolved)
    return (resolved.casefold() if folds else resolved), folds


def _folds_case(path: str) -> bool:
    """Whether the filesystem holding `path` ignores case. realpath keeps the
    caller's casing, so `DENIED/` would otherwise miss a `denied/` root."""
    flipped = path.swapcase()
    if flipped == path:
        return sys.platform in _FOLDING_PLATFORMS
    try:
        return os.path.samestat(os.stat(path), os.stat(flipped))
    except OSError:
        return sys.platform in _FOLDING_PLATFORMS


def _resolve(path) -> str | None:
    """An event's path, resolved; None for an fd or anything that is not a path."""
    if path is None:  # os.listdir() and os.scandir() with no argument
        path = os.curdir
    if isinstance(path, int):
        return None
    try:
        return os.path.realpath(os.fsdecode(path))
    except (TypeError, ValueError, OSError):
        return None


def _within(path: str, root: str) -> bool:
    """By whole component: `denied2/` is not under `denied`."""
    return path == root or path.startswith(
        root if root.endswith(os.sep) else root + os.sep
    )


def _inside(path: str, roots) -> bool:
    return any(_within(path.casefold() if folds else path, key) for key, folds in roots)


def _holds(path: str, roots) -> bool:
    return any(_within(key, path.casefold() if folds else path) for key, folds in roots)


def _glob_base(pattern, root_dir=None):
    """The literal directory a glob pattern starts from."""
    try:
        head = os.fsdecode(pattern)
        while any(c in head for c in "*?["):
            head = os.path.dirname(head)
        if root_dir is not None:
            head = os.path.join(os.fsdecode(root_dir), head)
    except (TypeError, ValueError):
        return None
    return head or os.curdir


def _import_source(name, sys_path, refused) -> str | None:
    """The module file or package under a deny root this import would find.

    FileFinder swallows a refused listdir, so without this a denied import
    reads as ModuleNotFoundError. os.path.exists is not an audited event.
    """
    parts = str(name).split(".")
    entries, i = sys_path, 0
    for j in range(len(parts) - 1, 0, -1):  # a submodule searches its parent
        parent = sys.modules.get(".".join(parts[:j]))
        if parent is not None:
            entries, i = getattr(parent, "__path__", None), j
            break
    leaf = parts[i]
    tails = (leaf, leaf + ".py", leaf + ".pyc", *(leaf + s for s in EXTENSION_SUFFIXES))
    for entry in entries or ():
        base = _resolve(entry)
        if not refused(base):
            continue
        for tail in tails:
            candidate = os.path.join(base, tail)
            if os.path.exists(candidate):
                return candidate
    return None


def _wrap_fork_exec() -> None:
    """Refuse `_posixsubprocess.fork_exec`, which raises no audit event.

    multiprocessing's spawn and forkserver starts call it directly (spawn is
    the macOS default), so without this they start an unguarded child.
    """
    try:
        import _posixsubprocess
    except ImportError:  # not on POSIX
        return

    def fork_exec(*args, **kwargs):
        try:
            program = os.fsdecode(args[1][0])  # executable_list
        except (TypeError, ValueError, IndexError):
            program = None
        _refuse("_posixsubprocess.fork_exec", program, True)

    _posixsubprocess.fork_exec = fork_exec
    held = sys.modules.get("subprocess")  # it keeps its own name for the original
    if held is not None and hasattr(held, "_fork_exec"):
        held._fork_exec = fork_exec


def _program(event: str, args) -> str | None:
    """What a process start would run, for the log: a path, never its arguments."""
    try:
        if event == "os.system":
            words = os.fsdecode(args[0]).split()
            return words[0] if words else None
        if event in ("os.fork", "os.forkpty"):
            return None
        return os.fsdecode(args[1] if event == "os.spawn" else args[0])
    except (TypeError, ValueError, IndexError):
        return None


def _log(line: dict) -> None:
    try:
        os.write(2, (json.dumps(line) + "\n").encode())
    except OSError:
        pass


def _refuse(event: str, path, start: bool):
    _log({"readguard": event, "path": path})
    if start:
        raise PermissionError(
            f"crivo read guard: {event} refused: no process may start"
        )
    raise PermissionError(f"crivo read guard: {event} refused: {path} is a denied path")
