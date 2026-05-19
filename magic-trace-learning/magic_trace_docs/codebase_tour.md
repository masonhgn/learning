# A tour of the magic-trace codebase

This is a deep-dive into the internals of `magic-trace`. It is not a
user guide — `README.md` covers installation and how to drive the tool
from the command line. This document is for someone opening the source
tree for the first time and wanting to understand *how it works*.

The tour builds in layers:

1. What magic-trace is, and the core idea.
2. A bird's-eye view of the runtime architecture.
3. The repository layout.
4. A top-down walk through the CLI surface.
5. The capture pipeline (how `perf` is driven).
6. The decode + write pipeline (how raw trace data becomes a
   `.fxt.gz`).
7. A full end-to-end narrative of `magic-trace attach -pid X`.
8. Pointers for going further.

Every section cites concrete files and line numbers — jump into the
source freely as you read.

---

## 1. What magic-trace is

magic-trace samples *every function call* in a running process with
~40 ns resolution and 2–10% overhead, and produces an interactive
timeline you explore in a Perfetto-based UI.

The trick is Intel Processor Trace (PT). The CPU continuously emits a
compact stream of every taken branch into a hardware ring buffer.
Unlike `perf`'s usual sampling, this is not statistical — it's a
complete record of control flow. The ring buffer holds roughly the
last ~10 ms of execution. On some trigger (Ctrl+C, a hit on a chosen
function), the buffer is dumped to disk. All the heavy lifting of
decoding those branch packets back into call stacks happens
*offline*, after the process has already moved on.

From README.md:21-41, the headline properties are:

- 2–10% overhead (measured in the wiki),
- captures every function call at ~40 ns resolution,
- renders ~10 ms of call-stack history.

magic-trace doesn't reimplement Intel PT decoding — it shells out to
`perf record` for capture and `perf script` for decoding, then
interprets the textual output. The bulk of the codebase is OCaml
gluing those subprocesses together, reconstructing per-thread call
stacks, and emitting a Fuchsia Trace Format (`.fxt`) file that
Perfetto / `magic-trace.org` can load.

Two snapshot triggers are supported:

- **Ctrl+C / exit**: the default. Stop the tracer, snapshot what's in
  the ring buffer.
- **Function-call breakpoint**: arm a hardware breakpoint on a named
  symbol. When the target process calls it, snapshot. The canonical
  case is leaving an empty `magic_trace_stop_indicator` function in
  production code that you can snap to at interesting moments.

---

## 2. Bird's-eye architecture

```
  target process ────────────────────────────────────────┐
                   │                                     │
                   │  (ptrace.fork_exec_stopped for `run` │
                   │   mode; plain perf -p PID for        │
                   │   `attach` mode)                     │
                   ▼                                     ▼
              perf record ────────► Intel PT ring buffer (mmap)
                   ▲                                     │
   magic-trace ────┤  ctlfd pipe    (snapshot\n/stop\n)  │
   (signal handler│  or SIGUSR2/   ◄────────────────────┘
    + breakpoint  │   SIGTERM)                           │
    poller)       │                                      ▼
                  │                                 perf.data
                  │                                      │
                  │                                perf script
                  └───────────────────────────────────── │
                                                         ▼
                                            Perf_decode.to_events
                                                         │ pipe of Event.t
                                                         ▼
                                                  Trace_writer
                                                         │ duration spans
                                                         │ + compressed callstacks
                                                         ▼
                                            Tracing_zero.Writer
                                                         │
                                                         ▼
                                                  trace.fxt.gz
```

There are two backends behind the same `Backend_intf.S` interface
(`src/backend_intf.ml:7-56`):

- `Perf_tool_backend` — the default; forks and talks to `perf`.
- `direct_backend/` — an experimental in-process capture using
  `perf_event_open` ioctls and `libipt` directly. It is not currently
  wired into the CLI; see `direct_backend/README.md` for its history
  and limitations (missing vDSO handling, single-threaded, etc.).

Four logical stages: **orchestrate → record → trigger → decode+write**.

---

## 3. Repository layout

- `bin/magic_trace_bin.ml` — three-line binary entry.
- `lib/magic_trace/` — public library wrapper plus C stubs for the TSC
  and the `magic_trace_stop_indicator` symbol you can call from
  instrumented programs.
- `src/` — everything interesting: CLI, perf driver, decoder, trace
  writer, ELF parsing, callstack compression, …
- `direct_backend/` — experimental second backend. Reference-quality
  code that bypasses the `perf` binary entirely.
- `vendor/tracing/` — Jane Street's Fuchsia Trace Format writer,
  vendored in. magic-trace uses `Tracing_zero.Writer` to emit `.fxt`.
- `vendor/fzf/` — tiny FFI wrapper around the `fzf` binary; used by
  `-trigger ?` and `-pid` fuzzy pickers.
- `test/` — inline-expect tests plus a generous collection of golden
  `.perf` fixtures covering page faults, kernel tracing, OCaml
  exceptions, decode errors, and sampling mode.

---

## 4. Top-down tour

### 4.1 Entry point — `bin/magic_trace_bin.ml`

The binary does nothing except hand off to the library:

```ocaml
(* bin/magic_trace_bin.ml:1-3 *)
open! Core

let () = Command_unix.run Magic_trace_lib.Trace.command
```

All the real logic lives in `src/`, published as the
`magic-trace.magic_trace_lib` library.

### 4.2 The command tree — `src/trace.ml`

`Trace.command` is a `Command.group` of three subcommands, plus the
functor that instantiates them against a `Backend_intf.S`:

```ocaml
(* src/trace.ml:790-799 *)
let commands =
  [ "run", run_command; "attach", attach_command; "decode", decode_command ]
;;

end

module Perf_tool_commands = Make_commands (Perf_tool_backend)

let command =
  let commands = Perf_tool_commands.commands in
  Command.group ~summary:"Magical tracing based on Intel Processor Trace" commands
;;
```

`Make_commands (Backend : Backend_intf.S)` is a functor (around
`src/trace.ml:220`) that builds the three subcommands *parameterized
over the backend*. In production only `Perf_tool_backend` is plugged
in, but the functor shape keeps the seams clean enough that the
`direct_backend/` could be wired in with no changes to the CLI code.

### 4.3 The three subcommands

**`run`** (`src/trace.ml:580-640`) spawns a child under the tracer.
`run_and_record` (`src/trace.ml:438-457`) forks the child already in a
stopped state (via `Ptrace.fork_exec_stopped`), attaches `perf` to it,
then calls `Ptrace.resume` to let it go. On Ctrl+C or the trigger
firing, it snapshots and decodes.

**`attach`** (`src/trace.ml:684-750`) attaches to an already-running
PID. If `-pid` is omitted and `fzf` is in `PATH`, it pops a fuzzy
picker (`src/trace.ml:642-682`). The executable path is read from
`/proc/PID/exe` (`src/trace.ml:720-723`) so ELF symbols can be loaded.

**`decode`** (`src/trace.ml:752-788`) is the expert escape hatch: take
a `perf.data` you already have and re-run only the decode + write
stage, skipping capture entirely. Useful for debugging the trace
writer against a saved fixture.

The `run` and `attach` paths converge on `attach` (lowercase, the
function defined at `src/trace.ml:316-427`), which is where the
interesting control flow actually lives. We'll come back to it.

### 4.4 Flag categories

magic-trace's flags fan out into five orthogonal axes. Each has a
small module dedicated to it:

**When to snapshot** — `src/when_to_snapshot.ml:3-5`:

```ocaml
type t =
  | Magic_trace_or_the_application_terminates
  | Application_calls_a_function of Symbol_selection.t
```

Set via `-trigger`. No flag ⇒ snapshot on Ctrl+C or exit. `-trigger
SYMBOL` ⇒ snapshot on breakpoint hit. `-trigger .` is shorthand for
`magic_trace_stop_indicator`. `-trigger ?` pops an fzf picker.

**Collection mode** — `src/collection_mode.ml:51-53`:

```ocaml
type t =
  | Intel_processor_trace of { extra_events : Event.t list }
  | Stacktrace_sampling of { extra_events : Event.t list }
```

`-sampling` picks the sampling fallback; otherwise Intel PT is chosen
if `/sys/bus/event_source/devices/intel_pt` exists
(`src/collection_mode.ml:60-70`).

**Callgraph mode** — `src/callgraph_mode.ml:3-7`. `lbr` / `lbr-no-stitch`
/ `fp` / `dwarf`. This only matters under sampling — Intel PT traces
every branch, so it doesn't need a callgraph reconstruction strategy.
The values become `perf record --call-graph {lbr,fp,dwarf}` arguments
at `src/callgraph_mode.ml:32-37`.

**Trace scope** — `src/trace_scope.ml:3-7`:

```ocaml
type t =
  | Userspace
  | Kernel
  | Userspace_and_kernel
```

Defaults to userspace; `-trace-include-kernel` and `-trace-kernel-only`
require root. The variants map to perf's `/u`, `/k`, `/uk` selectors
(used at `src/perf_tool_backend.ml:226-230`).

**Range filter** — `src/trace_filter.ml:28-37`. `-filter "(START STOP)"`
clips the output to events between two function calls. Both endpoints
support the same fuzzy-picker syntax as `-trigger`.

**Symbol selection** — `src/symbol_selection.ml:8-15`:

```ocaml
let of_command_string s =
  match s with
  | "?" -> Use_fzf_to_select_one `File_or_func
  | "line:?" -> Use_fzf_to_select_one `File
  | "symbol:?" -> Use_fzf_to_select_one `Func
  | "." -> User_selected Magic_trace.Private.stop_symbol
  | s -> User_selected s
;;
```

Note that `symbol:?` / `line:?` / `?` are three distinct fuzzy modes —
all functions, just file:line pairs, or both mixed.

---

## 5. Capture pipeline

The core of capture is the `Make_commands (Backend)` functor's
`attach` function at `src/trace.ml:316-427`. This is worth reading in
full; we'll hit the highlights.

### 5.1 The backend interface

Everything the CLI demands from a backend fits in `Backend_intf.S`:

```ocaml
(* src/backend_intf.ml:14-36 *)
module Recording : sig
  module Data : sig type t [@@deriving sexp] end
  type t

  val attach_and_record
    :  Record_opts.t
    -> debug_print_perf_commands:bool
    -> subcommand:Subcommand.t
    -> when_to_snapshot:When_to_snapshot.t
    -> trace_scope:Trace_scope.t
    -> multi_snapshot:bool
    -> timer_resolution:Timer_resolution.t
    -> record_dir:string
    -> collection_mode:Collection_mode.t
    -> Pid.t list
    -> (t * Data.t) Deferred.Or_error.t

  val maybe_take_snapshot : t -> source:[ `ctrl_c | `function_call ] -> unit
  val finish_recording : t -> unit Deferred.Or_error.t
end
```

Three surfaces: start recording, take a snapshot, shut down. Plus
`decode_events` for the offline stage. `Perf_tool_backend` implements
all of these by shelling out to `perf`.

### 5.2 Building the perf argv

The single most informative piece of code in the capture pipeline is
the `argv` that magic-trace constructs for `perf record`:

```ocaml
(* src/perf_tool_backend.ml:507-520 *)
let argv =
  List.concat
    [ [ perf; "record"; "-o"; record_dir ^/ "perf.data"; "--timestamp" ]
    ; event_opts
    ; overwrite_opts
    ; switch_opts
    ; thread_opts
    ; pid_opt
    ; control_opt
    ; kcore_opts
    ; snapshot_size_opt
    ; Callgraph_mode.to_perf_record_args selected_callgraph_mode
    ]
in
```

- `event_opts` resolves to `--event=intel_pt/cyc=1,cyc_thresh=1,mtc_period=0/u`
  (or a similar string shaped by `Timer_resolution`) for Intel PT, or
  `--event=cycles/freq=10000/u` for sampling. Construction is at
  `src/perf_tool_backend.ml:307-332`.
- `overwrite_opts` → `--overwrite` for sampling mode (so the ring
  buffer behaves like Intel PT's does).
- `switch_opts` → `--switch-output=signal` when `-multi-snapshot` is
  set.
- `pid_opt` is the comma-separated list of target PIDs.
- `control_opt` → `--control=fd:RX,TX` when the kernel supports
  ctlfd (more below).
- `snapshot_size_opt` → `-m,NUM_PAGES`. See `src/pow2_pages.ml:15-48`
  for the rounding-to-power-of-two logic.
- `kcore_opts` adds kernel-core data when tracing the kernel.

### 5.3 Attaching to the target

`attach` mode just passes `-p PID` to perf — there's no additional
tracing infrastructure needed on the target. `run` mode is more
interesting:

```ocaml
(* src/ptrace.ml:8-29 *)
let fork_exec_stopped ~prog ~argv () =
  let pr_set_pdeathsig = Or_error.ok_exn Linux_ext.pr_set_pdeathsig in
  match Core_unix.fork () with
  | `In_the_child ->
    (* don't outlive the magic-trace parent process. *)
    pr_set_pdeathsig Signal.kill;
    (* this is how we ensure the process is started in a stopped state: we mark ourselves
       as traced, so that we receive a `SIGTRAP` after `exec*` completes. *)
    if not (ptrace_traceme ()) then sys_exit 126;
    never_returns
      (try Core_unix.exec ~prog ~argv () with
       | _ -> sys_exit 127)
  | `In_the_parent pid ->
    (match Core_unix.wait_untraced (`Pid pid) with
     | _, Error (`Stop _) -> pid
     | _, result -> raise_s [%message "expected child to stop but it did not" ...])
```

The child `PTRACE_TRACEME`s itself and `exec`s. Linux delivers
`SIGTRAP` on `exec`, which stops it. The parent waits for the stop,
hands the PID to `perf -p`, then `Ptrace.resume` (`src/ptrace.ml:31`,
a `PTRACE_DETACH`) lets the child run under perf's supervision. This
guarantees no instructions execute before Intel PT is armed.

### 5.4 The trigger

When `-trigger` names a function, magic-trace installs a hardware
breakpoint on its address. The mechanism is `perf_event_open` with
`type = PERF_TYPE_BREAKPOINT` and `bp_type = HW_BREAKPOINT_X`
(execute). The implementation sits in `src/breakpoint_stubs.c` and is
wrapped in `src/breakpoint.ml`.

Here's the setup in `attach` (the function defined at
`src/trace.ml:316`):

```ocaml
(* src/trace.ml:387-425, abbreviated *)
let breakpoint_done =
  match snap_loc with
  | None -> Deferred.unit
  | Some { Elf.Stop_info.name; addr; _ } ->
    Core.eprintf "[ Attaching to %s @ 0x%016Lx ]\n%!" name addr;
    let single_hit = not opts.multi_snapshot in
    let bp = Breakpoint.breakpoint_fd head_pid ~addr ~single_hit in
    let bp = Or_error.ok_exn bp in
    let fd =
      Async_unix.Fd.create Async_unix.Fd.Kind.File
        (Breakpoint.fd bp)
        (Info.of_string "perf breakpoint")
    in
    let rec read_evs snapshot_enabled =
      match Breakpoint.next_hit bp with
      | Some hit ->
        if snapshot_enabled then take_snapshot_on_hit (name, hit);
        read_evs false
      | None -> ()
    in
    let interrupt = Ivar.read done_ivar in
    let%map.Deferred res =
      Async_unix.Fd.interruptible_every_ready_to
        fd `Read ~interrupt (fun () -> read_evs true) ()
    in
    ...
```

The breakpoint fd becomes readable when the CPU hits it. Async wakes
up, reads the event, and fires `take_snapshot_on_hit`. `single_hit`
is a safety knob — otherwise a frequently-called symbol would incur
~8 µs on every hit until perf auto-disables the breakpoint.

In parallel, Ctrl+C is handled via a signal handler that fills an
ivar to break out of the same polling loop:

```ocaml
(* src/trace.ml:503-510 *)
let stop = Ivar.read done_ivar in
Async_unix.Signal.handle ~stop [ Signal.int ] ~f:(fun (_ : Signal.t) ->
  Core.eprintf "[ Got signal, detaching... ]\n%!";
  Ivar.fill_if_empty done_ivar ());
Deferred.upon stop (fun () -> Core.Signal.Expert.set Signal.int Default);
Core.eprintf "[ Attached. Press Ctrl-C to stop recording. ]\n%!";
let%bind () = stop in
detach attachment
```

### 5.5 Taking the snapshot

Once a trigger fires, magic-trace tells `perf` to dump the ring
buffer. How it does so depends on perf's capabilities. On kernels
≥ 5.10 (with `--control` support), `perf_ctlfd` writes a command word
over a pipe and blocks for an ack:

```ocaml
(* src/perf_ctlfd.ml:3-15 *)
module Command = struct
  type t = string

  let snapshot = "snapshot\n"
  let stop = "stop\n"
end

let ack_msg = Bytes.of_string "ack\n\000"

(* if we send a command while perf is shutting down, [ack_rx] will become ready only after
   perf exits, so this timeout must be at least as long as it takes perf to finish
   shutting down. *)
let ack_timeout = `After (Time_ns.Span.of_int_sec 8)
```

On older kernels the same intent is expressed with signals — `SIGUSR2`
for snapshot, `SIGTERM` for shutdown — see the fallback branches at
`src/perf_tool_backend.ml:176-195`. Either way, `maybe_take_snapshot`
dispatches to the right transport:

```ocaml
(* src/perf_tool_backend.ml:205-210 *)
let take_snapshot t pid =
  match t with
  | Signals { snapshot; _ } -> Signal_unix.send_i snapshot (`Pid pid)
  | Ctlfd { ctlfd; snapshot; _ } ->
    Perf_ctlfd.dispatch_and_block_for_ack ctlfd snapshot |> ignore_perf_exit
;;
```

### 5.6 Capability probing

magic-trace supports a wide range of perf and kernel versions. The
feature matrix is a flags bitfield, detected at startup by reading
`/sys/bus/event_source/...`, `/proc/cpuinfo`, and the perf version
string:

```ocaml
(* src/perf_capabilities.ml:4-11 *)
let bit n = Int63.of_int (1 lsl n)
let configurable_psb_period = bit 0
let kernel_tracing = bit 1
let kcore = bit 2
let snapshot_on_exit = bit 3
let last_branch_record = bit 4
let dlfilter = bit 5
let ctlfd = bit 6
```

The three `supports_*` helpers beneath it encode which kernel and
perf versions introduced each feature (`src/perf_capabilities.ml:95-105`).

### 5.7 The dlfilter shim

Intel PT emits an event for *every* taken branch. Most of them are
uninteresting jumps within a single function body. magic-trace drops
those at capture time (when perf ≥ 5.14 supports it) by loading a
tiny shared library as a perf "dlfilter":

```c
/* src/perf_dlfilter.c:10-26 */
int filter_event_early(void *data, const struct perf_dlfilter_sample *sample,
                       void *ctx) {
  const struct perf_dlfilter_al *resolved_ip =
      perf_dlfilter_fns.resolve_ip(ctx);
  const struct perf_dlfilter_al *resolved_addr =
      perf_dlfilter_fns.resolve_addr(ctx);

  // only filter out events we for sure don't want. it's better to be less aggressive than
  // too aggressive, as being too aggressive will lead to broken traces, while being not
  // aggressive enough just makes things slower.
  if (resolved_ip && resolved_ip->sym && resolved_addr && resolved_addr->sym &&
      strcmp(resolved_ip->sym, resolved_addr->sym) == 0) {
    return 1;
  }

  return 0;
}
```

It's C because perf's dlfilter ABI is a C header. The `.so` is built
from these stubs and written into the record directory; magic-trace
passes `--dlfilter` to `perf script` at decode time (see
`src/perf_tool_backend.ml:587-598`). When dlfilter isn't available,
the same filtering happens in OCaml at decode time — cheaper but
less elegant.

### 5.8 The experimental direct backend

`direct_backend/` is a second, currently-unused implementation that
uses `perf_event_open` directly and decodes PT with `libipt`. Its
README (`direct_backend/README.md:1-22`) explains honestly that it
"works, but currently it doesn't support decoding usage of the Linux
vDSO … also missing many other features perf has like multi-threaded
recording and capturing multiple snapshots." It stays in-tree as
reference code for anyone who needs to reach deeper into PT than the
`perf` binary exposes.

---

## 6. Decode + write pipeline

Once perf has written `perf.data`, the picture flips: instead of
driving a live target, magic-trace chews through a static file,
streaming events into the trace writer and eventually out to disk.

### 6.1 perf.data → text via `perf script`

Instead of parsing Intel PT packets itself, magic-trace spawns
`perf script` with carefully-chosen flags:

```ocaml
(* src/perf_tool_backend.ml:607-616 *)
let itrace_opts =
  match collection_mode with
  | Intel_processor_trace _ -> [ "--itrace=bep" ]
  | Stacktrace_sampling _ -> []
in
let fields_opts =
  match collection_mode with
  | Intel_processor_trace _ ->
    [ "-F"; "pid,tid,time,flags,ip,addr,sym,symoff,synth,dso,event,period" ]
  | Stacktrace_sampling _ -> [ "-F"; "pid,tid,time,ip,sym,symoff,dso,event,period" ]
in
```

The output is line-oriented text, which is robust and diff-friendly
(every `.perf` file in `test/` is one of these verbatim).

### 6.2 Parsing one line

`perf_decode.ml` consists almost entirely of regexes and a
dispatcher. The four main patterns:

```ocaml
(* src/perf_decode.ml:10-36 *)
let perf_event_header_re =
  Re.Perl.re
    {|^ *([0-9]+)/([0-9]+) +([0-9]+)\.([0-9]+): +([0-9]+) +([a-z\-]+)(/[a-z=0-9]+)?(/[a-zA-Z]*)?:([a-zA-Z]+:)?(.*)$|}
  |> Re.compile
;;

let perf_callstack_entry_re = Re.Perl.re "^\t *([0-9a-f]+) (.*)$" |> Re.compile

let perf_branches_event_re =
  Re.Perl.re
    {|^ *(call|return|tr strt(?: jmp)?|syscall|sysret|hw int|iret|int|tx abrt|tr end|tr strt tr end|tr end  (?:async|call|return|syscall|sysret|iret)|jmp|jcc) +(\(x\) +)?([0-9a-f]+) (.*) => +([0-9a-f]+) (.*)$|}
  |> Re.compile
;;

let trace_error_re =
  Re.Posix.re
    {|^ instruction trace error type [0-9]+ (time ([0-9]+)\.([0-9]+) )?cpu [\-0-9]+ pid ([\-0-9]+) tid ([\-0-9]+) ip (0x[0-9a-fA-F]+|0) code [0-9]+: (.*)$|}
  |> Re.compile
;;
```

The recognised branch kinds — `call`, `return`, `tr strt`, `tr end`,
`syscall`, `sysret`, `hw int`, `iret`, `jmp`, `jcc`, `tx abrt`,
`async` — correspond one-for-one to what perf writes out for Intel PT.
Each becomes an `Event.Kind.t` (`src/event.ml:3-16`).

The public entry point is:

```ocaml
(* src/perf_decode.ml:410-417 *)
let to_events ?perf_maps pipe =
  let pipe = split_line_pipe pipe in
  (* every route of filtering on streams in an async way seems to be deprecated ... *)
  Pipe.map pipe ~f:(to_event ?perf_maps) |> Pipe.filter_map ~f:Fn.id
;;
```

It is a streaming `Pipe.map` — decoding proceeds lazily, in lockstep
with the trace writer pulling events off the other end.

### 6.3 What the raw input looks like

From `test/hello_world_userspace.perf`:

```
30549/30549 174427.938460376:  1  branches:uH:  tr strt  0 [unknown] => 7ffff7ddc140 _start+0x0
30549/30549 174427.938460812:  1  branches:uH:  tr end   7ffff7ddc140 _start+0x0 => 0 [unknown]
30549/30549 174427.938462629:  1  branches:uH:  call     7ffff7ddc143 _start+0x3 => 7ffff7ddc850 _dl_start+0x0
30549/30549 174427.938463014:  1  branches:uH:  tr end   7ffff7ddc86f _dl_start+0x1f => 0 [unknown]
30549/30549 174427.938465863:  1  branches:uH:  jmp      7ffff7ddc8e2 _dl_start+0x92 => 7ffff7ddc8ff _dl_start+0xaf
```

Columns: `pid/tid`, `seconds.nanoseconds`, period, event name,
kind, source address + symbol + offset, `=>`, destination address +
symbol + offset. `tr strt` / `tr end` mark the boundaries of Intel
PT coverage — any gap between a `tr end` and a `tr strt` is
"untraced" (e.g. code paged out, or a context switch).

### 6.4 Symbol resolution — a three-way lookup

Most of the time perf itself hands us symbol names. When it doesn't
(JIT-ed code, stripped binaries), magic-trace falls back:

```ocaml
(* src/perf_decode.ml:112-146 *)
let parse_symbol_and_offset ?perf_maps pid str ~addr : Symbol.t * int =
  match Re.Group.all (Re.exec symbol_and_offset_re str) with
  | [| _; symbol; offset |] ->
    ...
    From_perf symbol, offset
  | _ | (exception _) ->
    let failed = Symbol.Unknown, 0 in
    (match perf_maps, pid with
     | None, _ | _, None ->
       (match Re.Group.all (Re.exec unknown_symbol_dso_re str) with
        | [| _; dso |] ->
          From_perf [%string "[unknown @ %{addr#Int64.Hex} (%{dso})]"], 0
        | _ | (exception _) -> failed)
     | Some perf_map, Some pid ->
       (match Perf_map.Table.symbol ~pid perf_map ~addr with
        | None -> failed
        | Some location ->
          let offset = saturating_sub_i64 addr location.start_addr in
          From_perf_map location, offset))
;;
```

Order: perf's own symbol → `/tmp/perf-<pid>.map` JIT map → `[unknown]`.

A separate augmentation happens at *write* time. When the trace
writer emits a duration span, it enriches the args with file/line/col
if ELF debug info is available for that address:

```ocaml
(* src/trace_writer.ml:379-395 *)
match symbol with
| From_perf_map { start_addr = _; size = _; function_ = _ } ->
  address @ [ "symbol", Interned display_name ]
| _ ->
  (match Option.bind (Int64.to_int base_address) ~f:(Hashtbl.find t.debug_info) with
   | None -> address @ [ "symbol", Interned display_name ]
   | Some (info : Elf.Location.t) ->
     address
     @ [ "line", Int info.line
       ; "col", Int info.col
       ; "symbol", Interned display_name
       ]
     @ (match info.filename with
        | Some x -> [ "file", Interned x ]
        | None -> []))
```

OCaml symbols get one more pass through a small Angstrom parser that
demangles the compiler's name encoding:

```ocaml
(* src/demangle_ocaml_symbols.ml:13-41 *)
let parser =
  let open Angstrom in
  let strip_numeric_suffix =
    char '_' *> skip_while Char.is_digit *> end_of_input *> return None
  in
  let double_underscores = string "__" >>| fun _ -> Some '.' in
  let two_digit_hexadecimal_number =
    let hex_character = satisfy Char.is_hex_digit in
    let hexcode =
      decode_two_digit_hexadecimal_number <$> char '$' *> hex_character <*> hex_character
    in
    hexcode
    >>= fun integer ->
    match integer with
    | None -> fail "invalid integer"
    | Some character -> return (Some character)
  in
  ...
  string "caml" *> many1 token
;;
```

So `caml__foo$2a__bar` becomes `caml.foo*bar` (`$2a` is hex for
`*`). This is what feeds the `fzf` picker when `-fzf-demangle-symbols`
is set.

### 6.5 Call stack reconstruction

`trace_writer.ml` is the heart of the decode stage. It keeps
per-thread state and turns the stream of call/return/jmp events into
Perfetto duration spans.

Per-thread state lives in `Thread_info.t`:

```ocaml
(* src/trace_writer.ml:107-123 *)
type 'thread t =
  { thread : ('thread[@sexp.opaque])
  ; (* this isn't a canonical callstack, but represents all of the information that we
       know about the callstack at the point in the events up to the current event being
       processed, and is reflected in the trace at that point. *)
    mutable callstack : Callstack.t
  ; inactive_callstacks : Callstack.t Stack.t
  ; mutable last_decode_error_time : Mapped_time.t
  ; ocaml_exception_state : ocaml_exception_state
  ; mutable pending_events : Pending_event.t list
  ; mutable pending_time : Mapped_time.t
  ; start_events : (Mapped_time.t * Pending_event.t) Deque.t
  ; mutable last_event_time : Mapped_time.t
  ; track_group_id : int
  ; extra_event_tracks : ('thread[@sexp.opaque]) Hashtbl.M(Collection_mode.Event.Name).t
  }
```

`inactive_callstacks` is a stack of stacks — used when a syscall or
hardware interrupt runs on "a new stack" and we want to splice back
to the previous userspace stack on sysret/iret.

The two primitives are `call` and `ret`:

```ocaml
(* src/trace_writer.ml:561-580 *)
let call t thread_info ~time ~location =
  let ev = Pending_event.create_call location ~from_untraced:false in
  add_event t thread_info time ev;
  Callstack.push thread_info.callstack location
;;

let ret_without_checking_for_go_hacks t (thread_info : _ Thread_info.t) ~time =
  match Callstack.pop thread_info.callstack with
  | Some { symbol; _ } -> add_event t thread_info time { symbol; kind = Ret }
  | None ->
    (* no known stackframe was popped --- could occur if the start of the snapshot
       started in the middle of a tracing region *)
    add_event t thread_info time
      { symbol = From_perf "[unknown]"
      ; kind = Ret_from_untraced { reset_time = thread_info.callstack.create_time }
      }
;;
```

On top of those sits a big match on `(kind, trace_state_change)` that
dispatches every perf event shape:

```ocaml
(* src/trace_writer.ml:1120-1149, abbreviated *)
(match kind, trace_state_change with
 | Some Call, (None | Some End) -> call t thread_info ~time ~location:dst
 | ...
 | (None | Some Async), Some End ->
   call t thread_info ~time ~location:Event.Location.untraced
 | Some Syscall, Some End ->
   assert_trace_scope t outer_event [ Userspace ];
   call t thread_info ~time ~location:Event.Location.syscall
 | Some Return, Some End ->
   call t thread_info ~time ~location:Event.Location.returned
 | Some Return, None ->
   Ocaml_hacks.ret_track_exn_data t thread_info ~time;
   Ocaml_hacks.check_current_symbol_track_entertraps t thread_info ~time dst
 | ...)
```

The whole dispatcher runs from `src/trace_writer.ml:1120-1231`. It
encodes, in one place, all of magic-trace's knowledge about what
different perf events mean for a per-thread call stack.

The two subtle bits worth highlighting:

**Tail-call repair.** Jumps between functions (tail calls, PLT stubs)
don't naturally appear as `call`+`ret` pairs. When `check_current_symbol`
notices the live IP's symbol doesn't match the top of the stack, it
synthesises the pair:

```ocaml
(* src/trace_writer.ml:686-712 *)
let check_current_symbol t (thread_info : _ Thread_info.t) ~time (location : Event.Location.t) =
  (* after every operation, we should be in a situation where the current symbol under
     the pc matches the symbol at the top of the callstack. this can go out-of-sync
     with jumps between functions (e.g. tailcalls, PLT) or returns out of the highest
     known function, so we have to correct the top of the stack here. *)
  match Callstack.top thread_info.callstack with
  | Some { symbol; _ } when not ([%compare.equal: Symbol.t] symbol location.symbol) ->
    ret t thread_info ~time;
    call t thread_info ~time ~location
  | Some _ -> ()
  | None ->
    (* if we have no callstack left, then we just returned out of something we didn't
       see the call for. since we're in snapshot mode, this happens with functions
       called before the perf events started, so add in a call that begins at the
       start of the trace for that pid. *)
    let ev = Pending_event.create_call location ~from_untraced:true in
    write_pending_event t thread_info thread_info.callstack.create_time ev;
    Callstack.push thread_info.callstack location
;;
```

**Batching and time smearing.** Many events arrive with the same
timestamp. If magic-trace emitted them all at the same `time`, their
duration spans would collapse to zero. Instead it buffers events per
timestamp and spreads them evenly:

```ocaml
(* src/trace_writer.ml:442-462 *)
let flush (t : _ inner) ~to_time (thread : _ Thread_info.t) =
  (* try to evenly distribute the time between timestamp updates between all the
     time-consuming events in the batch. *)
  let count = List.count thread.pending_events ~f:consumes_time in
  let total_ns = Mapped_time.diff to_time thread.pending_time |> Time_ns.Span.to_int_ns in
  let ns_offset = ref 0 in
  let shares_consumed = ref 0 in
  List.iter (List.rev thread.pending_events) ~f:(fun ev ->
    let ns_share =
      if consumes_time ev
      then (
        incr shares_consumed;
        (total_ns - !ns_offset) / (count - !shares_consumed + 1))
      else 0
    in
    let time = Mapped_time.add thread.pending_time (Time_ns.Span.of_int_ns !ns_offset) in
    ns_offset := !ns_offset + ns_share;
    write_pending_event t thread time ev);
  thread.pending_time <- to_time;
  thread.pending_events <- []
;;
```

### 6.6 `[untraced]` — the pink bands

When Intel PT loses coverage (end of snapshot, syscall to an
untraced region, iret into untraced kernel), the writer pushes a
synthetic frame:

```ocaml
(* src/event.ml:62-65 *)
let locationless symbol = { instruction_pointer = 0L; symbol; symbol_offset = 0 }
let unknown = locationless Unknown
let untraced = locationless Untraced
```

```ocaml
(* src/symbol.ml:16-23 *)
let display_name = function
  | Unknown -> "[unknown]"
  | Untraced -> "[untraced]"
  | Returned -> "[returned]"
  | Syscall -> "[syscall]"
  | From_perf name -> name
  | From_perf_map { function_; _ } -> function_
;;
```

These become the pink "[untraced]" spans the README talks about —
regions where magic-trace knows time passed but can't show you what
happened. Pushing `[untraced]` instead of just gapping the timeline
preserves the call stack depth correctly for anything that happens
after the gap.

### 6.7 Callstack compression

The `.fxt` file includes, per event, the full call stack. Naively
that would blow up the file size. `Callstack_compression` (the whole
module, `src/callstack_compression.ml:1-78`) does two things:

- **Symbol interning.** Each new symbol gets a small integer id.
  Emitted events refer to ids.
- **Follow-table run encoding.** Sequential calls frequently follow
  the same pattern (A calls B, B calls C). The compressor tracks
  "after id X we usually see id Y", then encodes common runs as
  `(start_id, run_length)` pairs.

The output for one event:

```ocaml
type compression_event =
  { new_symbols : (Symbol.t * int) list
  ; callstack : (int * int) list
  }
[@@deriving sexp, bin_io]
```

A consumer maintains the same state machine to decompress.

### 6.8 Writing the FXT

The actual bytes on disk are produced by `Tracing_zero.Writer` from
`vendor/tracing/`. This is Jane Street's implementation of Fuchsia
Trace Format — a binary layout of process/thread tracks and
duration_begin / duration_end records. magic-trace picks the
compression by filename suffix:

```ocaml
(* src/tracing_tool_output.ml:203-216 *)
let writer =
  let file_format : Tracing_zero.Writer.File_format.t =
    if Filename.check_suffix filename ".gz"
    then Gzip
    else if Filename.check_suffix filename ".zst"
    then Zstandard
    else Uncompressed
  in
  Tracing_zero.Writer.create_for_file
    ?num_temp_strs
    ~file_format
    ~filename:indirect_store_path
    ()
in
```

The default output name is `trace.fxt.gz`, so compression is on out
of the box.

### 6.9 Decode errors

Intel PT can and does drop packets — typically when the branch buffer
overflows. perf reports these inline as "instruction trace error"
messages. `trace_error_re` (`src/perf_decode.ml:32-36`) extracts them
into a structured type (`src/event.mli:70-78`), which the writer
turns into a visible annotation:

```ocaml
(* src/trace_writer.ml:1035-1045 *)
| Error { thread = _; instruction_pointer; message; time = _ } ->
  warn_decode_error ~instruction_pointer ~message;
  let name = sprintf !"[decode error: %s]" message in
  write_duration_instant t ~thread ~name ~time ~args:[];
  let is_kernel_address =
    match instruction_pointer with
    | None -> false
    | Some ip -> is_kernel_address ip
  in
  end_of_thread t thread_info ~time ~is_kernel_address
```

`end_of_thread` resets the call stack because after a decode error
we don't know what frame we're in. `test/decode_errors.ml` has
recorded examples; the commonest is "Overflow packet".

---

## 7. End-to-end: `magic-trace attach -pid X`

Putting it together, here's the full call chain:

1. `bin/magic_trace_bin.ml:3` runs `Magic_trace_lib.Trace.command`.
2. `Command_unix.run` parses argv and dispatches into the
   `Perf_tool_commands` group built at `src/trace.ml:795-799`.
3. `attach_command` (`src/trace.ml:684-750`) parses `-pid`, looks up
   the executable via `/proc/PID/exe` (`src/trace.ml:720-723`).
4. `create_elf` (`src/trace.ml:33-45`) loads the ELF so debug info is
   available. If `-trigger SYMBOL` is set, `Symbol_selection.evaluate`
   (`src/symbol_selection.ml:57-83`) turns the selection into a name,
   possibly through `Fzf.pick_one`.
5. `Backend.Recording.attach_and_record` is called at
   `src/trace.ml:352-364`. For the perf backend, this constructs the
   argv at `src/perf_tool_backend.ml:507-520` and forks `perf record`.
6. `Perf_ctlfd.create` opens the command/ack pipes
   (`src/perf_ctlfd.ml:25-36`); `--control=fd:RX,TX` is appended to
   the perf argv if the kernel supports it.
7. If a trigger symbol was set, `Elf.find_selection` resolves it to
   an address and `Breakpoint.breakpoint_fd` installs a hardware
   breakpoint via `perf_event_open(PERF_TYPE_BREAKPOINT, HW_BREAKPOINT_X)`
   (`src/trace.ml:398` + `src/breakpoint_stubs.c`).
8. `Async_unix.Fd.interruptible_every_ready_to` polls the breakpoint
   fd; `Signal.handle Signal.int` (`src/trace.ml:504-506`) fills the
   interrupt ivar on Ctrl+C.
9. On breakpoint hit, `take_snapshot_on_hit` →
   `Backend.Recording.maybe_take_snapshot ~source:\`function_call`;
   on Ctrl+C, the `finalize_recording` callback invokes the same with
   `~source:\`ctrl_c` (`src/trace.ml:367-375`).
10. `maybe_take_snapshot` (`src/perf_tool_backend.ml:543-557`) calls
    `Control.take_snapshot`, which either writes `snapshot\n` on the
    ctlfd pipe or sends `SIGUSR2`. perf dumps the ring buffer into
    `perf.data`.
11. `detach` (`src/trace.ml:429-436`) fills `done_ivar`, awaits
    `breakpoint_done`, persists hits + recording data sexps, then
    calls `Backend.Recording.finish_recording`
    (`src/perf_tool_backend.ml:559-568`), which sends `stop\n` and
    waits for perf to exit.
12. Control returns to `attach_command`, which loads any perf-map
    JIT tables (`Perf_map.Table.load_by_pids`) and calls
    `decode_to_trace` (`src/trace.ml:217-291`).
13. `decode_to_trace` calls `Backend.decode_events`
    (`src/perf_tool_backend.ml:577-...`), which fires off `perf
    script --itrace=bep ...`, optionally with `--dlfilter`.
14. `Perf_decode.to_events` (`src/perf_decode.ml:410-417`) parses
    perf-script lines into a `Pipe.t` of `Event.t`. Symbols are
    resolved three ways (`src/perf_decode.ml:112-146`).
15. `write_trace_from_events` (`src/trace.ml:89-186`) normalises
    timestamps, builds a `Trace_writer`, and drains the pipe.
16. `Trace_writer.write_event` dispatches each event through the
    big match (`src/trace_writer.ml:1035-1231`), pushing and popping
    per-thread stacks, smearing batched timestamps, enriching with
    ELF debug info, and forwarding to
    `Tracing_zero.Writer.write_duration_begin/end`.
17. When the pipe closes, `Tracing.Trace.close` flushes the writer;
    gzip compression is handled transparently by
    `Tracing_zero.Writer` based on the `.gz` suffix
    (`src/tracing_tool_output.ml:204-215`).
18. The resulting `trace.fxt.gz` is what you drop onto
    `magic-trace.org`.

---

## 8. Pointers for going further

- **Golden fixtures.** Every `test/*.perf` file is raw `perf script`
  output for a known scenario. `test/test.ml` is the inline-expect
  driver. If you're changing the decoder or writer, these are your
  first line of defence. Highlights:
  `test/page_fault.perf`, `test/ocaml_exceptions.perf`,
  `test/hello_world_with_kernel_tracing.perf`,
  `test/decode_errors.ml`.
- **The direct backend.** `direct_backend/README.md` is a candid,
  readable account of why the "just shell out to perf" architecture
  won, plus concrete ideas for where to take the tool next
  (perf-dlfilter-driven decode, basic-block-level exception handling).
- **OCaml exception hacks.** `src/ocaml_exception_info.ml` plus the
  `Ocaml_hacks` calls scattered through `trace_writer.ml`. This is
  where Intel PT's branch-only view runs up against OCaml's
  exception-handler `pushtrap`/`poptrap` frames, and magic-trace has
  to stitch the gap by reading debug metadata.
- **The vendored FXT writer.** `vendor/tracing/` — useful if you
  ever want to produce Perfetto-compatible traces from something
  other than magic-trace.
- **The wiki.** Build instructions, supported platforms, overhead
  measurements, and discussions of prior art — all live at
  https://github.com/janestreet/magic-trace/wiki.

A useful reading order if you're starting cold: skim `README.md` to
get the user-facing story, read this document, then trace one
subcommand end-to-end in the source (`attach` is the simplest). The
big files to know by heart are `src/trace.ml` (orchestration),
`src/perf_tool_backend.ml` (capture), and `src/trace_writer.ml`
(decode + write).
