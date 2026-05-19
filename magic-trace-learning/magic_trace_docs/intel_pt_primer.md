# Intel Processor Trace — a primer for reading magic-trace

This is a companion to `docs/codebase_tour.md`. The tour walked you
through magic-trace's source top-to-bottom. This document is the
opposite: a ground-up explanation of **Intel Processor Trace** (PT),
the hardware feature magic-trace is built on.

Read either one first. The tour will make more sense if you already
have the PT mental model; the PT concepts will land harder if
you've seen the code that uses them.

## Which PT topics matter most for understanding magic-trace?

In descending order of "how directly does this shape code you'll
read":

- **Tier S** — core design-determining:
  - **Decoding** (§3). Explains why `perf_decode.ml` and the
    three-way symbol lookup exist at all.
  - **Timing** (§4). `src/timer_resolution.ml` exposes raw PT timing
    knobs; unintelligible without background.
  - **The buffer** (§5). `--snapshot`, `Pow2_pages`, ring semantics —
    all pure PT-buffer mechanics.
- **Tier A** — explains specific flags and output literals:
  - **Packet types** (§2). What "tr strt"/"tr end" mean; why
    dlfilter drops same-symbol jumps.
  - **Filtering** (§6). Why `/u`/`/k`/`/uk` works and why
    `-p PID` scopes tracing.
- **Tier B** — explains warnings and constraints:
  - **Gotchas** (§7). Overflow errors, the VM caveat, direct backend's
    vDSO problem.
  - **vs LBR/sampling** (§8). The fallback path; why
    `Callgraph_mode` only applies under `-sampling`.

If you're short on time, read §1–§5 (Tier S + the §1 overview) and
stop. If you want the complete picture, read everything.

---

## 1. First principles: why this exists

Imagine you want to know, with near-cycle accuracy, every function
call that happened inside a running process for the last ten
milliseconds. The naive approach — emit one trace record per
instruction — is unworkable. A modern core retires ~10⁹
instructions per second; even a single byte per record saturates
DRAM bandwidth and obliterates cache.

But observe: **given the binary**, the vast majority of
instruction-level behavior is deterministic. If the CPU just
executed `jmp 0x401000`, the instruction at `0x401000` is obvious —
it's literally in the ELF. If it executed `call foo` where `foo` is
a known symbol, same thing. If it executed `jcc` (conditional
branch), the only question is one bit: did it jump or fall through?

That observation is the entire idea behind PT. The hardware emits
just enough information — *differential* control-flow hints — that a
decoder **with access to the binary** can reconstruct the whole
execution. Specifically, the CPU emits:

- one bit per conditional branch (taken or not),
- a target IP per indirect branch, call, or return,
- timing markers periodically,
- synchronization points so a decoder that joined mid-stream can
  recover.

Almost nothing else. This is the "cheap stream" — a few bytes per
thousand instructions — that makes PT viable at 2–10% overhead.

All the apparent complexity of magic-trace flows from this one
insight. The code exists to (a) configure the CPU's packet
generator, (b) shepherd the resulting bytes to disk, and (c) run
the reconstruction algorithm with the correct binary state.

---

## 2. Packet types — the atoms

PT's output is a sequence of variable-length packets. Intel's
taxonomy groups them by purpose: **flow**, **timing**, **mode**,
**paging**, **synchronization**, **control**. You don't need to
memorize bit layouts — those live in Intel SDM Volume 3B, Chapter 35.
You need to know the *function* of each packet so that magic-trace's
output becomes legible.

### Flow packets

**TNT** (Taken / Not-Taken). One bit per conditional branch,
packed 1–6 bits per packet. When the decoder reaches a `jcc` in the
binary, it consumes one bit from the current TNT to decide which
way to go. Every single `jcc` line in `test/hello_world_userspace.perf`
is a TNT bit being resolved post-hoc.

**TIP** (Target IP). An IP value, often compressed (only the bytes
of the IP that changed from the previous TIP are emitted). Used for
*indirect* control flow: `ret`, `call reg`, `jmp reg`, indirect
`jmp [mem]`. Every `call` and `return` event you see in the magic-trace
UI — except direct `call symbol` — came from a TIP.

**FUP** (Flow Update Packet). An IP anchor emitted at
*asynchronous* events: interrupts, exceptions, `iret`, `vmexit`,
exits from tracing mode. FUP says "the flow was at address X when
this thing happened". Ties: `hw int`, `iret`, and `int` lines in
perf script output each originate with an FUP.

### Mode packets

**MODE.Exec** — the CPU switched addressing mode (16/32/64-bit,
CS.D, CS.L). The decoder has to disassemble at the right width,
so it needs to know.

**MODE.TSX** — transactional execution (TSX) began or ended,
and/or a transaction aborted. In perf script: `tx abrt`.

### Packet generation enable/disable

**PGE** (Packet Generation Enable) and **PGD** (Packet Generation
Disable). The CPU stops emitting packets when the filter says the
current code path shouldn't be traced (e.g., kernel entry under
`/u` mode), then resumes when the filter permits again. Each
transition is one packet.

This maps directly onto a magic-trace concept. In perf script,
these become `tr strt` and `tr end` lines — "trace starts here",
"trace ends here". Follow the chain:

```
(* src/perf_decode.ml:22-26 *)
let perf_branches_event_re =
  Re.Perl.re
    {|^ *(call|return|tr strt(?: jmp)?|syscall|sysret|hw int|iret|int|tx abrt|tr end|tr strt tr end|tr end  (?:async|call|return|syscall|sysret|iret)|jmp|jcc) +(\(x\) +)?([0-9a-f]+) (.*) => +([0-9a-f]+) (.*)$|}
  |> Re.compile
;;
```

The `tr strt` and `tr end` tokens in that regex correspond to PGE
and PGD respectively. They surface as `Trace_state_change.Start`
and `Trace_state_change.End` in the event type, and the trace
writer reacts to them by pushing an `[untraced]` frame:

```ocaml
(* src/trace_writer.ml:1142-1143 *)
| (None | Some Async), Some End ->
  call t thread_info ~time ~location:Event.Location.untraced
```

That's why you see pink bands in the UI wherever PT coverage
lapsed.

### Synchronization

**PSB** (Packet Stream Boundary). A fixed byte pattern the decoder
can scan for if it joined the stream mid-way (say, a ring-buffer
snapshot that captured only the last N KB). After a PSB, you get a
fresh sync packet group re-establishing the current IP, CR3, mode,
and timing. A snapshot that starts mid-packet must scan forward to
the next PSB before it can decode anything.

PSB is emitted every `psb_period` bytes, and the period is
configurable (on newer CPUs) via the `psb_period` field:

```ocaml
(* src/timer_resolution.ml:8-15 *)
| Custom of
    { cyc : bool option [@sexp.option]
    ; cyc_thresh : int option [@sexp.option]
    ; mtc : bool option [@sexp.option]
    ; mtc_period : int option [@sexp.option]
    ; noretcomp : bool option [@sexp.option]
    ; psb_period : int option [@sexp.option]
    }
```

Whether the CPU supports configuring the period at all is a
capability bit:

```ocaml
(* src/perf_capabilities.ml:4-5 *)
let bit n = Int63.of_int (1 lsl n)
let configurable_psb_period = bit 0
```

On older chips you're stuck with whatever the hardware picked,
which magic-trace handles by silently degrading to `Low`:

```ocaml
(* src/perf_tool_backend.ml:241-247 *)
| (Normal | High), false ->
  Core.eprintf
    "Warning: This machine has an older generation processor, timing granularity \
     will be ~1us instead of ~10ns. Consider using a newer machine.\n\
     %!";
  Timer_resolution.Low
```

### Control

**OVF** (Overflow). The CPU emits this when its tiny internal PT
FIFO filled up and state was lost. Everything after an OVF is
untrustworthy until the next PSB. The decoder surfaces this as a
first-class error, which magic-trace renders as a visible span:

```ocaml
(* src/trace_writer.ml:1036-1045 *)
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

### Timing

We defer these to §4, but the packet names: **TSC**, **MTC**,
**CYC**, **TMA**, **CBR**. They stamp the packet stream with
enough timing information for the decoder to assign nanoseconds to
every event.

### An illustrative walk through one call

Suppose the target executes this:

```
main:
  call add_one          ; direct call
add_one:
  cmp edi, 0            ; conditional
  jne nonzero           ; taken this time
nonzero:
  ret
```

The packet stream for this fragment, approximately:

```
 ┌── CALL (direct, to known address)
 │   → no packet. Decoder knows from the binary.
 │
 ├── CMP / JNE (conditional, taken)
 │   → one TNT bit: "1" (taken).
 │
 ├── RET
 │   → TIP to the post-call IP in main. Or, if RET compression is
 │     enabled, the return may be implicit (stack-matched against the
 │     prior CALL) and skipped entirely.
 │
 └── occasional CYC/TSC interleaved to stamp time
```

Three actual code branches, and the hardware emitted maybe 2
packet-bytes. That's the compression we were promised.

---

## 3. Decoding — the binary-walking loop

This section explains the one algorithm at the heart of PT. Once
you have this, everything else is plumbing.

### The algorithm

The decoder has two pieces of state:

1. A current instruction pointer, `IP`.
2. A model of the loaded binary — which bytes are at which virtual
   addresses, for this process, at this moment in execution.

Given those, it runs this loop:

```
loop forever:
  disassemble from IP onward
  when you hit a branch instruction:
    if unconditional direct (jmp addr, call addr):
      IP = addr
    elif conditional (jcc, loop, etc.):
      bit = consume one TNT bit
      if bit:    IP = target of jcc
      else:      IP = fallthrough
    elif indirect (jmp reg, call reg, call [mem]):
      IP = consume TIP value
    elif ret:
      IP = consume TIP (or use RET-compression shortcut)
    if the branch crossed a function boundary:
      emit an event "call X => Y" or "ret X => Y"
  on async packet (FUP):
    IP = FUP address
    emit "interrupt X => Y" or similar
  on timing packet:
    update clock state; timestamp subsequent events
  on PSB:
    resync — reset IP/mode state from the sync group
  on OVF:
    emit a decode error; wait for next PSB
```

That's it. Everything else — call stacks, durations, symbol
lookups, JITs, kernel mode — are layered on top of this loop.

### Two implementations in magic-trace

**Default path.** The decoder lives inside libipt, inside `perf`.
magic-trace spawns `perf script --itrace=bep`, which runs libipt,
which runs the loop above and prints a line per emitted event.
magic-trace regex-parses those lines at `src/perf_decode.ml:10-39`.

**Direct backend (experimental).** `direct_backend/decoding.ml`
calls libipt's C API directly, skipping the text layer:

```ocaml
(* direct_backend/decoding.ml:99-104 *)
external init_decoder : Config.t -> c_decoding_state = "magic_pt_init_decoder_stub"

external run_decoder
  :  c_decoding_state
  -> Event.t
  -> Add_section.t
  -> Decode_result.t
  = "magic_pt_run_decoder_stub"
```

Both paths run the same algorithm; the difference is whether the
events are marshalled through text or through shared memory.
Skipping text is faster but limits you to libipt's event model —
no way to inject extra context between perf and the OCaml side.

### Why the binary must be *correct at decode time*

The decoder reads instruction bytes from the binary to decide what
each branch is. If the binary it reads is not the binary the CPU
ran, the walk will go off the rails on the first mispredicted
branch, and everything after is garbage.

This is a non-trivial constraint:

- **Shared libraries need to be the ones that were loaded.**
  Process memory maps at capture time determine which version of
  `libc.so.6` is in use.
- **JITs** (V8, the JVM, OCaml's dynamic compilation) emit code
  that isn't on disk. Linux has a convention: if the process
  writes `/tmp/perf-<pid>.map` listing `start_addr size symbol`
  lines, perf will read it. magic-trace's decoder uses this as
  the second arm of the three-way symbol lookup:

  ```ocaml
  (* src/perf_decode.ml:130-145 *)
  | Some perf_map, Some pid ->
    (match Perf_map.Table.symbol ~pid perf_map ~addr with
     | None -> failed
     | Some location ->
       let offset = saturating_sub_i64 addr location.start_addr in
       From_perf_map location, offset))
  ```

- **Sideband data.** perf records auxiliary events alongside PT —
  mmap / munmap, context switches, execs — via its normal event
  stream. libipt-sb consumes these so the decoder can update its
  loaded-binary model as the process evolves. The direct backend
  wires this in explicitly:

  ```c
  // direct_backend/decoding_stubs.c:10-12
  #include <intel-pt.h>
  #include <libipt-sb.h>
  #include <pevent.h>
  ```

- **Image section IDs.** libipt assigns each loaded segment an
  integer `isid`, then tags each event with the `isid` it came
  from. The direct backend threads these through to resolve
  symbols correctly when two libraries at different addresses
  both contain code:

  ```ocaml
  (* direct_backend/decoding.ml:44 *)
  ; mutable isid : int
  ```

  ```ocaml
  (* direct_backend/decoding.ml:128-133 *)
  let resolver : Elf.Symbol_resolver.t =
    { elf; file_offset = add.offset; loaded_offset = add.vaddr }
  in
  state.fallback_resolvers
  <- (add.vaddr, add.size, resolver) :: state.fallback_resolvers;
  Hashtbl.add_exn state.resolver_by_isid ~key:add.isid ~data:resolver
  ```

This is also why self-modifying code breaks PT (more in §7): the
decoder reads *current* binary bytes, but the trace was produced
by whatever bytes existed at capture time.

### Why this is so much better than it sounds

On its face, "trace everything" should be hundreds of times more
expensive than sampling. PT inverts that intuition because the
hardware does the cheap part and the CPU isn't even aware of a
tracing abstraction — it's just dumping state to a memory region
it already had to compute. Reconstruction happens later, offline,
at leisure. The decoder can be as slow as it needs to be without
impacting the live workload.

For the code walkthrough of how magic-trace threads
`perf script` output → `Perf_decode` → `Trace_writer` → FXT, see
`codebase_tour.md` §6.

---

## 4. Timing — assigning clocks to events

PT's timing packets are layered. Each refines the resolution of
the previous.

### TSC — Time Stamp Counter

The baseline. TSC ticks at a fixed rate (invariant TSC is standard
on everything recent), independent of CPU frequency scaling. The
CPU emits a TSC packet at PSBs and certain events, so the decoder
periodically gets a wall-clock anchor.

Converting TSC cycles to nanoseconds uses three constants exposed
by the kernel's perf mmap page. The direct backend's `Trace_meta`
holds them explicitly:

```ocaml
(* direct_backend/manual_perf.ml:27-34 *)
module Trace_meta = struct
  type t =
    { mutable time_shift : int
    ; mutable time_mult : int
    ; mutable time_zero : int
    ; mutable max_nonturbo_ratio : int
    }
  [@@deriving sexp]
end
```

The conversion is `ns = ((tsc - tsc_offset) * time_mult) >> time_shift + time_zero`.
These numbers are measured once per boot and stored in the perf
mmap page.

### MTC — Mini Timing Counter

Between TSC packets (which are comparatively expensive to emit),
the CPU emits MTC packets at a finer interval. An MTC is just a
short counter; combined with TMA (which tells you how an MTC
aligns to TSC), you interpolate.

Configurable via `mtc_period` (0 = maximum frequency, larger
numbers = coarser):

```ocaml
(* src/timer_resolution.ml:11-12 *)
; mtc : bool option [@sexp.option]
; mtc_period : int option [@sexp.option]
```

Gets you ~10 ns resolution on modern parts.

### CYC — Cycle Accurate

The finest-grained packet. CYC emits a cycle count whenever enough
cycles have elapsed since the previous packet. Combined with the
TSC baseline, CYC lets the decoder stamp events with near-cycle
precision. This is where magic-trace's "~40 ns" resolution claim
comes from.

Configurable via `cyc` and `cyc_thresh`:

```ocaml
(* src/timer_resolution.ml:9-10 *)
; cyc : bool option [@sexp.option]
; cyc_thresh : int option [@sexp.option]
```

`cyc_thresh=1` means "emit a CYC every cycle if a packet-worthy
event occurred" — the most aggressive setting.

### TMA — Timing Mostly Accurate

The rosetta stone between MTC ticks and TSC cycles. Emitted
alongside TSC so the decoder can express any MTC tick in
nanoseconds.

### CBR — Core Bus Ratio

Frequency-change event. When the CPU changes ratios (turbo up,
thermal down, sleep transition), the cycle-to-nanosecond
conversion changes. CBR tells the decoder the new ratio so it can
recompute. magic-trace recognizes these explicitly:

```ocaml
(* src/perf_decode.ml:28-30 *)
let perf_cbr_event_re =
  Re.Perl.re {|^ *([a-z )(]*)? +cbr: +([0-9]+ +freq: +([0-9]+) MHz)?(.*)$|} |> Re.compile
;;
```

And emits a `Power` event (`src/event.ml:79`) for visibility in
the UI.

### The three resolution settings, tabulated

| Variant  | Perf arg string                       | Effect                                              |
|----------|---------------------------------------|-----------------------------------------------------|
| `Low`    | `""` (empty)                          | Only TSC; ~µs resolution; smallest trace            |
| `Normal` | `cyc=1,cyc_thresh=1,mtc_period=0`     | Full CYC + finest MTC; ~10–40 ns resolution         |
| `High`   | same + `,noretcomp=1`                 | Also disable RET compression; fullest fidelity      |

This is not prose — it's literally the arg-string construction
in `perf_tool_backend.ml`:

```ocaml
(* src/perf_tool_backend.ml:249-256 *)
match timer_resolution with
| Low -> Or_error.return ""
| Normal -> Or_error.return "cyc=1,cyc_thresh=1,mtc_period=0"
| High -> Or_error.return "cyc=1,cyc_thresh=1,mtc_period=0,noretcomp=1"
| Sample _ ->
  Or_error.error_string
    "[-timer-resolution Sample] can only be used in sampling mode. (Did you forget \
     [-sampling]?)"
```

### Why `noretcomp=1` exists

By default, the CPU does not emit a TIP for returns whose call
site the decoder can match via a stack tracker — this halves the
byte rate on call-heavy workloads but depends on a call/return
discipline being maintained. With `noretcomp=1`, every return
emits a TIP, which is more robust (but fatter traces). `High` sets
it for maximal fidelity when you're chasing an exotic bug.

### The overhead / resolution knob

Adding CYC packets roughly doubles the PT byte rate. That's the
trade magic-trace users make when they switch from `-timer-resolution
Low` to `Normal`. It's the single biggest lever on capture
overhead; consider dropping to `Low` if your buffer fills too
quickly.

---

## 5. The buffer — ToPA, ring mode, and snapshots

PT doesn't write to a file. It writes to a region of physical
memory via a descriptor table. You have to arrange memory up front,
tell the CPU where it is, and then drain it on your own schedule.

### Where packets go

Two destination modes are standardized:

- **Single range**. A linear buffer. The CPU writes until it's
  full, then stops (and emits OVFs). Simple, no wrap.
- **ToPA (Table of Physical Addresses)**. A list of
  `(physical_address, length)` entries. The CPU walks the table;
  each entry can be marked "STOP" (stop when full), "INT"
  (interrupt), or "END" (wrap around to the first entry = ring
  mode).

Linux uses ToPA in ring mode. The ring is exposed to userspace as
the **AUX area** of perf's mmap buffer — same protocol as the
regular mmap, but with an `aux_offset` field pointing at the PT
region.

### Sizing

magic-trace sizes the AUX ring via `-m,NUM_PAGES`. The size must
be a power of two pages, which is why `Pow2_pages` exists:

```ocaml
(* src/pow2_pages.ml:15-47 *)
let create byte_units =
  let bytes = Byte_units.bytes_int64 byte_units in
  if Int64.( < ) bytes min_byte_units_int
  then (
    warn [%string "Rounding small bytes, ... up to the minimum of ..."];
    Int64.(to_int_exn (min_byte_units_int / page_size)))
  else if Int64.( > ) bytes max_byte_units_int
  then (
    warn [%string "Rounding large bytes, ... down to the maximum of ..."];
    Int64.(to_int_exn (max_byte_units_int / page_size)))
  else (
    let num_pages = Int64.( / ) bytes page_size in
    let num_pages_rounded_up =
      let open Int64 in
      if num_pages * page_size <> bytes then num_pages + one else num_pages
    in
    let num_pages_rounded_up_to_pow2_int = Int64.ceil_pow2 num_pages_rounded_up in
    ...
    Int64.to_int_exn num_pages_rounded_up_to_pow2_int)
;;
```

Defaults: ~4 MiB when the user is root; ~256 KiB when unprivileged
(rlimits restrict unprivileged users' locked-memory quota, and AUX
pages count against it).

### How long is "the last ~10 ms"?

The 10-ms figure is approximate. It's a function of:

- buffer size (`-m`),
- branch density of the workload,
- whether timing packets are enabled.

As a very rough rule of thumb, modern code with CYC on averages
~1 byte/branch after compression. A tight loop fills 4 MiB in a
handful of milliseconds; code that mostly waits on I/O can fit
seconds of history. Your mileage will vary, and if you hit "[decode
error: Overflow packet]" on every run, your mileage is vanishing —
increase `-m` or drop to `-timer-resolution Low`.

### What "snapshot" means at the hardware level

`perf record --snapshot` is a specific mode where perf **does not
stream the AUX ring to disk**. It lets the CPU keep rewriting the
ring, knowing the ring is conceptually "the last N bytes of
history". When a trigger fires (signal, ctlfd command, target
exit), perf:

1. Briefly stops the trace (MSR write).
2. Copies the AUX ring contents into `perf.data`.
3. Resumes (for multi-snapshot) or tears down (for single-snapshot).

The perf flags for these modes:

```ocaml
(* src/perf_tool_backend.ml:167-175 *)
let perf_snapshot_on_exit =
  Perf_capabilities.(do_intersect capabilities snapshot_on_exit)
in
let snapshot_opt =
  match snapshot_when with
  | Never -> []
  | At_exit when perf_snapshot_on_exit -> [ "--snapshot=e" ]
  | At_exit | Function_call -> [ "--snapshot" ]
in
```

`--snapshot=e` (kernel ≥ 5.4) is the convenience: perf handles
"snapshot on target-process exit" automatically. For earlier
kernels, magic-trace does it manually.

The trigger-to-snapshot communication goes through a small ctlfd
protocol:

```ocaml
(* src/perf_ctlfd.ml:3-7 *)
module Command = struct
  type t = string

  let snapshot = "snapshot\n"
  let stop = "stop\n"
end
```

Writing `"snapshot\n"` into perf's control fd is what triggers
step 1 above. (Before ctlfd existed — pre-5.10 — the same job was
done by sending `SIGUSR2`.)

### The direct backend's buffer

The direct backend skips perf entirely, using the same kernel
protocol. Its defaults:

```ocaml
(* direct_backend/manual_perf.ml:107-108 *)
?(data_size = 0x400000)
?(aux_size = 0x400000)
```

Both data and AUX at 4 MiB. `data_size` is the regular perf
mmap buffer (for sideband events); `aux_size` is the PT ring.
Whatever is read out of these is handed straight to libipt's
decoder.

---

## 6. Filtering — scoping the trace

Unfiltered, the CPU would emit PT for every thread on every core
continuously. That's useless and expensive. Filtering is how you
tell the hardware "only trace this process, in this privilege
mode, in this address range."

### Per-process filtering: CR3 match

Linux gives each process a unique CR3 (page-directory pointer).
`IA32_RTIT_CR3_MATCH` is an MSR holding a CR3 value; when set,
PT only generates packets when `CR3 == IA32_RTIT_CR3_MATCH`.
This is the filter installed by `perf record -p PID`. The kernel
reads the target's CR3 from its mm_struct and programs the MSR
before enabling tracing.

### Userspace vs kernel: USR/OS bits

Two bits in `IA32_RTIT_CTL` control privilege-mode gating:

- `IA32_RTIT_CTL.USR = 1`: trace ring-3 code.
- `IA32_RTIT_CTL.OS = 1`: trace ring-0 code.

perf exposes these with the familiar suffix syntax: `intel_pt//u`
(userspace only), `//k` (kernel only), `//uk` (both). magic-trace
plumbs them through `Trace_scope`:

```ocaml
(* src/trace_scope.ml:3-7 *)
type t =
  | Userspace
  | Kernel
  | Userspace_and_kernel
[@@deriving sexp_of, compare, equal]
```

```ocaml
(* src/perf_tool_backend.ml:226-230 *)
let perf_selector_of_trace_scope : Trace_scope.t -> string = function
  | Userspace -> "u"
  | Kernel -> "k"
  | Userspace_and_kernel -> "uk"
;;
```

So the `/u` in the perf event string comes from `Userspace`.

### Why kernel tracing needs root

The kernel refuses to let unprivileged processes see kernel code
flow for obvious reasons. magic-trace enforces this before even
asking perf:

```ocaml
(* src/perf_capabilities.ml:81-89 *)
let supports_tracing_kernel () =
  (* Only allow tracing the kernel if we are root. `perf` will start even without this,
     but the generated traces will be broken, so disallow it here.

     This check is technically stricter than it has to be. We could query the capability
     bits of the perf binary here instead, as per
     <https://perf.wiki.kernel.org/index.php/Perf_tools_support_for_Intel%C2%AE_Processor_Trace#Adding_capabilities_to_perf> *)
  Int.(Core_unix.geteuid () = 0)
;;
```

Strictly more than necessary — linux capabilities (`CAP_SYS_ADMIN`
on the perf binary) suffice — but `geteuid() == 0` is a reliable
proxy.

### Address-range filters

`IA32_RTIT_ADDR0_A`, `ADDR0_B`, `ADDR1_A`, `ADDR1_B`, up to four
pairs. Each pair defines a `[start, end)` range; tracing is
enabled only when IP falls inside one of the enabled ranges.

magic-trace does not expose these. An obvious hypothetical
enhancement would be "only trace libfoo.so" to shrink the buffer
for a noisy workload, but today you do that at decode time with
`-filter`.

### MODE.TSX

You can configure whether transactional regions are traced (and
whether aborts are marked). magic-trace leaves this at default and
surfaces aborts as `tx abrt` events in the stream; they bubble up
to the trace writer as `Event.Kind.Tx_abort`.

---

## 7. Gotchas

The practical issues you'll actually run into.

### Overflow packets

When the on-chip PT FIFO (a few hundred bytes) fills faster than
memory can drain it, the CPU inserts an OVF and drops state until
the next PSB. Everything between is lost. You'll see this in the
UI as:

```
[decode error: Overflow packet]
```

Triggers: tight branchy loops, CYC on high-IPC code, contention
with other users of the memory subsystem. Mitigations:

- `-timer-resolution Low` (fewer bytes emitted).
- Larger `-m` (the memory subsystem can drain into a larger
  buffer before backpressure reaches the FIFO).
- Filtering (if you can narrow CR3 or address range).

### Self-modifying code

The decoder reads bytes *now* and assumes they're the bytes that
ran *then*. If an instruction was patched between capture and
decode — JIT tier-up, dynamic dispatch table rewrite, hot-patching
— you get garbage output (usually plausible-looking garbage, which
is worse). magic-trace mitigates by running `perf script`
immediately after capture while the process is still alive, but
the window is non-zero.

### JIT symbols

If the tracee is a JIT (V8, Hotspot, OCaml's dynamic compilation),
addresses will land in anonymous mmap regions with no on-disk
backing. Without a companion `/tmp/perf-<pid>.map` file, the
decoder sees executable pages and can't resolve them to names. The
default backend falls back to `[unknown @ 0x...]` via
`Perf_map.Table.symbol` (`src/perf_map.ml`). Your JIT needs to
emit the map file.

### vDSO

The virtual Dynamic Shared Object — the kernel-provided page of
fast syscalls (clock_gettime, getpid) — is mapped into every
process but has no on-disk binary (it's synthesized at boot). The
default backend handles it because perf has built-in knowledge.
The direct backend does not, and says so:

```
(* direct_backend/README.md:10-14 *)
It works, but currently it doesn't support decoding usage of the Linux
vDSO, which means whenever a vDSO syscall like getting the current time
happens, it causes a trace decoding error leading to a short gap in the
trace.
```

### Virtualization

KVM's PT support is incomplete and was outright missing before
kernel 5.10. Most public-cloud Linux instances disable it (either
because the host kernel is old, or because the hypervisor simply
doesn't pass through the MSRs). When magic-trace runs on a VM
without PT, it logs:

```
Intel PT support not found. magic-trace will continue and use sampling instead.
```

(`src/collection_mode.ml:66-68`) and quietly falls back to §8's
world.

### Context switches

When the kernel migrates a thread from CPU A to CPU B, PT's ring
is per-CPU, so the thread's trace jumps between rings. The decoder
needs to stitch these together, which requires perf sideband
events (`PERF_RECORD_SWITCH`, `PERF_RECORD_SWITCH_CPU_WIDE`).
libipt-sb does this automatically; the default backend gets this
for free, the direct backend handles it via its sideband file.

### Don't confuse PT with its cousins

- **PEBS** (Precise Event-Based Sampling): statistical sampling
  with IP accuracy. Different feature.
- **BTS** (Branch Trace Store): older per-branch store. Much
  higher overhead, no compression, effectively deprecated.
- **LBR** (Last Branch Record): CPU ring of the last 16–32
  branches, sampled on interrupts. See §8.

They're all worth knowing about; they each solve a different
version of "give me branch information", but PT is the only one
that's complete, efficient, *and* retrospective.

### Capability fragility

Every PT-related feature landed in a specific kernel version:

```ocaml
(* src/perf_capabilities.ml:95-105 *)
(* Added in kernel commit eeb399b, which made it into 5.5. *)
let supports_kcore = kernel_version_at_least ~major:5 ~minor:5

(* Added in kernel commit ce7b0e4, which made it into 5.4. *)
let supports_snapshot_on_exit = kernel_version_at_least ~major:5 ~minor:4

(* Added in kernel commit d20aff1, which made it into 5.10. *)
let supports_ctlfd = kernel_version_at_least ~major:5 ~minor:10

(* Added in kernel commit 291961f, which made it into 5.14. *)
let supports_dlfilter = kernel_version_at_least ~major:5 ~minor:14
```

If a magic-trace feature does nothing on your box, it's usually
the kernel. Check `uname -r` and compare against the table.

"unknown event 'intel_pt'" when running `perf list` usually means
your kernel was built without `CONFIG_PERF_EVENTS_INTEL_PT=y`. Some
distro kernels ship it disabled.

---

## 8. PT vs LBR and perf sampling

The other two ways to approach "where is my program spending
time", and why magic-trace falls back to them.

### LBR — Last Branch Record

Every modern Intel (and now AMD) CPU has a small ring of the most
recent branches, typically 16 or 32 entries. The ring is per-CPU,
not per-packet-stream — it's just a rotating register file. You
sample it by taking a perf interrupt (say, every N cycles), then
dumping the ring.

Trade-off: you get stack context *only* at the sample points. Most
branches are never observed. A long-running loop gets sampled; a
one-shot function that runs once between samples is invisible.

magic-trace uses LBR when falling back to sampling:

```ocaml
(* src/callgraph_mode.ml:3-7 *)
type t =
  | Last_branch_record of { stitched : bool [@sexp.default true] }
  | Frame_pointers
  | Dwarf
```

`lbr-no-stitch` is available for environments where LBR stitching
(combining multiple sample rings into longer chains) misbehaves.

### Frame pointer / DWARF unwinding

Also sample-point-based. Instead of using a hardware ring, the
kernel walks the stack at each sample — either by following frame
pointers (`fp`, fast but needs `-fno-omit-frame-pointer`) or by
interpreting DWARF unwind info (`dwarf`, slower but more robust).

Both are cheaper than LBR in overhead terms but lose even more
fidelity between samples.

### BTS

For completeness: Branch Trace Store was a pre-PT per-branch
mechanism. It recorded every branch to a DRAM-backed store
without compression. Overhead was punishing — 10–40× slowdown is
typical — and it's been effectively replaced by PT.

### PT vs sampling summary

| Property          | PT                            | Sampling (LBR/DWARF/FP)  |
|-------------------|-------------------------------|--------------------------|
| Coverage          | every branch                  | periodic samples         |
| Overhead          | 2–10%                         | 1–5%                     |
| Retrospective     | yes (ring snapshot)           | no                       |
| Works in VMs      | usually not                   | yes                      |
| Needs Intel       | yes                           | no (AMD has LBR too)     |
| Needs the binary  | yes                           | yes (for resolution)     |
| Decode complexity | high (libipt)                 | low                      |

### magic-trace's fallback

Pre-run probe:

```ocaml
(* src/collection_mode.ml:60-70 *)
let select_collection_mode ~extra_events ~use_sampling =
  match use_sampling with
  | true -> Stacktrace_sampling { extra_events }
  | false ->
    (match Core_unix.access "/sys/bus/event_source/devices/intel_pt" [ `Exists ] with
     | Ok () -> Intel_processor_trace { extra_events }
     | Error _ ->
       Core.eprintf
         "Intel PT support not found. magic-trace will continue and use sampling instead.\n";
       Stacktrace_sampling { extra_events })
;;
```

Explicit `-sampling` forces it; otherwise magic-trace checks for
the PT event-source sysfs node and downshifts gracefully if
absent. **`Callgraph_mode` is only consulted under the sampling
branch** — Intel PT produces its own call graph for free, so the
flag is ignored otherwise.

---

## 9. Putting it all together: a magic-trace session through the PT lens

With everything above in hand, here's what happens *in hardware*
during `magic-trace attach -pid X`. The code narrative is in
`codebase_tour.md` §7; this is the complement.

1. **Capability probe.** magic-trace reads `/sys/bus/event_source/devices/intel_pt`
   and `/proc/cpuinfo`; detects PT support, decides on collection
   mode, timer resolution, buffer size, ctlfd availability.
   (`src/perf_capabilities.ml:107-122`)
2. **perf record fork.** magic-trace builds the argv at
   `src/perf_tool_backend.ml:507-520` and forks `perf`. The argv
   carries `intel_pt/cyc=1,cyc_thresh=1,mtc_period=0/u` (for
   Normal / userspace), `--snapshot` (ring mode, don't auto-drain
   to disk), `-m,NUM_PAGES` (AUX ring size), `--control=fd:RX,TX`
   (command pipe), `-p PID` (CR3 filter).
3. **Kernel setup.** perf opens a `perf_event_open` fd of type
   `PERF_TYPE_RAW`, attribute `intel_pt`. The kernel allocates
   ToPA pages, writes `IA32_RTIT_CR3_MATCH` to the target's CR3,
   sets `IA32_RTIT_CTL` with USR=1, CYC=1, and enables tracing.
4. **Continuous emission.** The CPU begins streaming PSB, TNT,
   TIP, FUP, MODE, CYC, MTC, TSC packets into the AUX ring. The
   ring wraps; history older than ~ring_size bytes is lost.
5. **Trigger.** Either you Ctrl+C magic-trace (SIGINT → signal
   handler fills `done_ivar` → breakpoint poll loop exits), or a
   hardware breakpoint installed via `perf_event_open(PERF_TYPE_BREAKPOINT)`
   fires when the target enters the trigger function.
6. **Snapshot.** magic-trace writes `"snapshot\n"` to the ctlfd
   pipe. perf reads it, sends the kernel a snapshot ioctl. Kernel
   briefly stops the trace, copies the AUX ring contents into
   `perf.data`, re-enables the trace. magic-trace blocks for ack.
7. **Shutdown.** magic-trace writes `"stop\n"`; perf disables
   tracing (clears `IA32_RTIT_CTL.TraceEn`), flushes remaining
   ring content, exits. magic-trace reaps.
8. **Decode.** magic-trace spawns `perf script --itrace=bep
   --dlfilter ...`. perf reopens `perf.data`, hands the PT bytes
   to libipt along with the loaded-binaries model. libipt walks
   the binary, consuming TNT/TIP/FUP/etc., emitting synthetic
   events. perf prints them as text.
9. **Parse.** magic-trace regex-parses each line
   (`src/perf_decode.ml:10-39`), resolving symbols three ways
   (perf symbol, perf-map, `[unknown]`), producing a pipe of
   `Event.t` values.
10. **Reconstruct.** `Trace_writer` (`src/trace_writer.ml`)
    consumes the pipe, maintains per-thread stacks, handles PGE/PGD
    as `[untraced]` bands, handles kernel entries and TSX
    transactions, distributes same-timestamp events across a time
    window.
11. **Write.** `Tracing_zero.Writer` encodes to Fuchsia Trace
    Format; the `.gz` suffix triggers gzip. The file lands as
    `trace.fxt.gz`.
12. **View.** Drop `trace.fxt.gz` onto `magic-trace.org` (a lightly
    modified Perfetto). You see the hardware's work, rendered as
    call stacks at nanosecond resolution.

The hardware did the whole middle of this without knowing what a
function was. Everything you see in the UI — calls, returns,
durations, kernel bands, untraced regions — was reconstructed by
software from a couple of kilobytes of packets per millisecond
of execution.

---

## 10. Further reading

- **Intel Software Developer's Manual, Volume 3B, Chapter 35**
  ("Intel Processor Trace") — the authoritative spec. Bit layouts,
  MSR semantics, capability enumeration. Dense, but no substitute
  for the real thing.
- **`man perf-intel-pt`** and the kernel tree's
  `tools/perf/Documentation/intel-pt.txt` — the practitioner's
  reference for the perf side.
- **libipt source** (`github.com/intel/libipt`) — especially the
  `ptxed` example, which is the canonical "minimal PT decoder."
  Reading its main loop is a great way to make §3's algorithm
  concrete.
- **Linux kernel PT driver**: `arch/x86/events/intel/pt.c` — how
  the kernel programs the MSRs, handles ToPA, exposes AUX to
  userspace.
- **Tristan Hume's original magic-trace write-up** (linked from
  the project wiki) — the motivation, design retrospective, and
  some war stories.
- **Back to `docs/codebase_tour.md`** — with the hardware model
  now clear, the code will read differently. §5 ("capture
  pipeline") and §6 ("decode + write") are where PT
  knowledge becomes most valuable.
