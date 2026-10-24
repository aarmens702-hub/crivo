"""PreToolUse hook that limits what a specialist agent may read, write and run,
by mode (set in the agent's .claude/agents/*.md frontmatter):

    python3 guard_reads.py eval-author -> reads and searches stay on an
        allowlist (bench/ but not bench/results/, the bench tests, the
        contract, AGENTS.md, CLAUDE.md, SECURITY.md, docs/PRD.md, the plan,
        the eval tooling spec, pyproject.toml, the brief; not the plan
        inventory or the stage specs, which quote the detector); writes go
        only to the traps, the injectors, the corpus, the shape and
        degenerate generators and their tests; Bash runs only a few whole
        commands, with no shell operators: uv run pytest on bench tests inside
        a .worktrees/<n> of this checkout, and git status and git diff -- PATH,
        bare or with -C on a .worktrees/<n>, each PATH one it may read;
        SubagentHandback, which only carries its report back, goes through;
        any other tool is refused
    python3 guard_reads.py builder -> nothing names bench/traps/heldout or
        bench/traps/sealed (nor searches from above one, once it is on disk),
        the shell never writes bench/ledger.jsonl, and a paid command runs
        only with CRIVO_PROVIDER=faux on that same command

Each mode is an entry in MODES: its path lists and a check per tool. A later
mode that reuses these checks with its own lists (loop 1's attacker, say) is a
new entry, not new code. Paths are followed through links (os.path.realpath),
case-folded (APFS ignores case, and reads the long s as s) and matched on their
tail, relative to the checkout, so a file in another worktree, the main
checkout, __pycache__ or site-packages meets the same rule. The hook fails
closed: input it can't read, an unknown or missing mode, an eval-author read
or write with no path, and a crash all exit 2. Exit 2 blocks the call with one
line saying what was blocked and what is allowed. Standard library only and
Python 3.9-safe, so it runs on the system python3.

The honest limits. The hook makes a read deliberate, not impossible:
- Code the agent writes and runs (python -c, a script, a test that opens
  prompts.py) can read any file, write the ledger and reach a model.
- The Bash rules read the command's words, so a wildcard path
  (bench/traps/*/x), a variable, a word built by $'...' or $(...), cd then a
  relative name, a shell or python fed on stdin (a pipe or heredoc), or a
  launcher or writer the hook doesn't know gets past them.
- The builder's rule against searching from above a held set covers the Grep
  and Glob tools only: Bash's grep -r, rg -uu, find -exec, git grep,
  git log -p and cp -r reach a held set from above.
- rm of the ledger, mv of it elsewhere, or a folder copied over bench/
  (cp -r, rsync -a) is not blocked; git shows it.
- An eval-author search from bench/ is allowed though bench/results/ is not,
  because bench/results/ is git-ignored and ripgrep skips it. Its Glob
  patterns are brace-expanded before the check for .. and for / or ~.
- An eval-author git -C checks the folder's shape (.worktrees/<n> of this
  checkout, links followed), not that git keeps a worktree there; git run in
  a plain folder there finds the main checkout's repository. Each PATH is
  still checked.
- Each PATH of an eval-author git diff must be relative, with no .. part, and
  inside the work tree git runs in (the -C folder, or else the cwd's worktree
  or checkout) once links are followed, since git tests a path's text and a
  path outside makes git diff compare files as diff --no-index.
- An eval-author SubagentHandback goes through unchecked: it reads, writes and
  runs nothing, and its message goes only to the orchestrator.
- The hook sees only the tools its matcher sends: wire it with matcher "*" and
  limit the agent's tools: frontmatter. A builder can edit .claude/, this hook
  included.
The reviewer checks the diff (EV13), and nothing else stops these yet: 0d's
sandbox contains the analyst's kernel, not agent tools, and an OS sandbox for
code the eval-author runs is deferred to 0d (D18), not built.
"""

import glob
import json
import os
import re
import shlex
import sys
from fnmatch import fnmatchcase

# Path rules: the first that matches wins, "!" denies, and no match denies. A
# rule is relative to the checkout, or absolute when it starts with ~ or /; a
# last part of ** covers the folder and everything in it.
EVAL_AUTHOR_READS = (
    "!bench/results/**",
    "bench/**",
    "tests/test_bench_*.py",
    "docs/API-CONTRACT.md",
    "docs/PRD.md",
    "AGENTS.md",
    "CLAUDE.md",
    "SECURITY.md",
    "specs/2026-10-14-the-plan.md",
    "specs/2026-10-17-eval-tooling.md",
    "pyproject.toml",
    "~/Desktop/mailo/coop-project/**",
)
EVAL_AUTHOR_WRITES = (
    "bench/traps/**",
    "bench/corrupt.py",
    "bench/bases.py",
    "bench/corpus.py",
    "bench/shapes.py",
    "bench/degenerate.py",
    "tests/test_bench_corrupt.py",
    "tests/test_bench_bases.py",
    "tests/test_bench_shapes.py",
    "tests/test_bench_degenerate.py",
)
EVAL_AUTHOR_TESTS = (
    "tests/test_bench_corrupt.py",
    "tests/test_bench_bases.py",
    "tests/test_bench_truth.py",
    "tests/test_bench_shapes.py",
    "tests/test_bench_degenerate.py",
)

PATH_KEYS = ("file_path", "notebook_path", "path")
SEARCHES = ("Grep", "Glob")
# Anything outside these characters (; & | > < ` $ * ? [ { ~ # a newline ...)
# blocks an eval-author command before it is parsed.
PLAIN_COMMAND = re.compile(r"[A-Za-z0-9_./ '\"-]*")
HELD = re.compile(r"(?:^|[^a-z0-9_.-])traps/+(?:heldout|sealed)(?![a-z0-9_.-])")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
OPERATORS = "();<>|&`\n"
SHELLS = ("bash", "sh", "zsh", "dash", "ksh")

# Each launcher, as the words that start it, and (as a regex) its options that
# take a value; "" when none do.
UV_VALUES = (
    r"--(no-|only-)?(extra|group)|--env-file|-w|--with(-editable|-requirements)?"
    r"|--package|-p|--python(-platform)?|--(default-)?index|-i|--(extra-)?index-url"
    r"|-f|--find-links|--index-strategy|--keyring-provider|-P|--upgrade-(package|group)"
    r"|--resolution|--prerelease|--fork-strategy|--exclude-newer|--link-mode|-C"
    r"|--config-setting|--cache-dir|--color|--allow-insecure-host|--directory"
    r"|--project|--config-file|--from"
    r"|--(?!all-)[a-z-]+-package"  # each --*-package but the flag --all-package
)
LAUNCHERS = {
    ("uv", "run"): UV_VALUES,
    ("uv", "tool", "run"): UV_VALUES,
    ("uvx",): UV_VALUES,
    ("env",): r"-u|--unset|-C|--chdir",  # -S STRING is split, in launched()
    ("exec",): r"-a",
    ("nice",): r"-n|--adjustment",
    ("timeout",): r"-s|--signal|-k|--kill-after",  # then its DURATION
    ("sudo",): r"-[ugCDhprtUT]|--(user|group|close-from|chdir|host|prompt|role|type)"
    r"|--(other-user|command-timeout)",
    ("time",): "",
    ("nohup",): "",
    ("command",): "",
    ("builtin",): "",
}
# shell keywords sit in front of a command the way a launcher does
KEYWORDS = ("{", "!", "if", "then", "else", "elif", "do", "while", "until")
LAUNCHERS.update({(k,): "" for k in KEYWORDS})

# How each command writes the files it names: "last" (its last argument, or a
# copy into bench/ of a source named ledger.jsonl), "any" (any argument), "edit"
# (any argument, given an -i option) and "of" (dd's of=FILE).
WRITERS = {
    "last": ("cp", "mv", "ln", "install", "rsync"),
    "any": ("tee", "truncate"),
    "edit": ("sed", "gsed", "perl"),
    "of": ("dd",),
}
GIT_WRITERS = ("checkout", "restore")
PAID_MODULES = ("crivo", "bench.agent_run", "bench.eval")
PAID_SCRIPTS = (
    "bench/agent_run.py",
    "bench/eval.py",
    "bench/eval",
    "bench/eval/__main__.py",
)


def block(reason):
    sys.stderr.write("Blocked: " + " ".join(str(reason).split()) + "\n")
    sys.exit(2)


def fold(path):
    return path.casefold()


def resolve(path, cwd):
    """The real path, links followed, case-folded for matching."""
    return fold(os.path.realpath(os.path.join(cwd, os.path.expanduser(path))))


def checkout(cwd):
    """The checkout the agent works in: the cwd above any .worktrees/<n>."""
    parts = cwd.split("/")
    if ".worktrees" in parts:
        parts = parts[: parts.index(".worktrees")]
    return "/".join(parts) or "/"


def inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def repo_parts(real, top):
    """`real` as parts relative to the checkout, past any .worktrees/<n>/, or
    None when it sits outside the checkout."""
    if not inside(real, top):
        return None
    parts = [p for p in real[len(top) :].split("/") if p]
    return parts[2:] if parts[:1] == [".worktrees"] else parts


def worktree(real, top):
    """The .worktrees/<n> folder of the checkout `top` that `real` is or sits
    in, or None when it is in none. Both are folded real paths."""
    parts = [p for p in real[len(top) :].split("/") if p] if inside(real, top) else []
    if len(parts) < 2 or parts[0] != ".worktrees":
        return None
    return top.rstrip("/") + "/.worktrees/" + parts[1]


def matches(parts, rule):
    if rule[-1] == "**":
        rule = rule[:-1]
        if len(parts) < len(rule):
            return False
    elif len(parts) != len(rule):
        return False
    return all(fnmatchcase(p, r) for p, r in zip(parts, rule))


def allowed(real, rules, cwd):
    """Whether the first of `rules` that matches the real path allows it."""
    inner = repo_parts(real, fold(checkout(cwd)))
    for rule in rules:
        pattern = rule.lstrip("!")
        parts = inner
        if pattern[:1] in "~/":
            pattern = os.path.realpath(os.path.expanduser(pattern))
            parts = real.strip("/").split("/")
        if parts is not None and matches(parts, fold(pattern).strip("/").split("/")):
            return not rule.startswith("!")
    return False


def listing(rules):
    allow = ", ".join(r for r in rules if not r.startswith("!"))
    deny = ", ".join(r[1:] for r in rules if r.startswith("!"))
    return allow + (f" (but not {deny})" if deny else "")


def spellings(pattern, limit=256):
    """Every pattern a brace expression spells (a{b,c} is ab and ac), or None
    past `limit` of them."""
    done, todo = [], [pattern]
    while todo:
        text = todo.pop()
        group = re.search(r"\{([^{}]*)\}", text)
        if group is None:
            done.append(text)
        else:
            head, tail = text[: group.start()], text[group.end() :]
            todo += [head + alt + tail for alt in group.group(1).split(",")]
        if len(done) + len(todo) > limit:
            return None
    return done


def climbs(pattern):
    """Whether a Glob pattern leaves its root: .., or a start at / or ~."""
    found = spellings(pattern.replace("\\", ""))  # an escaped dot is still a dot
    return found is None or any(".." in p or p.startswith(("/", "~")) for p in found)


def on_list(name, mode, tool, args, cwd, key, verb):
    paths = [args[k] for k in PATH_KEYS if args.get(k)]
    if tool in SEARCHES and not args.get("path"):
        paths.append(cwd)  # a search with no path starts at the cwd
    if not paths:
        return (
            f"{tool} came with no path, and {name} mode allows only a path it can check"
        )
    if tool == "Glob" and climbs(args.get("pattern") or ""):
        return (
            f"{name} mode's Glob patterns may not use .. or start at / or ~; "
            "set path to a folder it may read instead"
        )
    for path in paths:
        if not allowed(resolve(path, cwd), mode[key], cwd):
            return f"{name} mode {verb} only {listing(mode[key])}; {path} is not on that list"
    return None


def check_read(name, mode, tool, args, cwd):
    return on_list(name, mode, tool, args, cwd, "reads", "reads and searches")


def check_write(name, mode, tool, args, cwd):
    return on_list(name, mode, tool, args, cwd, "writes", "writes")


def in_tree(path, base, tree):
    """Whether a git diff PATH, read from `base`, sits in the work tree `tree`
    as git reads it, by its text (relative, with no .. part: git compares an
    absolute path with the tree's on-disk case, so the hook can't fold it), and
    once links are followed. A PATH outside the work tree turns git diff into
    diff --no-index, a diff of whatever files it names."""
    if os.path.isabs(path) or ".." in path.split("/"):
        return False
    return inside(resolve(path, base), tree)


def runs_allowed(words, mode, cwd):
    """The whole commands eval-author mode may run: git status, and git diff on
    paths it may read, bare or with -C on a .worktrees/<n> of the checkout; and
    uv run pytest, with -q or -k NAME, on its tests inside a .worktrees/<n>, so
    a relative path from the main checkout never tests dev's bench."""
    top, base = fold(checkout(cwd)), cwd
    tree = worktree(fold(cwd), top) or top  # the work tree git runs in
    if words[:2] == ["git", "-C"] and len(words) > 3:
        base = os.path.realpath(os.path.join(cwd, words[2]))
        if worktree(fold(base), top) != fold(base):
            return False
        words, tree = ["git"] + words[3:], fold(base)  # PATHs read from there
    if words == ["git", "status"]:
        return True
    if words[:3] == ["git", "diff", "--"] and len(words) > 3:
        return all(
            in_tree(p, base, tree) and allowed(resolve(p, base), mode["reads"], cwd)
            for p in words[3:]
        )
    if words[:3] != ["uv", "run", "pytest"]:
        return False
    files, rest = 0, words[3:]
    while rest:
        word = rest.pop(0)
        if word == "-k" and rest:
            rest.pop(0)  # NAME: PLAIN_COMMAND already limits its characters
        elif word != "-q":
            real = resolve(word, cwd)
            if not worktree(real, top) or not allowed(real, mode["tests"], cwd):
                return False
            files += 1
    return files > 0


def check_command(name, mode, tool, args, cwd):
    command = args.get("command") or ""
    try:
        words = shlex.split(command) if PLAIN_COMMAND.fullmatch(command) else []
    except ValueError:
        words = []
    if not runs_allowed(words, mode, cwd):
        return (
            f"{name} mode runs only uv run pytest on {', '.join(mode['tests'])} "
            "inside a .worktrees/<n> of this checkout, with -q or -k NAME, and "
            "git status or git diff -- PATH on a path it may read, bare or as "
            "git -C on a .worktrees/<n>, each as one whole command with no "
            "shell operators"
        )
    return None


def check_handback(name, mode, tool, args, cwd):
    """SubagentHandback carries the agent's report back to the orchestrator; it
    reads, writes and runs nothing, so there is nothing to check (None lets
    the call through)."""


def refuse(name, mode, tool, args, cwd):
    tools = ", ".join(t for t in mode["tools"] if t != "*")
    return f"{name} mode allows only {tools}; {tool} is not one of them"


def held_reason(name):
    return (
        f"{name} mode stays off bench/traps/heldout and bench/traps/sealed, the "
        "sets the eval scores against; read and search bench/traps/dev instead"
    )


def names_held(path, cwd):
    path = os.path.join(cwd, os.path.expanduser(path))
    return any(
        HELD.search(fold(p)) for p in (os.path.normpath(path), os.path.realpath(path))
    )


def held_below(root, cwd):
    """Whether a held-out or sealed set exists on disk under a search root."""
    top = checkout(cwd)
    worktrees = glob.glob(os.path.join(glob.escape(top), ".worktrees", "*"))
    for base in [top, root] + worktrees:
        for name in ("heldout", "sealed"):
            held = os.path.join(base, "bench", "traps", name)
            if os.path.lexists(held) and any(
                inside(fold(p), fold(root)) for p in (held, os.path.realpath(held))
            ):
                return True
    return False


def check_held(name, mode, tool, args, cwd):
    if any(names_held(args[k], cwd) for k in PATH_KEYS if args.get(k)):
        return held_reason(name)
    if tool not in SEARCHES:
        return None
    root = os.path.join(cwd, os.path.expanduser(args.get("path") or cwd))
    if tool == "Glob":
        pattern = args.get("pattern") or ""
        if names_held(os.path.join(root, pattern), cwd):
            return held_reason(name)
        literal = []  # the folders the pattern names before its first wildcard
        for part in pattern.split("/"):
            if any(c in part for c in "*?[{"):
                break
            literal.append(part)
        root = os.path.join(root, "/".join(literal))
    root = os.path.realpath(root)
    if held_below(root, cwd):
        return f"a search from {root} reaches a held set on disk; {held_reason(name)}"
    return None


def split_words(text):
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def segments(command):
    """Each command between ; & | ( ) ` and newlines, as its de-quoted words,
    the files its > and >> redirects write, and the strings <<< feeds it."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=OPERATORS)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""  # a mid-word # is not a comment
    try:
        tokens = list(lex)
    except ValueError:  # an unclosed quote: fall back to plain words
        tokens = re.findall(r"[();<>|&`\n]+|[^\s();<>|&`]+", command)
        tokens = [t.replace("'", "").replace('"', "") for t in tokens]
    found, words, writes, feeds, redirect = [], [], [], [], None
    for token in tokens + [";"]:
        if redirect is not None:
            if ">" in redirect:
                writes.append(token)
            elif redirect == "<<<":
                feeds.append(token)
            redirect = None
        elif token and set(token) <= set(OPERATORS) and set(token) & set("<>"):
            redirect = token
            if words and words[-1].isdigit():
                words.pop()  # the 2 in 2>err is a file descriptor
        elif token and set(token) <= set(OPERATORS):
            found.append((words, writes, feeds))
            words, writes, feeds = [], [], []
        else:
            words.append(token)
    return found


def split_string(words, i):
    """env -S STRING: the words of STRING, spliced in where the option stood."""
    option = words[i]
    if option in ("-S", "--split-string"):
        value, end = (words[i + 1 : i + 2] or [""])[0], i + 2
    else:
        value, end = option.split("=", 1)[-1] if "=" in option else option[2:], i + 1
    return words[:i] + split_words(value) + words[end:]


def launched(words):
    """The env a command sets and the argv it runs, past assignments,
    launchers (uv run, env, timeout, ...) and shell keywords."""
    env, i = {}, 0
    while i < len(words):
        if ASSIGNMENT.match(words[i]):
            key, _, value = words[i].partition("=")
            env[key] = value
            i += 1
            continue
        head = [fold(os.path.basename(words[i]))] + words[i + 1 : i + 3]
        launcher = next((k for k in LAUNCHERS if list(k) == head[: len(k)]), None)
        if launcher is None:
            break
        i += len(launcher)
        while i < len(words) and words[i].startswith("-"):
            module = re.fullmatch(r"-m=?(.*)|--module(?:=(.*))?", words[i])
            if launcher[0].startswith("uv") and module:  # uv run -m M: python -m M
                value = module.group(1) or module.group(2)
                python = ["python", "-m"] + ([value] if value else [])
                words = words[:i] + python + words[i + 1 :]
                break
            if launcher == ("env",) and re.match(r"-S|--split-string", words[i]):
                words = split_string(words, i)
            else:
                takes_value = re.fullmatch(LAUNCHERS[launcher], words[i])
                i += 2 if takes_value else 1
        if launcher == ("timeout",):
            i += 1  # its DURATION
    return env, words[i:]


def shell_strings(argv, feeds):
    """The commands a shell runs from strings: bash -c STRING, eval ARGS, and
    a shell's here-string (bash <<< STRING)."""
    word = fold(os.path.basename(argv[0])) if argv else ""
    if word == "eval":
        return [" ".join(argv[1:])]
    if word not in SHELLS:
        return []
    from_string, i = False, 1
    while i < len(argv) and argv[i][:1] in ("-", "+"):
        if argv[i] in ("-o", "+o", "-O", "+O"):
            i += 1  # its option name
        elif not argv[i].startswith("--") and "c" in argv[i]:
            from_string = True
        i += 1
    return feeds + (argv[i : i + 1] if from_string else [])


def is_ledger(path):
    return fold(os.path.basename(path)) == "ledger.jsonl"


def git_subcommand(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    return args[i] if i < len(args) else ""


def writes_ledger(argv, writes):
    if any(is_ledger(p) for p in writes):
        return True
    word = fold(os.path.basename(argv[0])) if argv else ""
    args = argv[1:]
    how = next((kind for kind, names in WRITERS.items() if word in names), None)
    if word == "git" and git_subcommand(args) in GIT_WRITERS:
        how = "any"
    if how == "edit" and any(re.match(r"-[^-]*i|--in-place", a) for a in args):
        how = "any"
    if how == "any":
        return any(is_ledger(a) for a in args)
    if how == "of":
        return any(a.startswith("of=") and is_ledger(a[3:]) for a in args)
    if how == "last":
        files = [a for a in args if not a.startswith("-")] or [""]
        into_bench = fold(os.path.basename(os.path.normpath(files[-1]))) == "bench"
        sources = files[:-1]
        return is_ledger(files[-1]) or (into_bench and any(map(is_ledger, sources)))
    return False


def paid_module(module):
    module = fold(module)
    return any(module == m or module.startswith(m + ".") for m in PAID_MODULES)


def paid_script(path):
    """A script that is crivo (a crivo folder under src/ or site-packages/) or
    one of bench's agent runs."""
    path = fold(os.path.normpath(path))
    in_package = re.search(r"(^|/)(src|site-packages)/crivo(/|$)", path)
    return bool(in_package) or any(("/" + path).endswith("/" + s) for s in PAID_SCRIPTS)


def keyless(args):
    """The crivo calls that need no key: the diagnose subcommand, and a first
    --diagnose FILE that no later --di... option replaces (argparse keeps the
    last one given and accepts any prefix of the name)."""
    first, value = (args[:1] or [""])[0], (args[1:2] or [""])[0]
    if first.startswith("--diagnose="):
        first, value = "--diagnose", first.split("=", 1)[1]
    if first == "diagnose":
        return True
    replaced = any(a.startswith("--di") for a in args[1:])
    return first == "--diagnose" and value[:1] not in ("", "-") and not replaced


def paid(argv):
    """Whether argv can reach a paid model: crivo other than crivo diagnose,
    crivo-mcp, python -m crivo, and bench's agent runs."""
    word = fold(os.path.basename(argv[0])) if argv else ""
    if word in ("crivo", "crivo-mcp"):
        return word == "crivo-mcp" or not keyless(argv[1:])
    if not re.fullmatch(r"python[0-9.]*", word):
        return bool(word) and paid_script(argv[0])
    args, i = argv[1:], 0
    while i < len(args):
        arg = args[i]
        if arg == "-m" and i + 1 < len(args):
            arg, i = "-m" + args[i + 1], i + 1  # -m MODULE, read as -mMODULE
        if arg.startswith("-m"):
            module, rest = arg[2:], args[i + 1 :]
            return not keyless(rest) if module == "crivo" else paid_module(module)
        if arg == "-c":
            return False
        if arg.startswith("-"):
            i += 2 if arg in ("-X", "-W") else 1
            continue
        return paid_script(arg)
    return False


def shell_reason(name, command):
    for words, writes, feeds in segments(command):
        if any(HELD.search(fold(w)) for w in words + writes):
            return held_reason(name)
        env, argv = launched(words)
        for inner in shell_strings(argv, feeds):
            reason = shell_reason(name, inner)
            if reason:
                return reason
        if writes_ledger(argv, writes):
            return (
                f"{name} mode reads bench/ledger.jsonl but never writes it from "
                "the shell (no >, >>, tee, sed -i, cp, mv, dd, truncate or git "
                "checkout onto it); the eval runner appends its rows"
            )
        if paid(argv) and env.get("CRIVO_PROVIDER") != "faux":
            return (
                f"{name} mode runs crivo, crivo-mcp, python -m crivo, "
                "bench.agent_run and bench.eval only with CRIVO_PROVIDER=faux "
                "set on that same command, since another provider spends the "
                "owner's key; crivo diagnose FILE needs no key"
            )
    return None


def check_shell(name, mode, tool, args, cwd):
    command = args.get("command") or ""
    if HELD.search(fold(command)):
        return held_reason(name)
    return shell_reason(name, command)


# Per mode: its path lists, and a check per tool ("*": any other tool). A
# check returns why the call is blocked, or None to let it through.
MODES = {
    "eval-author": {
        "reads": EVAL_AUTHOR_READS,
        "writes": EVAL_AUTHOR_WRITES,
        "tests": EVAL_AUTHOR_TESTS,
        "tools": {
            "Read": check_read,
            "Grep": check_read,
            "Glob": check_read,
            "Write": check_write,
            "Edit": check_write,
            "MultiEdit": check_write,
            "NotebookEdit": check_write,
            "Bash": check_command,
            "SubagentHandback": check_handback,
            "*": refuse,
        },
    },
    "builder": {"tools": {"Bash": check_shell, "*": check_held}},
}


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in MODES:
        block(
            f"guard_reads.py needs a mode ({', '.join(MODES)}), got "
            f"{name or 'none'}, so it fails closed"
        )
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = None
    args = data.get("tool_input", {}) if isinstance(data, dict) else None
    tool = data.get("tool_name") if isinstance(data, dict) else None
    fields = PATH_KEYS + ("command", "pattern")
    if (
        not isinstance(args, dict)
        or not isinstance(tool, str)
        or any(not isinstance(args.get(k), (str, type(None))) for k in fields)
    ):
        block(
            "guard_reads.py could not read this tool call (it needs a JSON "
            "object with a tool_name and a tool_input object), so it fails closed"
        )
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""
    cwd = os.path.realpath(cwd or os.getcwd())
    tools = MODES[name]["tools"]
    return tools.get(tool, tools["*"])(name, MODES[name], tool, args, cwd)


try:
    reason = main()
except Exception as exc:  # noqa: BLE001 — a crash would let the call through
    reason = f"guard_reads.py failed ({type(exc).__name__}), so it fails closed"
if reason:
    block(reason)
sys.exit(0)
