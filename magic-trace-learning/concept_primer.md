# magic-trace concept primer, for listening

A hundred short entries, each with the same shape: a title, a short overview, and a longer explanation. Built from first principles. Designed to be read aloud.

---

## 1. What a CPU does, one instruction at a time

**Overview.** Before we can talk about tracing, we need a shared picture of what the CPU is actually doing moment to moment. A C-P-U fetches one instruction, does what it says, advances a pointer to say what comes next, and repeats — billions of times a second. Magic-trace is a tool for observing that loop from the outside without slowing it down. Every later concept rests on this one.

**Detailed.** Let me ask you: what does a C-P-U actually do, at its most mechanical level? The answer is surprisingly boring, which is a good thing. Inside the chip there's a register called the instruction pointer — think of it as a bookmark into the memory of your program. The C-P-U looks at where the bookmark is pointing, reads a few bytes of memory there, interprets those bytes as a machine instruction, carries out whatever the instruction says, advances the bookmark, and goes again. That loop — fetch, execute, advance, repeat — is the heartbeat of every program you've ever run.

Most instructions just move data around or do arithmetic. A move from here to there, a multiply this by that, a load a value from memory into a register. These don't change the bookmark in any exciting way; they just nudge it forward by the length of the instruction.

A small minority of instructions are branches — jumps, calls, conditional branches, returns. These are the instructions whose whole job is to move the bookmark somewhere else. When you write an if in C, the compiler emits a conditional branch. When you call a function, it emits a call. When you return from one, it emits a return.

Here's the part that matters for magic-trace. The branches are the rare events. In typical code, maybe one instruction in ten is a branch. The other nine are silent, predictable arithmetic that nobody needs to trace. Intel Processor Trace, the hardware feature magic-trace is built on, was designed around exactly that observation. Up next: the instruction pointer itself, in a little more detail.

---

## 2. The instruction pointer and control flow

**Overview.** The instruction pointer is the one piece of C-P-U state that magic-trace really cares about. It's the register that says where in memory the next instruction lives. All of tracing, in one sentence, is the problem of reconstructing the history of that register over time.

**Detailed.** On a 64-bit Intel chip, this register is called R-I-P — "instruction pointer" with an R prefix meaning the 64-bit version. You can forget the prefix; everyone just says "I-P" or "instruction pointer." Whatever you call it, it points into memory at the next instruction to execute. When the C-P-U finishes one instruction, it updates the I-P. Sometimes the update is obvious: "advance by the length of the instruction I just finished." Sometimes the update is interesting: "oh, that was a branch, so jump somewhere else."

The whole tracing question — what did my program actually do? — is really a question about the history of the I-P. If you could plot it over time, with time on one axis and memory addresses on the other, you'd see a jagged line zig-zagging from place to place. Straight-line code would be short diagonal segments as the I-P walks forward through consecutive instructions. Function calls would be big vertical jumps to a new address. Returns would be jumps back. Loops would look like a zigzag visiting the same small range over and over.

Now here's a question worth sitting with: do we actually need to know the I-P at every single instruction? It turns out no, we do not. Between branches, the I-P moves predictably — by the length of whatever instruction is at that address, which anyone with the binary in hand can compute. What's unpredictable, and therefore interesting to record, is every point at which the I-P changes direction. That's why the hardware tracing feature focuses on branches. Everything else can be reconstructed.

We'll talk about that reconstruction later. Up next: the split between branches whose destination is obvious from the binary and branches whose destination is not.

---

## 3. Direct versus indirect branches

**Overview.** Not all branches are equal. A direct branch has its destination baked into the instruction bytes. An indirect branch computes its destination at runtime from a register or a memory location. That distinction is load-bearing for tracing, because a decoder can predict direct branches for free but needs help with indirect ones.

**Detailed.** Let me ask you: when the compiler emits a "call printf" instruction, where does the C-P-U know to go? The answer depends on the linker. In the simplest case, the call instruction literally contains the target address in its own bytes. The instruction says: I am a call, and I go to address zero-x-four-hundred-one-thousand. That's a direct call. Anybody reading the bytes of the program can tell you where it goes, without ever running anything.

Now contrast that with a call through a function pointer. Imagine a C program that stores a function pointer in a variable, then calls it. The compiled instruction says something like: go to whatever address is currently in register R-A-X. What's in R-A-X? Depends on the runtime. Maybe it points at "foo" this time and "bar" next time. That's an indirect call, and the instruction bytes alone tell you nothing about where it goes.

The same split applies to jumps and returns. A plain "jump to label" is direct. A jump through a jump table — the kind a big switch statement might compile to — is indirect. Every return instruction is indirect, because it pulls its target address off the stack at runtime.

This is one of the most important facts in all of magic-trace. Here's why. If you're decoding a trace and you want to know what happened after a direct branch, you can figure it out by reading the binary. The destination is right there in the bytes. You don't need the C-P-U to tell you anything. But if you see an indirect branch, you have no idea where it went without help. The hardware trace feature has to step in and emit, literally, the address where the branch landed. That's where the real information density of a trace lives.

Up next: the idea of instruction retirement, which is when the C-P-U considers a branch "really done."

---

## 4. What instruction retirement means

**Overview.** Modern C-P-Us do not execute instructions strictly in order. They execute them out of order, speculatively, and then commit the results in the original program order. That commit step is called retirement. Intel Processor Trace only cares about retired branches, and that's deliberate.

**Detailed.** Here's a thing that trips people up. When you write C code, you picture the C-P-U taking your instructions one by one and running them in order, top to bottom. That's the mental model. The reality is much weirder. A modern chip has many execution units running in parallel; it will fetch twenty instructions ahead of where it "really" is; it will start executing some of them before it knows whether their preconditions are met; and it will sometimes speculate down a branch that turns out to be wrong.

When the C-P-U speculates wrong — it guesses a conditional branch will be taken, starts executing the "taken" path, then finds out it should have fallen through — it has to throw away all the work it did down the wrong path. It does so, backs up, and goes down the correct path instead. That wrong-path work never happened, from the program's point of view.

Retirement is the moment when an instruction graduates from "speculation" to "this really happened, it's part of the record." An instruction retires in program order, even if it executed out of program order. Intel's tracing hardware is careful to only emit packets for retired branches. Speculative paths do not show up in the trace, and a good thing too — otherwise your trace would be full of work the program never actually did.

This is why you can trust magic-trace's output. The branches shown are the branches that really ran. Any branch the C-P-U speculatively tried and aborted is invisible. Up next: how the C-P-U keeps time, which matters because branches alone aren't very useful without timestamps.

---

## 5. Cycles, frequency, and why clock rates change

**Overview.** The C-P-U's clock is not a fixed thing. It speeds up and slows down dynamically. That's a problem for any tracing system that wants to translate hardware cycle counters into human wall-clock time. Intel Processor Trace solves it with a specific packet that tells the decoder when the frequency changed.

**Detailed.** It would be nice if the C-P-U always ran at a single fixed frequency. Then one cycle would be the same amount of time as any other cycle, and converting cycle counts to nanoseconds would be a single multiplication. In practice, the chip constantly adjusts its clock rate for power and thermal reasons. Under heavy load, the turbo logic cranks it up well past the rated frequency. Under light load or when the die gets too hot, it throttles down, sometimes dramatically.

That means a cycle is not a fixed unit of time. A cycle while the chip is running at four gigahertz is a quarter of a nanosecond. A cycle while the chip is running at one gigahertz is a full nanosecond — four times longer. If you measure a branch as happening at cycle count ten million, that number on its own is meaningless until you know what frequency the core was running at.

Because this matters, Intel's tracing hardware emits a packet — we'll give it the name in a later entry — every time the core's frequency changes. The packet is small. It just says: as of now, I'm running at this ratio relative to my base frequency. The decoder sees it, updates its conversion factor, and can continue translating cycles to nanoseconds correctly.

For magic-trace users, this usually just works. You don't configure it; the hardware emits the frequency-change packet automatically when it changes state, and the decoder consumes it automatically. The reason to know about it is that if you see odd timing discontinuities in a trace — a region that looks compressed or stretched compared to neighboring code — frequency changes are one plausible cause.

Up next: the invariant timestamp counter, which is the one clock that doesn't care about any of this.

---

## 6. The invariant timestamp counter

**Overview.** Modern Intel chips have a special timestamp counter that, unlike most hardware counters, ticks at a constant rate regardless of what the core is doing with its frequency. It is the wall clock of the C-P-U. Magic-trace relies on it to give events real nanosecond timestamps.

**Detailed.** There's a register on every Intel core called the time-stamp counter, or T-S-C. On old chips, the T-S-C was tied to the core's clock — when the core sped up or slowed down, the T-S-C ticked faster or slower. That made it unreliable as a wall clock, because the same amount of real time would produce different numbers depending on what the core was doing.

Sometime around the Nehalem generation, Intel added a property called "invariant T-S-C." On an invariant-T-S-C chip, the counter ticks at a fixed rate no matter what — independent of frequency, independent of sleep states, independent of turbo. If you read it twice and subtract, you get a real elapsed duration, in units of some fixed base frequency the chip was designed around.

Nearly every machine magic-trace runs on has invariant T-S-C. You can assume it's there. The tracing hardware uses it to emit timestamp packets at known points in the stream, and the decoder uses those packets as anchors to assign wall-clock time to every subsequent event.

The conversion is not one-to-one with nanoseconds. T-S-C ticks are in some hardware-defined unit; the kernel measures the conversion factor at boot and exposes it to userspace through a small structure called the perf memory-mapped page. That structure contains three numbers — a multiplier, a shift, and a zero offset — and the formula "multiply, shift right, add zero" turns a T-S-C tick into a nanosecond.

You do not need to remember the formula. You just need to know that the T-S-C is the foundation clock, that it's reliable, and that the kernel gives software everything it needs to convert T-S-C ticks into real time.

Up next: a special kind of register called a model-specific register, which is how software configures the whole tracing apparatus.

---

## 7. Model-specific registers

**Overview.** Alongside the normal general-purpose registers like R-A-X and R-C-X, the C-P-U has a second population of registers that control its behavior — enabling features, configuring caches, setting up tracing. They're called model-specific registers, or M-S-Rs. Only the kernel can read or write them.

**Detailed.** Picture two separate register files on the chip. The first is the set of registers that ordinary programs use: general-purpose registers for holding values, floating-point registers, vector registers. These are addressed by name — R-A-X, X-M-M-zero, and so on.

The second set is much larger — there are thousands of model-specific registers on a modern C-P-U — and it's used to configure the C-P-U rather than compute with it. Want to enable a hardware feature? Write to an M-S-R. Want to program a performance counter? Write to an M-S-R. Want to turn on Intel Processor Trace? You guessed it — write to a specific M-S-R.

M-S-Rs are addressed by number rather than by name. There are two instructions, read-M-S-R and write-M-S-R, and both take the M-S-R number as an argument and either return a value or write one. Because writing an M-S-R can change fundamental C-P-U behavior — and mistakes can crash the whole machine — these instructions only work from ring zero. That means only the kernel can touch M-S-Rs directly.

For magic-trace, this means user code never programs the tracing hardware itself. What happens instead: user code makes a system call, via the perf subsystem, asking the kernel to set up a trace. The kernel, running in ring zero, writes the relevant M-S-Rs on the user's behalf. When user code wants to stop the trace, it makes another system call; the kernel writes the M-S-Rs to disable tracing.

You'll sometimes see an error message mentioning M-S-R zero-five-seventy. That's a hexadecimal number naming a specific M-S-R — the one that controls tracing enable. When you see that error, it means the kernel tried to enable tracing by writing to that M-S-R and got denied, usually because you're inside a virtual machine that doesn't expose M-S-Rs.

Up next: the privilege levels that make "only the kernel can" meaningful.

---

## 8. Privilege levels — ring zero and ring three

**Overview.** Intel C-P-Us have four privilege levels, called rings, numbered zero through three. Ring zero is for the kernel and can do anything. Ring three is for user programs and can do almost nothing dangerous. Rings one and two exist but aren't used on Linux. This is why system calls have to cross rings, and why tracing privileges matter.

**Detailed.** Pretend for a moment you're the person designing a C-P-U. Your machine is going to run untrusted programs — arbitrary code that a user downloaded from the internet. How do you stop one program from reading another's memory, or writing to the disk directly, or reprogramming the hardware? The answer is privilege levels.

At any moment the C-P-U is running in some privilege ring. If it's in ring zero, it can do anything — read and write any memory, talk to any device, program M-S-Rs. If it's in ring three, it is severely restricted — it can only access the memory the kernel has explicitly allowed, and a lot of instructions will fault if it tries to use them.

The kernel lives in ring zero. Your browser, your text editor, all your shells — those live in ring three. When you run a program, the kernel loads it, sets up its memory, and jumps to its entry point in ring three.

The only ways to cross rings are controlled. A ring-three program cannot just decide to go to ring zero — it has to ask, via a system call or a hardware exception or an interrupt. The C-P-U supports these crossings with special instructions and mechanisms. When you issue a system call, the C-P-U flips the ring bit, your code starts running in ring zero at a specific kernel entry point, the kernel does its thing, and when it's done it flips back to ring three and resumes where you left off.

For magic-trace this matters in two ways. First, programming the tracing hardware requires ring zero, which means user tools have to ask the kernel. Second, tracing can be scoped to ring three only, or ring zero only, or both. Tracing ring zero lets you see what the kernel is doing; we'll discuss why that requires being root.

Up next: the biggest abstraction the kernel maintains per process — virtual memory.

---

## 9. Virtual memory, briefly

**Overview.** Every process on Linux has its own private view of memory. Addresses in one process don't mean the same thing as the same addresses in another process. The machinery underneath — page tables — is how the kernel maintains that illusion. Magic-trace uses a piece of this machinery to scope tracing to a single process.

**Detailed.** Let me ask you: if two processes both read address zero-x-four-hundred-one-thousand, do they see the same byte? The answer is almost always no. Each process has its own address space, maintained by a data structure called a page table. A page table is a tree of entries that maps virtual addresses — the addresses programs use — to physical addresses — the actual electrical locations in D-R-A-M.

The unit of mapping is a page, typically four kilobytes. When a process says "read address V," the C-P-U walks the page table to find the physical address that V currently maps to, and then reads that physical address. If the page table says V isn't mapped to anything, the C-P-U raises a page fault and the kernel handles it — either by installing a fresh page of memory there or by killing the process if it shouldn't have touched that address.

Each process has its own page table. That's how process A's address zero-x-four-hundred-one-thousand can map to one place in physical memory while process B's same virtual address maps to somewhere totally different. The kernel tracks these page tables and, on every context switch between processes, tells the C-P-U to use a different one.

The mechanism for telling the C-P-U which page table to use is the topic of the next entry. But know now that the whole multi-process illusion Linux maintains is built on the page-table switch. When two processes seem to run at the same time, what's really happening is that the scheduler alternates them rapidly, switching page tables every time it switches which process is on the core.

Understanding this mechanism is the prerequisite to understanding how magic-trace scopes tracing to one process at a time. Up next: the specific C-P-U register that names the current page table.

---

## 10. The C-R-three register as per-process identity

**Overview.** C-R-three is the C-P-U register that holds the physical address of the current process's top-level page table. Because each Linux process has a unique page table, the value in C-R-three is a perfect stand-in for "which process is running on this core right now." Intel Processor Trace uses exactly this register to implement per-process filtering.

**Detailed.** I just said that each process has its own page table. The next question is: how does the C-P-U know which page table to use? The answer is a register called C-R-three, short for control register three. It holds the physical address of the root of the current process's page table tree. When the C-P-U wants to translate a virtual address to a physical one, it starts by reading C-R-three, going to that address, and walking the tree from there.

When Linux context-switches from process A to process B, one of the key things the scheduler does is write the new process's page-table root into C-R-three. From that instant on, every memory access the core does is interpreted through process B's address space. Process A's memory isn't gone — it's still in D-R-A-M somewhere — it's just no longer reachable by any virtual address, because the page table in use no longer maps to it.

Here is where things start coming together. Because C-R-three uniquely identifies a process's address space, it also effectively identifies the process. Two processes have different page tables, and therefore different values of C-R-three. If you know a process's C-R-three value, you can watch the hardware and tell exactly when that process is running on a core — it's whenever C-R-three matches.

Intel Processor Trace has a dedicated M-S-R that says: only emit tracing packets when C-R-three matches this specific value. When magic-trace attaches to a P-I-D, what really happens at the hardware level is this. The kernel looks up that process's C-R-three value, programs it into the C-R-three-match M-S-R, and enables tracing. From then on, tracing automatically turns itself on when the target process runs and off when any other process runs. The hardware doesn't know about P-I-Ds — that's an operating-system concept. It just knows about C-R-three values.

Up next: memory-mapped I-O, which is how the kernel gives user-space tools a window into the tracing buffer.

---

## 11. Memory-mapped I-O and mmap

**Overview.** User-space programs can ask the kernel to expose a region of physical memory, or a file, as a block of virtual memory they can read and write directly, without system calls. The primary mechanism is called mmap. Magic-trace uses mmap to read the Intel Processor Trace buffer that the hardware is writing into.

**Detailed.** Normally, when a user program wants to read from a file, it calls read, which is a system call. The kernel handles it, copies bytes from somewhere into the program's buffer, and returns. Every such read costs a ring transition. That's fine for occasional I-O but terrible for high-bandwidth data.

Memory-mapped I-O is an alternative. The program makes one system call, called mmap, that asks the kernel to "wire up" a region of the program's virtual address space so that it points at something — a file, a device, or a chunk of memory the kernel manages. After that, the program can read and write that region using ordinary loads and stores. No more system calls per access.

This is how perf exposes tracing data to user-space tools. The kernel sets up a physical memory region that the hardware tracing unit will write packets into. Then the kernel memory-maps that region into the perf-event file descriptor that user-space opened. The user-space tool, in this case the perf binary or magic-trace's direct backend, can read that region as if it were a regular array of bytes. The hardware writes; user-space reads. No kernel involvement on the critical path.

Mmap also has another role in tracing. When the program loads a shared library, the kernel records that fact and can publish it as an event on the perf stream — specifically, as a packet of metadata that says "this process just mmap'd this file at this address." The decoder sees that metadata and updates its model of what binary is loaded where. That's critical for symbol resolution later.

So remember two uses of mmap in this context. First, it's the mechanism by which user-space tools read the tracing buffer. Second, it's an event the kernel reports, so the decoder knows what binaries were loaded.

Up next: processes and threads, and why the kernel's idea of them matters.

---

## 12. Processes and threads, from the kernel's view

**Overview.** The kernel does not really distinguish processes from threads. Both are tasks — scheduleable units with a thread I-D. What varies is how much state they share. Magic-trace picks one or more tasks to trace, and everything else in its capture pipeline flows from that choice.

**Detailed.** On Linux, the kernel's core concept is the task. A task has an identifier called a thread I-D, or T-I-D. It has a set of registers, a stack, a scheduling state — all the usual suspects. When the scheduler decides which piece of code to run next on a core, it picks a task.

What we call a process is actually a group of tasks that happen to share some resources. All the threads of a process share the same virtual address space — same page table, same C-R-three value. They share open file descriptors. They share signal handlers. What they don't share is each thread's own stack and registers.

The kernel gives each process a process I-D, or P-I-D. If you look at slash-proc-slash-some-number-slash-status, the status file contains both the P-I-D and the T-I-D. For a single-threaded process, the two are equal. For multi-threaded processes, there's one P-I-D shared by all the threads, and each thread has its own unique T-I-D.

Magic-trace cares about this distinction in a couple of places. The hardware filter, remember, is keyed on C-R-three, which is per-process. So if you ask to trace P-I-D one thousand, the hardware automatically traces all of that process's threads, regardless of which core they run on. That's almost always what you want.

In the text perf emits for each event, you'll see both numbers — a P-I-D and a T-I-D, separated by a slash. Magic-trace uses them to organize the output. Each unique T-I-D becomes a separate track in the final Perfetto-style visualization, so you can see each thread's timeline side by side.

Up next: context switches, which are what happen when the kernel takes one task off a core and puts another on.

---

## 13. Context switches and the scheduler

**Overview.** A context switch is the moment the kernel takes one task off a C-P-U core and puts a different task on. During a switch, the page tables are swapped, the registers are saved and restored, and tracing hardware either resumes or goes quiet. Understanding this moment is important because it's where a lot of "why did my trace get weird" questions come from.

**Detailed.** Here's the rough picture. The kernel has a scheduler — a component that decides, many times per second, which task should run on each core. When the scheduler decides to preempt task A in favor of task B, the following happens. The kernel saves A's registers into a kernel-owned data structure, writes B's registers into the C-P-U, swaps C-R-three to point at B's page table, and jumps to where B was last running. From B's point of view, nothing unusual happened — it just resumed where it left off, possibly milliseconds or seconds later.

For tracing, the critical thing is what happens to C-R-three during the switch. If the tracing hardware is filtering on process A's C-R-three value, then the moment the scheduler writes process B's C-R-three, the hardware stops emitting packets. When the scheduler later switches back to A, C-R-three matches again, and packets resume.

That's good news in one sense. The filter "just works" across context switches. Your target process's tracing automatically pauses when it's not running and resumes when it is. You don't have to handle it manually.

But it's also the source of subtle issues. If the target thread moves between cores — the scheduler frequently migrates threads for load-balancing reasons — then its trace ends up scattered across the per-core ring buffers. A decoder needs sideband events describing the migrations in order to stitch the trace back together coherently. Intel's reference decoder library handles that; magic-trace's default backend gets that handling for free via perf.

So when you run magic-trace, your process may be running on many different cores over time. Its trace is being written to many different per-core buffers. The decoder reassembles those into one coherent per-thread timeline.

Up next: system calls, which are the mechanism a user program uses to ask the kernel to do something.

---

## 14. System calls as ring transitions

**Overview.** A system call is how a user-space program asks the kernel to do something on its behalf — read a file, send data to a socket, start a new process. Mechanically, it's a hardware feature: a controlled jump from ring three to ring zero and back. Magic-trace uses system calls pervasively to configure tracing and to communicate with perf.

**Detailed.** When your program calls "read" in C, the actual machine code that runs is not a regular function. It's a wrapper in the C standard library that puts the system-call number into a specific register, the arguments into other specific registers, and then issues a special instruction — on modern x-eighty-six, that's "syscall." The C-P-U recognizes this instruction and does something remarkable: it flips the privilege level from ring three to ring zero and jumps to a kernel entry point.

Now you're in the kernel. The kernel reads the system-call number from where the wrapper left it, dispatches to the right handler, does the work, and eventually hits an instruction that returns to ring three. Your program resumes immediately after the syscall instruction, with a return value waiting in a specific register.

All of this feels like a function call from the user's point of view, but under the hood it's a hardware transition between privilege levels. That's why syscalls are expensive — not enormously so, but they involve saving and restoring state, switching stacks, and traversing a privilege boundary.

For tracing, syscalls matter in two specific ways. First, the tracing hardware can be configured to capture syscalls as events, so you see them in the trace with names like "s-y-s-underscore-read" or "do-underscore-syscall-underscore-sixty-four." Second, all of the configuration that enables or disables tracing, sets the buffer size, or arms a snapshot trigger happens via a syscall called perf-event-open. More on that shortly.

You might see syscalls in your traces even without explicitly asking for them. That's because even pure user-space tracing records the fact of a syscall happening — the hardware has to, since syscalls cross into ring zero and the trace of ring-three code has to stop briefly.

Up next: signals, which are Unix's ancient inter-process notification mechanism.

---

## 15. Signals as lightweight I-P-C

**Overview.** Signals are small integer notifications the kernel can deliver to a process asynchronously. They're among the oldest ways for one program to tell another to do something. Magic-trace uses signals both to receive Ctrl-C from the terminal and, on older kernels, to tell the perf process to take a snapshot.

**Detailed.** Picture a signal as a flag the kernel sets on a process. There are a few dozen possible signals, each with a number and a name — S-I-G-I-N-T for interrupt, S-I-G-T-E-R-M for termination, S-I-G-U-S-R-two for user-defined number two, and so on. When a signal is delivered, the kernel interrupts whatever the target process is doing and either runs a handler function that the program has registered, takes the default action, or kills the process.

Magic-trace uses signals in a couple of places. The first, and most visible, is Ctrl-C. When you press Ctrl-C in the terminal, the shell sends S-I-G-I-N-T to the foreground process. Magic-trace has a handler that sees the signal and starts its shutdown path — ask perf to take a snapshot, wait for it, finalize, and decode.

The second use is internal. On older kernels that don't support a newer mechanism we'll talk about soon, magic-trace tells perf to take a snapshot by sending it S-I-G-U-S-R-two. Perf has its own handler for that signal which says "okay, pause tracing, dump the buffer to disk, resume." S-I-G-T-E-R-M is used similarly to ask perf to shut down cleanly.

Signals have a few awkward properties. They're asynchronous, meaning they can arrive at almost any point in a program's execution. That makes them hard to reason about. They don't carry much information — just the signal number, and maybe a small extra value in newer variants. And because they depend on process identity, they tie magic-trace and perf together tightly at the P-I-D level.

For these reasons, modern Linux has introduced a more structured alternative called a control file descriptor, which we'll discuss in a later entry. But on any kernel older than version five point ten or so, signals are what magic-trace uses.

Up next: file descriptors and pipes, which are the alternative communication mechanism.

---

## 16. File descriptors and pipes

**Overview.** A file descriptor is a small integer the kernel gives a process to refer to an open resource — a file, a socket, a pipe. A pipe is a pair of descriptors, one readable and one writable, connected by a kernel-managed buffer. Magic-trace uses pipes to talk to perf through its newer control interface.

**Detailed.** When a process opens a file, the kernel doesn't hand it back a file object or a pointer. It hands it back a small non-negative integer — a file descriptor, often abbreviated F-D. The F-D is a key into a kernel-maintained table, specific to that process, which stores the actual resource. Every subsequent operation — read from, write to, close — takes the F-D as its first argument.

F-Ds don't have to refer to real files. They can refer to sockets, to pipes, to anonymous memory regions, to event notification objects. On Linux, nearly everything with a lifecycle gets an F-D. It's a wonderfully uniform interface.

A pipe is one such resource. You ask the kernel for a pipe, and you get back two F-Ds — a read end and a write end, connected by a kernel buffer. Anything you write to the write end can be read from the read end, in F-I-F-O order. If there's nothing to read, the reader blocks until something arrives. If the buffer fills up, the writer blocks until space is available.

Pipes are a primary inter-process communication mechanism on Unix. They're reliable, ordered, and cheap. You'll see them everywhere — shells use them for the command-line pipe operator, init systems use them for IPC, and so on.

Magic-trace creates two pipes when it starts perf. One pipe is used to send commands to perf — literally strings like "snapshot" or "stop," written into one end and read by perf on the other end. The second pipe is used to receive acknowledgments back from perf. This pair of pipes, set up as specific file descriptors visible to perf, is called the control file descriptor protocol. It replaces the older signal-based approach.

We'll go into that protocol in a later entry. For now, the takeaway is that file descriptors and pipes are the raw Unix primitives out of which magic-trace builds more sophisticated communication with the perf process.

Up next: ptrace, the debugger hook.

---

## 17. Ptrace — the debugger hook

**Overview.** Ptrace is a system call that lets one process control and inspect another. It's the mechanism every Unix debugger is built on. Magic-trace uses it for exactly one purpose: to launch a new program in a stopped state so that tracing can be armed before a single instruction of the target runs.

**Detailed.** The ptrace system call is a swiss-army knife. It can attach one process to another, halt a running process, read or write its registers and memory, single-step it, resume it, and detach. Debuggers like g-d-b are built on top of ptrace.

For magic-trace, though, ptrace has a narrow role. Consider the "run" subcommand, which spawns a new target program and traces it. You want tracing to be armed before the program's first instruction runs, so you don't miss the interesting early part of its execution. How do you do that?

The technique is called P-T-R-A-C-E-underscore-T-R-A-C-E-M-E. The magic-trace tool forks itself. The child process, before doing anything else, issues a ptrace call that says "I am going to be traced." Then it calls exec to replace itself with the target program. The kernel notices the trace-me flag, executes exec, but before the target program's first instruction, raises S-I-G-T-R-A-P and puts the process into a stopped state.

The parent process sees the stop, knows the child is waiting at its entry point with zero instructions executed. This is the moment to attach perf to the P-I-D, set up the ring buffer, and enable tracing. Then the parent issues another ptrace call, P-T-R-A-C-E-underscore-D-E-T-A-C-H, which tells the kernel "thanks, stop tracing, let the child run normally." The child resumes, tracing is already armed, and the first instruction it executes is captured.

There is no ptrace involved in the "attach" subcommand — perf attaches to an already-running P-I-D directly, and ptrace is not needed. And once the target is running under perf's control, ptrace is out of the picture. It's really just used as a starting gate for the run mode.

Up next: the perf-event subsystem, which sits under both the perf command-line tool and magic-trace.

---

## 18. The perf-event subsystem

**Overview.** Perf is a Linux kernel subsystem that exposes hardware and software performance-monitoring features to user-space through a single system call. Magic-trace never programs the tracing hardware directly; it goes through perf, either by invoking the perf binary or, in the experimental backend, by calling perf's system call directly.

**Detailed.** When people say "perf," they often mean two different things. The first is a user-space command-line tool that ships with the Linux kernel. You run perf record, perf report, perf script, and so on. The second is the kernel subsystem that this tool talks to. The subsystem, for our purposes, is the more interesting one.

At the heart of the subsystem is a single system call: perf-event-open. It takes a big structure describing what you want to measure — a hardware event, a software event, a tracing event — and returns a file descriptor. That F-D is a handle onto the event. You can memory-map it to get a buffer where samples are deposited. You can use I-O-C-T-L calls on it to enable, disable, or reset the event. You can poll it for readability to know when data is available.

The perf subsystem is how the kernel abstracts away a whole menagerie of hardware differences. Intel's hardware performance counters are different from A-M-D's, which are different from A-R-M's. Perf papers over them with a uniform A-P-I. When magic-trace asks for an Intel-P-T event, it's using the same perf-event-open system call that magic-trace would use to ask for a cycle counter or a cache-miss counter.

The command-line perf tool is just a program that uses perf-event-open to set things up, then spawns subprocesses, gathers data, and presents it. Magic-trace uses that tool by default. It spawns perf record, which opens the right perf events, collects data, writes a perf-dot-data file. Then it spawns perf script, which reads the file back, decodes Intel-P-T packets, and prints human-readable events.

Magic-trace's direct backend calls perf-event-open itself, without going through any subprocess. It can do everything perf record does. The reason it's not the default is practical — perf has a mountain of accumulated special-case handling for things like virtual syscall pages and dynamic libraries that the direct backend doesn't replicate.

Up next: E-L-F files, the format of Linux binaries.

---

## 19. E-L-F files, the Linux binary format

**Overview.** Every executable on Linux, and every shared library, is in a format called E-L-F, which stands for Executable and Linkable Format. When magic-trace's decoder needs to figure out what instructions are at what addresses, it reads them out of E-L-F files. A tour of E-L-F is a tour of where the decoder gets its source of truth.

**Detailed.** An E-L-F file is structured into sections and segments. Sections are the compile-time view of the file — a section called dot-text holds executable instructions, a section called dot-rodata holds read-only data, a section called dot-bss holds uninitialized bytes that will become zero-initialized memory at load time. Segments are the load-time view — at runtime, the kernel loader reads the program's segment headers and maps each segment into memory at the right virtual address with the right permissions.

When you run a program, the kernel does roughly this. It opens the E-L-F file. It reads the header to find out where the segments are. For each load segment, it memory-maps the file bytes into the process's address space at the specified virtual address. It locates the entry point, jumps there, and off the program goes.

For an executable that uses shared libraries — which is almost every program on a modern Linux system — there's an extra step. The E-L-F file names an interpreter, typically slash-lib-slash-l-d-hyphen-linux-dot-so-dot-two. The kernel doesn't really run your program first; it runs the interpreter, handing it your program as an argument. The interpreter is what you know as the dynamic linker, or l-d dot s-o. It loads the required shared libraries, links everything together, and then transfers control to your program's entry point.

All of this — the sections, the segments, the symbols, the debug info — is stored in the E-L-F file. A magic-trace decoder reads all of it. It needs the instruction bytes to walk from branch to branch. It needs the symbol table to translate addresses into function names. It uses debug info, when available, to additionally label events with file names and line numbers.

If your E-L-F has no debug info, magic-trace still mostly works, but the output loses line numbers. If your E-L-F has no symbol table, you get raw addresses with no function names. So building your binary with reasonable debug settings matters for the quality of magic-trace's output.

Up next: the dot-text section specifically, where the actual code lives.

---

## 20. The dot-text section

**Overview.** Inside an E-L-F file, the dot-text section contains the actual machine instructions of your program. It's the bytes the C-P-U will execute. When the magic-trace decoder does its binary-walking algorithm, it's walking through dot-text.

**Detailed.** Here's a concrete picture. You compile a C file. The compiler emits an object file. Inside the object file there's a section called dot-text containing a flat sequence of bytes — the machine encoding of every function you wrote. Each function occupies some consecutive range of those bytes. The linker combines multiple object files, stitching their dot-text sections together into one bigger dot-text in the final executable.

When the program runs, the kernel loader maps that dot-text section into memory somewhere in the process's virtual address space, marked as readable and executable. The entry point is somewhere inside that region. The instruction pointer starts there, and as it moves, it's moving through dot-text.

For magic-trace, the important fact is that dot-text is a static, on-disk blob that represents exactly what the C-P-U will execute. If the decoder reads dot-text and disassembles at any address, it sees the same instruction the C-P-U saw. That's the invariant on which the whole decoding algorithm is built.

This is also where the term "static" versus "dynamic" analysis comes from in other contexts. Magic-trace's decoder does something in between. It uses the static contents of dot-text to disassemble, but it uses the dynamic packet stream from the hardware to decide which paths were actually taken. Static knowledge plus dynamic hints equals a full trace.

One note. On modern Linux systems with a feature called position-independent executables, the dot-text bytes are the same but they get loaded at a randomized virtual address at each run. We'll talk about that more in a couple of entries. For now, think of dot-text as the ground truth of your program's instructions.

Up next: the dynamic linker, and everything it does before your main function runs.

---

## 21. Dynamic linking and l-d dot s-o

**Overview.** Before your main function runs, a surprising amount of code executes. It's the dynamic linker, loading shared libraries your program depends on, resolving symbols, running initializers. When you first open a magic-trace of hello-world you'll see this phase dominate the timeline, and understanding why makes the trace navigable.

**Detailed.** Let me ask you: when you run an executable that uses libc — every normal C program — how does the instruction pointer get to your main function? The boring answer is that it doesn't start there. It starts at an entry point called underscore-start, compiled into every executable by a small startup object file. But underscore-start, in a dynamically-linked program, doesn't jump directly to your main either. It first hands control to the dynamic linker.

The dynamic linker is itself a shared library — typically slash-lib-slash-l-d-hyphen-linux-dot-so — that the kernel maps into your process alongside your binary. Its job is everything between "kernel loaded my binary" and "my main function is ready to run." That's a big list. It has to open every shared library your program directly and indirectly depends on. It has to map each one into your address space. It has to walk relocation tables and patch up every address in every loaded library so that function calls work. It has to run each library's initializer functions.

Only after all of that does the dynamic linker finally transfer control to the glibc startup code, which sets up argc and argv and envp, registers some cleanup handlers, and finally calls your main.

In the hello-world example trace, everything with names starting with underscore-d-l is the dynamic linker doing this work. Functions like d-l-underscore-start, d-l-underscore-sysdep-underscore-start, d-l-underscore-map-underscore-object-underscore-deps. These are internal functions of the dynamic linker. You're seeing it walk the dependency graph, load libc, relocate it, initialize it.

The whole dance typically takes two or three hundred microseconds on a fast machine for a simple program. That's tiny in absolute terms but enormous relative to the roughly five microseconds hello-world's main actually spends printing its string. If you've ever wondered why statically-linked binaries launch faster, this is a big part of the reason — they skip the dynamic linker entirely, because everything is pre-linked at build time.

Up next: position-independent code and address randomization.

---

## 22. P-I-E, A-S-L-R, and relocation

**Overview.** Modern Linux loads binaries and libraries at randomized addresses for security. The binary contains only relative offsets; the loader patches in the real addresses at load time. This matters to magic-trace because the decoder has to know the load addresses to correlate trace output with source code.

**Detailed.** Once upon a time, binaries had fixed load addresses. Your executable said "load me at zero-x-four-hundred-thousand," and every time you ran it, it landed there. Libraries likewise had fixed addresses. Simple, but a nightmare for security — attackers could rely on knowing exactly where anything interesting lived.

A-S-L-R, address space layout randomization, changed that. Every time you run a binary now, the kernel loads it at a different randomized virtual address. The same binary may live at zero-x-five-five-five-hundred-something on one run and somewhere completely different on the next. An attacker can't hard-code targets.

For this to work, the binary has to be loadable at any address. That's where position-independent executables, or P-I-E, come in. The compiler emits code that doesn't assume any particular load address; it uses relative offsets everywhere, and the loader patches in absolute addresses where necessary. Shared libraries have always been built this way. Modern executables are typically P-I-E now too.

For magic-trace, this creates a mapping problem. The instructions in the trace are at virtual addresses like zero-x-five-five-five-hundred-something. The instructions in the E-L-F file on disk are at file offsets. The decoder needs to know, for each address in the trace, which E-L-F file contains it and at what offset inside that file.

The answer comes from two sources. At recording time, perf records sideband events every time the kernel maps a binary or library — a record that says "the file at this path has been loaded at this virtual address." The decoder consumes these records and builds a map from virtual address ranges to file-plus-offset pairs. Then, for any address in the trace, it knows which file to read and where.

When you use magic-trace on a properly-loaded binary, you don't think about any of this. When it goes wrong — when a binary was loaded that perf didn't see, or when a library got unloaded and reloaded — you get unknown frames. That's usually the cause.

Up next: D-W-A-R-F debug info, which adds line numbers and source file names to the picture.

---

## 23. D-W-A-R-F debug info

**Overview.** D-W-A-R-F is a debug information format embedded in E-L-F files. It maps machine addresses back to source file names, line numbers, columns, variable names, types. Magic-trace uses it to annotate trace events with source locations, so when you click a function in the viewer you see where in the code it lives.

**Detailed.** Compilers have a dilemma. To produce fast code, they transform the source heavily — inline functions, reorder instructions, eliminate dead code, fuse operations. The resulting machine code bears little resemblance to the original source. But when you're debugging a program, you want to see the source, not the optimized assembly. The compiler has to remember the mapping between the two.

That mapping is stored in a format called D-W-A-R-F. The acronym officially doesn't stand for anything, though the joke at the time of its naming was that E-L-F was for elves and D-W-A-R-F was for dwarves. D-W-A-R-F lives in special debug sections of the E-L-F file, with names like dot-debug-underscore-info and dot-debug-underscore-line. It's large and complex — modern D-W-A-R-F can double or triple the on-disk size of a binary — and most tools strip it out before shipping.

For magic-trace, the relevant piece is the address-to-line table. Given an instruction pointer, D-W-A-R-F tells you the source file, the line number, and often the column. That's how magic-trace can label an event in the trace with, say, quote main dot c line forty-seven column twelve unquote.

The magic-trace decoder uses a library called owee to parse D-W-A-R-F lazily. When it writes a trace event out, it looks up the instruction pointer in the D-W-A-R-F tables and attaches file, line, column as metadata on the event. If the binary has no D-W-A-R-F, you still get symbol names from the regular E-L-F symbol table — just no line-level location.

This is the reason magic-trace's output quality depends on how your program was built. A stripped, release-build binary gives you function-level traces. A debug-build binary gives you line-level traces. A production deployment that was accidentally stripped gives you raw addresses. Build flags matter.

Up next: symbol mangling, and why function names sometimes look garbled.

---

## 24. Symbol mangling and why names look odd

**Overview.** Many programming languages encode type information into function symbol names. C++ does it. OCaml does it. The results are ugly but unambiguous. Magic-trace has a built-in demangler for OCaml, and can optionally run names through a demangler before showing them in the fuzzy picker.

**Detailed.** In C, a function called foo in your source becomes a symbol literally called foo in the object file. Nothing fancy. But in C-plus-plus and OCaml and most other modern languages, things are more complicated. Consider C-plus-plus: you can have two functions named foo that take different argument types, thanks to overloading. The linker needs to tell them apart. So the compiler encodes the argument types into the symbol name. A function called foo that takes an integer might become underscore-Z-three-foo-i. That's mangling.

OCaml mangling is a bit different — it encodes the module path in a specific way, with escape sequences for characters that aren't legal in linker symbols. A function called bar in module foo becomes something like c-a-m-l-underscore-underscore-foo-underscore-underscore-bar. If there's an asterisk or a greater-than sign in the name, they get replaced with dollar sign plus a two-digit hex code — dollar-two-a for asterisk, dollar-three-e for greater-than.

When the magic-trace decoder sees an OCaml symbol, it can recognize the c-a-m-l prefix and run a small parser over the rest to reverse the encoding, turning it back into something human-readable. That parser is a tiny piece of Angstrom, a parser-combinator library. It's only triggered when a specific flag is set, because demangling adds a small cost and the mangled names are the ones in the binary that perf will match on.

For the fuzzy-finder picker — the thing you get when you pass a question mark as the trigger — magic-trace does show both the mangled and the demangled forms, so you can search by either. The underlying stored symbol is always the mangled one, because that's what actually matches an address in the binary. The demangled version is a cosmetic alias.

Up next: the slash-proc file system entry that lets you see any process's memory map.

---

## 25. Slash-proc-slash-P-I-D-slash-maps

**Overview.** Linux exposes per-process runtime information as pseudo-files under slash-proc. One of them, called maps, lists every memory region currently mapped in the process — code, data, libraries, anonymous mappings. Magic-trace reads this for the direct backend to know what binaries are loaded.

**Detailed.** The kernel maintains, for each process, a table of virtual memory regions. Each region has a start address, an end address, permissions, and either a backing file or a note saying it's anonymous. When you read the file slash-proc-slash-some-P-I-D-slash-maps, the kernel generates a text listing on the fly showing you exactly that table.

A typical entry looks like this when read aloud: an address range, followed by r-w-x-p for the permissions, followed by a file offset, followed by the device and inode, followed by the path to the backing file. For executable code you'll see ranges mapped with r-x-p permissions pointing at paths like slash-lib-slash-x-eight-six-sixty-four-hyphen-linux-hyphen-g-n-u-slash-libc-dot-so-dot-six. For heap memory you'll see anonymous ranges. For the stack you'll see a specific entry labeled stack.

Why does this matter for magic-trace? The default backend doesn't need to read maps directly — perf does it internally via its sideband mechanism. But the direct backend, which skips perf, reads the maps file to bootstrap its model of what binary is loaded where. Specifically, when the direct backend attaches to a process, one of its first actions is to scan maps and build an initial list of every executable mapping.

Any mappings that happen after that initial scan — the target loads another library later, for example — need to be captured through other means, typically perf's sideband events. So maps gives you a snapshot of the present, and sideband events give you the deltas thereafter.

You can read any process's maps manually from the shell. If you're debugging a magic-trace issue where symbols aren't resolving, a quick look at the target's maps file often clarifies whether the binary you think is loaded actually is loaded where you think it is.

Up next: how just-in-time compilers advertise the addresses of code they generate at runtime.

---

## 26. J-I-T code and the perf map file

**Overview.** Not all executable code on a running system comes from a file on disk. Virtual machines like the J-V-M and V-eight generate native code at runtime into anonymous memory. To make that code findable by profilers, there's a convention: the runtime writes a special file called perf-dash-P-I-D-dot-map that lists the addresses and names of the J-I-T-generated functions. Magic-trace reads that file as one of its three fallback ways to resolve symbols.

**Detailed.** Dynamic runtimes have a problem when it comes to profiling. The V-eight J-I-T compiles JavaScript into x-eighty-six instructions at runtime and drops them into a chunk of memory it mmap'd. The Java H-o-t-Spot V-M does the same for bytecode. OCaml has a J-I-T option that does something similar. From the profiler's point of view, those instructions are in memory with no matching E-L-F file on disk — no symbol table, no D-W-A-R-F.

The fix is a lightweight convention. The runtime writes a plain text file named perf-dash-then-the-process-I-D-dot-map in slash-tmp. Each line in the file has three parts: a hexadecimal start address, a hexadecimal length in bytes, and a symbol name. Whenever the runtime generates a new J-I-T function, it appends a line to that file.

Profilers agree, by convention, to check for this file when resolving addresses. Perf does, magic-trace does. When the decoder sees an address that isn't in any loaded binary, it looks up the address in the perf map. If there's a matching range, it uses the symbol from that line. If not, the address is labeled unknown.

Magic-trace's symbol-resolution code tries three sources in order. First, it asks whether perf script already labeled the address in its text output. Second, if that failed, it checks the perf map file for J-I-T code. Third, if both fail, it labels the address with a generic unknown tag that includes the raw address and, if available, the D-S-O name.

For tracing a J-I-T-based workload, the practical advice is: make sure your runtime is writing a perf map file. Node has a flag to enable it. H-o-t-Spot has an agent. Without the map file, your J-I-T code shows up as unknown frames and you learn very little.

Up next: profiling in general, before we go any further into PT.

---

## 27. What profiling actually is

**Overview.** Before we go deeper into Intel Processor Trace, let's take a step back. Profiling is the practice of observing a running program to answer questions about its performance — where is it spending time, what is it doing when it stalls, why is some request slow. Magic-trace is a specific kind of profiler optimized for retrospective, high-resolution analysis.

**Detailed.** The first question a profiler answers is where time is going. You run your program, it takes too long, and you want to know which parts of the code are responsible. A classic statistical profiler interrupts the program periodically — say, a hundred times a second — and records the call stack. After a while you have a histogram of stack traces. Functions that appear often in the histogram were presumably running a lot.

The second question is what's happening at a specific moment. A crash happens. A request is mysteriously slow. A garbage-collection pause is surprisingly long. You'd like a trace of exactly what the program did leading up to that event. Statistical profilers are terrible at this — they see samples, not complete control flow. What you want is a full trace: every function call, every return, in order, with timestamps.

These two modes — histograms for overall shape, traces for specific episodes — sit at opposite ends of a design trade-off. Statistical profiling is cheap and can run all the time. Tracing is expensive and usually targeted. Tools sit somewhere along that trade-off.

Magic-trace leans heavily toward tracing. It captures every branch with near-cycle precision, which is effectively every function call. But it only does so for a small window of recent history — roughly the last ten milliseconds worth of branches that fit in the ring buffer — and only when triggered. So it's not "always-on, full program history." It's "ring-buffered, snapshot-on-demand, complete during the captured window."

This is a sweet spot for a specific class of problems. You know something weird happens occasionally. You can't capture a full trace of the whole run because that would be gigabytes. You just want a high-fidelity trace of the moment the weird thing happened. Magic-trace nails that.

Up next: sampling profilers in more detail.

---

## 28. Sampling profilers, cheap and blind

**Overview.** The dominant style of profiling is sampling — interrupting the program at a fixed rate and recording what it was doing. Sampling is cheap but blind between samples. Magic-trace's fallback mode is essentially a sampling profiler that uses the same pipeline.

**Detailed.** Picture a classical sampling profiler. It programs a timer to fire, say, one thousand times a second. Each time the timer fires, the profiler interrupts whatever the C-P-U is doing, captures the current instruction pointer and the call stack, and records it. When the program finishes, the profiler has a big pile of stacks, and it aggregates them to say: function f-o-o was on the stack in thirty percent of samples, so f-o-o is probably consuming thirty percent of time.

This approach has two wonderful properties. It's cheap, because you're only doing real work once per sample, and between samples the program runs at essentially full speed. And it's reasonably accurate in aggregate, because the law of large numbers makes the histogram reliable given enough samples.

It has two terrible properties. First, it's blind between samples. If a function runs for one hundred microseconds and your sample rate is one millisecond, the sampler has a ninety percent chance of missing it entirely. Functions shorter than the sample interval are effectively invisible. Second, it's statistical, not deterministic. If you want to understand what led up to a specific anomaly, sampling can't tell you — the odds of having a sample at the right moment are slim.

Linux's perf supports sampling extensively. You pick a hardware event — cycles, instructions, cache misses — and perf samples the stack whenever a counter overflows. That's why perf is usually described as a sampling profiler.

Magic-trace has a sampling mode that it falls back to when Intel Processor Trace isn't available — for instance, on virtual machines. In that mode, magic-trace essentially runs perf in sampling mode and feeds the samples through its normal decode and render pipeline. You lose the high-fidelity branch-by-branch timeline but you still get something useful.

Up next: tracing profilers, expensive but complete.

---

## 29. Tracing profilers, expensive and complete

**Overview.** Tracing profilers record every event of some kind — every function call, every cache miss, every system call — rather than sampling. They produce complete records but at much higher overhead than sampling. Intel Processor Trace is a tracing profiler done almost entirely in hardware, which is the trick that makes its overhead acceptable.

**Detailed.** A pure tracing profiler instruments every function. When the function is entered, it records a "call" event; when it returns, it records a "return" event. Run the program to completion and you have a complete record of every call, in order, with timestamps.

The cost is punishing. Every function call now has tracing overhead on top of its normal cost. Short functions — the ones you call a lot — suffer the most, because their tracing overhead is a significant fraction of their execution time. A program that was spending one percent in a function might, when instrumented, spend ten percent — and that's a fundamental change in the program's behavior, which undermines the premise of tracing in the first place. You're not studying the real program anymore; you're studying the instrumented program.

This is why software-based tracing profilers are typically targeted. You instrument some functions, not all of them. You use D-trace or e-B-P-F to attach probes only to the call sites you care about. You pay the tracing overhead only where it helps.

Intel Processor Trace breaks this trade-off by doing the tracing in hardware. The tracing unit is always running; it's built into the core. The overhead is not "instrument every function" overhead — it's the cost of the packet generator consuming a small fraction of the front-end bandwidth while the core executes. It turns out to be between two and ten percent in practice, which is low enough that you can afford to trace the real program rather than a modified one.

That's the central magic of P-T, and therefore of magic-trace. Tracing used to mean slow. Hardware-assisted tracing means full fidelity at sampling prices.

Up next: flame graphs and flame charts, which are the two main visualizations for profiling output.

---

## 30. Flame graphs versus flame charts

**Overview.** Flame graphs and flame charts look similar but answer different questions. A flame graph aggregates samples by stack, showing you which stacks were hot. A flame chart preserves time, showing you what happened when. Magic-trace produces a flame chart, which is why you see a time axis in the viewer.

**Detailed.** A flame graph is a visualization invented by Brendan Gregg to make sampling profiler output easy to read. You take all your samples, group identical call stacks together, and draw a horizontal bar for each unique stack. The width of the bar is the number of samples with that stack. The bars are stacked vertically by call depth — root at the bottom, deepest call at the top. You scan the image: the widest bars near the top are the hottest leaf functions.

A flame graph has no time axis. The order of samples has been aggregated away. You can't tell from it whether a hot function was hot constantly or hot in a burst.

A flame chart is superficially similar but carries an entirely different meaning. The horizontal axis is time, not aggregation count. Each bar represents a single call — you called foo at this time, it lasted this long — and the vertical stacking represents the call stack at that moment. Reading left to right is reading forward in time. Reading top to bottom at a single moment is reading the stack that was live at that moment.

Magic-trace produces a flame chart. When you open a trace in the viewer, you're looking at a timeline. A given function call appears as one rectangle somewhere on the chart, not as an aggregated bar. If that function was called a hundred times, there are a hundred rectangles scattered along the time axis.

This is a much more powerful view for answering "what happened when" questions. You can see a slow request as a long bar. You can see a garbage collector pause as a block of work that interrupted the main thread. You can measure the duration of a specific call by clicking on it, which a flame graph cannot do.

The cost is that a flame chart is much larger than a flame graph for the same data. One call site becomes many rectangles, not one. That's fine for magic-trace, which ring-buffers to a bounded window and therefore has bounded data.

Up next: the last branch record, a lightweight alternative to P-T.

---

## 31. The last branch record

**Overview.** L-B-R, the last branch record, is a small hardware ring that stores the most recent branches the C-P-U has taken. It's simpler than P-T, AMD and Intel both have it, and it's used by sampling profilers to reconstruct short call stacks at each sample. It shows up in magic-trace as one of the options for the sampling fallback mode.

**Detailed.** Every modern Intel and AMD core has a small set of registers — typically sixteen or thirty-two pairs — that together form a ring of the most recent branches. Each entry records the from-address and the to-address of one branch. As the C-P-U takes new branches, old entries drop out of the ring.

The L-B-R is not, by itself, a streaming trace. It's a snapshot you can read at any moment — the hardware updates it continuously in the background, but nothing in memory gets written until you explicitly sample it.

Sampling profilers use L-B-R to get a mini-trace at each sample point. When the sampling timer fires, the profiler reads the L-B-R along with the current instruction pointer, and the thirty-two most recent branches give it a short history of what led to this moment. You can use that history to reconstruct a call stack: each call instruction in the L-B-R is a frame, each return pops one.

The advantage over D-W-A-R-F-based unwinding, which we'll describe shortly, is that L-B-R needs no debug info. It's pure hardware. Your binary can be completely stripped and L-B-R still works. The disadvantage is that the ring is small, so for deep stacks you might not see the full history.

Magic-trace's sampling mode can be configured to use L-B-R, or frame pointers, or D-W-A-R-F. L-B-R is usually the default when available because it strikes a good balance. There's a feature called L-B-R stitching, where the profiler tries to combine multiple adjacent L-B-R snapshots into a single longer history; magic-trace supports this and has a flag to disable it if it misbehaves.

L-B-R is not a substitute for Intel Processor Trace. It gives you the last few branches at each sample, not every branch over time. But it's cheap, ubiquitous, and good enough for many performance questions. When P-T isn't available — typically in VMs — magic-trace defaults to L-B-R-based sampling.

Up next: the two major ways of reconstructing call stacks when you don't have hardware help.

---

## 32. D-W-A-R-F versus frame pointer unwinding

**Overview.** When a sampling profiler captures a stack trace, it has two main ways to walk up the call chain. One is to follow frame pointers, which is fast but requires a compiler flag. The other is to interpret D-W-A-R-F unwind information, which is slow but works on any binary. Magic-trace's sampling mode exposes both options.

**Detailed.** At any moment, the stack of the running thread holds a chain of stack frames — one per live function call. A stack trace is the sequence of return addresses walking up that chain. How do you walk it?

The simple way: frame pointers. Each function, on entry, saves the previous frame pointer into its own stack frame and then sets the frame pointer to point at its own frame. This creates a linked list up the stack, where each frame contains a pointer to the previous one. To unwind, you follow that list: read the current frame pointer, follow it to the parent frame, read its frame pointer, and so on. Fast, simple, robust.

The catch: frame pointers cost a register and some instructions per function. Compilers by default omit frame pointers for optimization. If you compile a program with dash-f-no-omit-frame-pointer, you opt in to the overhead in exchange for easy stack unwinding.

The complicated way: D-W-A-R-F unwinding. The compiler embeds tables in the binary — as part of D-W-A-R-F debug info — that describe, for every instruction, how the stack is laid out. To unwind, you look up the current instruction pointer in those tables, find out where the return address was saved, read it, then look up the new instruction pointer in the tables, and continue. It's slower because every frame requires a table lookup, and the tables are compressed, so the lookup isn't a simple array index.

The advantage of D-W-A-R-F unwinding is that it works without any cost at runtime. You keep your tight code, and the unwinding is done only when a profiler samples. The disadvantage is that it requires D-W-A-R-F info in the binary, which means not stripping.

Magic-trace exposes both under its callgraph-mode flag. You pick based on what your binary supports. If you can afford frame pointers, use them. If not, and you have D-W-A-R-F, use that. This choice only applies to the sampling fallback mode — Intel Processor Trace produces its own call graph for free and doesn't need either technique.

Up next: the big insight behind why Intel Processor Trace works at all.

---

## 33. The big insight of Intel Processor Trace

**Overview.** Intel Processor Trace is built on one clever observation. Given the binary, a decoder already knows what most instructions would do. Branches are the only instructions whose outcome is uncertain, and even among branches, only some outcomes are truly uncertain. By emitting just that uncertainty, the C-P-U produces a trace at a tiny fraction of the cost of emitting everything.

**Detailed.** Let me frame it as a question. Suppose you want to know what a program did. You have two resources: the binary, which you have a copy of, and the execution history, which you must somehow capture. What's the minimum information the C-P-U needs to tell you?

Here's what you already know from the binary. You know every instruction at every address. You know which instructions are branches and which aren't. For every direct branch, you know where it goes; that's encoded in the instruction itself. For every conditional branch, you know the two possible destinations — taken or fall-through — but not which will be chosen at runtime. For every indirect branch, you know neither destination.

So from the binary alone, you can trace a program up to the first conditional branch, at which point you need one bit to tell you which way it went. After that, you can keep going until the next branch that produces ambiguity.

Intel Processor Trace emits exactly this minimum. For conditional branches, it emits one bit each — a one if taken, a zero if not. Pack six of these bits into a byte and you've got six branches in a single byte. For indirect branches, it emits the destination address. For interrupts and exceptions, it emits where they happened. For everything else — all the arithmetic, all the memory operations, all the direct branches — it emits nothing.

The result is a packet stream where typical code produces maybe one byte for every five to ten retired instructions. That's sparse enough that the C-P-U can emit it as a background activity, dumping into memory without materially slowing the core.

This is the central trick. There's nothing fundamentally special about the tracing hardware; it's a small state machine that watches the retirement stream and outputs packets when necessary. What's special is the insight — the decoder already knows the binary, so don't waste bytes telling it what it already knows. Once you see it, you can't unsee it. It applies to many kinds of information compression, and you'll notice it in other places now that you know to look.

Up next: how much overhead magic-trace actually imposes.

---

## 34. Why magic-trace's overhead is so low

**Overview.** Tracing every function call in a program sounds like it should be impossibly expensive. In practice, magic-trace costs between two and ten percent. That's because almost all of the work happens in hardware that was going to run anyway, and the rest happens after the fact.

**Detailed.** Let's build an intuition for where the overhead comes from. The C-P-U's tracing unit is part of the core itself. It watches the retirement stream, emits packets into a buffer. That work happens at core frequency, in parallel with everything else, and from the point of view of the instruction stream it's pure background noise. It doesn't add instructions. It doesn't add latency to anything except maybe a tiny fraction of the front-end bandwidth.

There's a memory-bandwidth cost because the packets have to go somewhere. The tracing unit streams to D-R-A-M, and that's bytes that wouldn't otherwise be flowing. For very branch-heavy code, that can become significant. That's where the upper end of the two-to-ten range comes from.

There's a cache cost, too. The tracing buffer displaces other things from last-level cache. In the worst case, that shows up as slightly slower code.

But there is zero syscall overhead during tracing. Zero interrupts per branch. Zero software polling. The C-P-U fills the buffer; magic-trace reads it after the fact. That's what makes the numbers so small.

Then there's the decoder, which runs offline. It's the heavy part. Walking through tens of thousands of packets and reconstructing call stacks is computationally non-trivial. For a snapshot's worth of data — the last ten milliseconds or so — the decoder typically runs for under a second. You pay this cost once, after the snapshot, on a different C-P-U from the one being traced, on cached data. It doesn't affect the running program.

Put it all together. The live cost is small because the hardware is efficient. The offline cost is moderate but doesn't interfere with anything. The user-visible cost is a brief "decoding, this takes a while" message and then you have your trace. For a tool that gives you every branch with forty-nanosecond precision, that's an astounding cost profile.

Up next: the physical structure of a tracing packet, in more concrete terms than we've used so far.

---

## 35. What a packet is, physically

**Overview.** A packet is a short run of bytes in memory. It has a header byte that identifies its type and tells the decoder how many payload bytes follow. Packets sit one after another in the tracing buffer. The decoder reads them by walking the byte stream and interpreting each header.

**Detailed.** It's easy to imagine "packets" as something abstract, like network packets or protocol messages. For Intel Processor Trace, they're more like entries in a binary log file. The tracing unit is just appending bytes into a ring buffer in D-R-A-M. A packet is a contiguous, variable-length run of those bytes.

Every packet starts with a header byte. The bits of that byte encode which kind of packet it is. Some packet types have no payload at all — the header is the whole packet. Others have one, two, four, eight, or even sixteen bytes of payload, depending on what they need to say.

To make the encoding efficient, the header also carries a little bit of data payload when it can. For example, a short tracing packet that holds up to six conditional-branch bits packs those bits into spare bits of the header. No separate payload bytes needed.

The decoder reads this stream linearly. It looks at the first byte, identifies the packet type by the bit pattern, reads any payload bytes that follow, and moves on to the next header. It knows how many bytes to consume because the header says so. This is what allows the format to be variable-length — self-describing in the same way U-T-F-eight is.

Because it's a byte stream rather than a word stream, the tracing buffer can be read from anywhere in principle. But finding a safe starting point is not trivial; if you start mid-packet, you'll misinterpret a random byte as a header and get garbage. That's why the packet stream has periodic synchronization markers — a specific fixed pattern that can only be the beginning of a sync packet — so a decoder joining mid-stream can scan forward to the next sync and start fresh.

For magic-trace users, you never interact with packets directly. Perf and libipt handle them. But knowing what a packet is makes later discussions much clearer — when we talk about why some operations are expensive in bytes and others aren't, we're talking about this packet economy.

Up next: the many-to-many relationship between packets and instructions.

---

## 36. Packets versus instructions — many to many

**Overview.** The relationship between packets and instructions is not one-to-one. Most instructions produce zero packets. Some produce fractions of a packet. A few produce multiple packets. One packet can represent many instructions worth of execution. Understanding this accounting is the key to understanding why P-T is cheap.

**Detailed.** Let's walk through the cases carefully. First, the most common case: a plain non-branch instruction like an add or a move or a load. The tracing unit emits zero packets for it. Millions of these can retire per millisecond with nothing in the trace.

Second, a direct branch. A direct jump, a direct call. The destination is encoded in the instruction bytes. Zero packets emitted. The decoder, later, will read the instruction from the binary and follow it without any runtime hint.

Third, a conditional branch. These emit one bit — one taken-not-taken bit — packed into a larger packet along with other recent bits. Six of them fit in one byte. So the "cost" of a conditional branch is roughly one-sixth of a byte, amortized. For a loop that iterates ten times, you pay about ten bits, under two bytes total. Compared to the dozens of bytes of instructions that ran in those ten iterations, the cost is negligible.

Fourth, an indirect branch. An indirect call through a function pointer, a return, an indirect jump through a jump table. These emit a target-address packet. The exact size depends on how much of the new address differs from the previous one, usually between two and five bytes.

Fifth, interrupts and exceptions. Each of these emits an anchor packet identifying where in the instruction stream it happened, plus mode-change information. A handful of bytes.

Now for cases where one instruction emits multiple packets. If an indirect branch happens to coincide with a time-stamp deadline, you get a target packet plus a timing packet plus possibly a wall-clock packet. Three packets on one instruction. This is not common but it happens regularly on modern settings.

And the inverse: a single taken-not-taken packet can describe six conditional branches worth of behavior. One packet, multiple instructions.

The aggregate, on typical code with normal timing settings, comes out to roughly one packet byte per five to ten retired instructions. That's the ratio you should keep in your head. It's why the buffer can hold milliseconds of history in a few megabytes. It's why the overhead is tolerable. It's why this works at all.

Up next: self-describing encoding, via a familiar analogy.

---

## 37. Self-describing encoding, the U-T-F-eight analogy

**Overview.** Intel Processor Trace packets are self-describing in the same way U-T-F-eight-encoded text is. Each starting byte tells the decoder how many bytes of payload to consume. You walk the stream forward without needing any out-of-band length information. This is why the stream can be variable-length yet unambiguous.

**Detailed.** You probably know U-T-F-eight as the character encoding that dominates the web. Let me remind you how it works. A text string is a sequence of bytes. Some bytes — specifically, the ones with the high bit clear — represent one-byte characters. Other bytes, the ones starting with a one-zero pattern, are continuation bytes that belong to a multi-byte character. The first byte of a multi-byte character has a specific pattern that tells you how many bytes total: one-ten for two bytes, one-ten-zero for three bytes, one-zero-one-zero for four.

The upshot is that given a U-T-F-eight byte stream, you can decode it one byte at a time, and each byte either is a complete character or tells you how many more bytes to expect. You never need a length prefix because the bytes are self-synchronizing.

P-T packets work the same way. The first byte of every packet — its header — has a specific bit pattern that identifies both the packet type and, implicitly, the total length. Some headers say "I'm a short T-N-T packet, no payload, move on after me." Others say "I'm a T-I-P packet with compression mode two, three payload bytes follow."

The decoder marches through the buffer, byte by byte. Each header tells it what it's looking at and how to advance. This pattern makes the stream robust: if you're handed a buffer and told to decode it, you can start from the beginning and go. There's no parsing tree to build, no length table to load.

The one wrinkle is that if your starting point is wrong — mid-packet rather than at a header — you'll interpret a random byte as a header and emit garbage. That's what synchronization markers are for, which we'll cover a bit later. If you see garbage decoded output, one likely cause is that the decoder started at the wrong byte offset, typically because a ring buffer wrapped weirdly or the snapshot boundary wasn't aligned with a sync marker.

Up next: the first of the packet types in detail — taken-not-taken.

---

## 38. T-N-T packets, one bit per branch

**Overview.** The most common packet type is T-N-T, which stands for taken-not-taken. It carries up to six bits, each representing the outcome of a conditional branch. Conditional branches are the most common branches in code, so T-N-T is where most of the stream's bytes go.

**Detailed.** Consider your program's conditional branches — the jumps that are taken sometimes and not taken other times, depending on runtime data. Every if statement compiles to one. Every loop condition compiles to one. These are dense in typical code.

Each time a conditional branch retires, the tracing unit records a single bit: one if it was taken, zero if it fell through. It doesn't emit a packet right away. Instead, it buffers the bits and packs them together. When it has up to six bits, it emits a T-N-T packet containing all of them.

The packet is one byte. The first bit is a leading marker that says "this is a short T-N-T." The remaining bits carry the branch outcomes, padded with a stop bit so the decoder knows how many real bits are in the packet. That means up to six conditional branches represented in a single byte.

Let me ask you: how would the decoder use this? Starting from a known instruction pointer, the decoder disassembles forward through the binary. When it hits a conditional branch, it consumes the next taken-not-taken bit. If the bit is one, it jumps to the branch target. If zero, it falls through to the next instruction. Then it continues disassembling, consuming another bit at the next conditional branch, and so on. Six bits in a byte, six branches' worth of control flow reconstructed.

There's also a long-form T-N-T packet for cases where more than six bits need to come out at once, typically after a burst of conditional branches. It's rare but it exists, and the decoder handles both forms transparently.

From a cost standpoint, T-N-T is astonishingly efficient. If a for-loop iterates ten thousand times, its ten thousand "should I continue?" decisions compress to about sixteen hundred bytes. That's how P-T manages to trace tight loops without exploding the buffer.

Up next: the packet type that carries the addresses of indirect branches.

---

## 39. T-I-P packets and indirect control flow

**Overview.** When the C-P-U takes an indirect branch — a jump through a register, a return, an indirect call — the decoder can't know the destination from the binary alone. The tracing unit emits a target instruction pointer packet, or T-I-P, to tell the decoder where control landed. T-I-P packets are variable-length thanks to a compression scheme based on reusing the upper bytes of the previous target.

**Detailed.** Every indirect branch retires, the tracing unit emits a T-I-P. The payload is the target instruction pointer — the address where control went. On a sixty-four-bit machine, that could be up to eight bytes. Emitting eight bytes per indirect branch would blow the byte budget for branchy code, so Intel applies compression.

The trick is this. Instruction pointers tend to cluster. A function's code is contiguous; a call into a library stays within that library for a while. So the upper bytes of the new target are often the same as the upper bytes of the previous target. The T-I-P header tells the decoder how many of the low bytes follow, and the decoder reuses the upper bytes of whatever target it saw last. A typical T-I-P in a tight loop might be three or four bytes long rather than eight.

There are actually several variants of T-I-P that use different compression strategies. One uses reserved bits in the previous target; one sign-extends; one re-emits the full address as a resync. The decoder handles all of them, and magic-trace users don't have to care about the details.

T-I-P is emitted for a few specific kinds of control flow. An indirect jump through a register. An indirect call through a register or memory. A return instruction, which pops its target off the stack and therefore is always indirect. Also, certain trace-state-change events that we'll discuss later each come with an associated T-I-P-like packet that anchors the instruction pointer at the moment of change.

Where you see T-I-P in perf's text output is implicit. Each "return" or "call" where the destination wasn't predictable gets its destination from a T-I-P the decoder consumed. In the trace, you see the human-readable effect — a function call with a real target — but underneath, the hardware emitted T-I-P bytes to make that reconstruction possible.

Up next: flow update packets, which handle asynchronous events.

---

## 40. F-U-P packets and asynchronous events

**Overview.** When something happens that's not in the normal instruction stream — an interrupt, an exception, a page fault — the C-P-U needs to tell the decoder where the instruction pointer was at that moment. The flow update packet, or F-U-P, carries that anchor address. Without F-U-Ps, the decoder would have no idea where control was when an interrupt preempted.

**Detailed.** Instructions are deterministic. The C-P-U knows which one is next. Asynchronous events are not — an interrupt or a page fault can arrive at almost any retirement boundary. From the decoder's perspective, an async event is a sudden discontinuity in the instruction stream.

F-U-P packets handle this. Whenever an asynchronous event happens, the tracing unit emits an F-U-P whose payload is the instruction pointer at the moment the event fired. Then it emits additional packets describing the event — a mode change if the C-P-U is entering kernel space, a T-I-P if control is transferring to an interrupt handler, and so on.

The sequence "F-U-P plus event descriptor" is the canonical way asynchronous events land in the trace. The decoder sees the F-U-P, knows control was at that address when interrupted, and uses the subsequent packets to figure out where control went next.

In magic-trace's output, you'll see F-U-Ps manifest as events named hardware interrupt, interrupt-return, transaction abort, and so on. Each of these came from an F-U-P combined with a mode packet.

One subtlety worth knowing: F-U-Ps are also used in "trace disable due to filter mismatch" scenarios. If the C-P-U is filtering by C-R-three and C-R-three changes due to a context switch, an F-U-P is emitted to anchor where the traced process was at the moment the filter stopped firing. When tracing comes back, another F-U-P anchors the resume point. This is how the decoder handles the gaps created by filtering without getting lost.

Up next: the packet types that mark when tracing itself turns on and off.

---

## 41. P-G-E and P-G-D — tracing on and off

**Overview.** The tracing unit can be instantaneously enabled or disabled. P-G-E, packet generation enable, is emitted when tracing becomes active. P-G-D, packet generation disable, is emitted when it becomes inactive. These are what produce the tr strt and tr end lines in perf's output, which in magic-trace's viewer become the pink untraced bands.

**Detailed.** P-G-E stands for packet generation enable. P-G-D for packet generation disable. They're the tracing unit's way of marking transitions between "I'm emitting packets" and "I'm not."

Why would tracing turn on and off mid-execution? Several reasons. If your filter says "only trace when C-R-three matches a specific value," then every context switch to another process turns tracing off and every context switch back turns it on. If your filter says "only trace user-space code," then every system call or interrupt turns tracing off for the duration of kernel execution. If you asked for a specific instruction-pointer range only, then control flowing out of that range turns tracing off.

Each transition produces a packet. P-G-E when tracing starts, P-G-D when it stops. The packet carries the instruction pointer at the moment of transition, so the decoder knows where control was as tracing resumed or ended.

In perf's text output, P-G-E becomes a line labeled tr strt — trace start. P-G-D becomes tr end — trace end. Magic-trace's decoder sees these and interprets them as state-change events. When tr end is seen, magic-trace pushes a synthetic untraced frame onto the call stack. When tr strt is seen, it pops the untraced frame and continues normally.

That's why you see pink untraced bands in the viewer. They mark periods when the target process was doing something but tracing wasn't capturing it. Typical causes: the thread ran a system call into the kernel, the thread was descheduled, the thread took a page fault. Each of these turns tracing off for its duration.

If you're wondering "why did my function take so long" and you see a big untraced band in the middle, the answer is probably that the kernel was doing something there. Enabling kernel tracing with the corresponding magic-trace flag — which requires being root — fills in those bands with kernel-side detail.

Up next: the synchronization packets that let decoders join a stream in progress.

---

## 42. P-S-B packets and resynchronization

**Overview.** The tracing unit periodically emits a special fixed-byte packet called P-S-B, for packet stream boundary. It's the sync marker the decoder looks for when starting mid-stream or recovering from an overflow. Without it, snapshot-mode tracing — where you might start decoding from any point in a ring buffer — would be impossible.

**Detailed.** Here's the problem. In snapshot mode, the tracing buffer is a ring. When you take a snapshot, you get whatever bytes happened to be in the ring at that moment. The oldest bytes get overwritten by newer ones. When the decoder starts reading, it's starting at some arbitrary byte offset — whatever the ring pointer was at the moment of the snapshot, minus the ring size.

If the decoder begins at a random byte in the middle of a packet, everything it decodes will be garbage. It needs a landmark — a byte sequence that can only mean "start fresh here." That landmark is the P-S-B packet.

P-S-B is sixteen bytes of a specific fixed pattern, chosen so it can't occur accidentally as part of any other packet. The decoder scans forward through the buffer until it finds the pattern, positions itself just past it, and starts decoding. Right after a P-S-B, the tracing unit also emits a group of synchronizing packets — the current instruction pointer, current mode, current timestamp — so the decoder has a complete starting state.

P-S-Bs are emitted on a periodic basis, roughly every so-many bytes of trace output. The period is configurable on newer C-P-Us, through an M-S-R bit and a corresponding perf option called psb-period. Shorter period means you can resync more frequently, which means less of the buffer is lost after an overflow or at a snapshot boundary, but it also means more P-S-B packets in the stream, consuming bytes.

In magic-trace's timer resolution settings, you can control the P-S-B period through the custom setting. The default works fine for most workloads. If you regularly lose long stretches of trace to overflow, tightening P-S-B period helps you salvage more after each overflow.

Up next: mode packets, which describe C-P-U state changes.

---

## 43. Mode packets — the C-P-U changed state

**Overview.** When the C-P-U transitions between operating modes — user to kernel, sixty-four bit to thirty-two bit, in or out of a transactional region — it emits a mode packet to tell the decoder. Without these, the decoder wouldn't know how to disassemble subsequent instructions, since the same bytes can mean different things in different modes.

**Detailed.** Not all x-eighty-six code is the same. A chip can run in sixty-four-bit mode or in legacy thirty-two-bit mode. Certain Intel extensions put the C-P-U into special states for transactional memory. And of course there's the user-space versus kernel-space distinction, which doesn't change disassembly but does change what's being traced.

When any of these state bits change, the tracing unit emits a mode packet. The payload encodes which state changed and what the new value is. The decoder keeps its own shadow copy of the C-P-U mode and consults it when disassembling instructions.

For magic-trace users, you'll rarely think about mode directly. The one place it surfaces visibly is transaction aborts — when the C-P-U is inside a hardware memory transaction and something triggers a rollback, you get a mode change packet and a tx-abrt event in the text output. That event propagates into magic-trace's event stream and shows up as a distinct kind in the trace.

The vast majority of the mode changes are silent plumbing. The C-P-U flips from user to kernel during a syscall, back to user when the syscall returns, occasionally in and out of thirty-two-bit compatibility mode if the process does anything esoteric. None of this requires user action.

Mode packets also play a role with F-U-P packets, which we discussed earlier. When an interrupt takes the C-P-U into kernel space, you'll see an F-U-P marking the anchor address, followed by a mode packet saying "we are now in ring zero." Decoders use the pair together to describe the transition cleanly.

If you trace with only user-space enabled and the target does a lot of system calls, you'll see short tr-end blocks at each syscall and tr-strt blocks when it returns. That's the P-G-D and P-G-E packets doing the on-off, not mode packets. Mode packets and filter-gating packets are related but distinct.

Up next: the packet that tells you the C-P-U gave up and lost data.

---

## 44. Overflow packets and hardware backpressure

**Overview.** The tracing unit has a tiny internal buffer before data reaches D-R-A-M. If D-R-A-M bandwidth falls behind, the internal buffer fills, and the tracing unit has no choice but to drop data. When this happens, it emits an overflow packet to tell the decoder that a gap occurred. Overflow is the most common way traces get corrupted in practice.

**Detailed.** Imagine the packet stream as a pipe. The tracing unit is producing bytes at one end; they flow through a short on-chip F-I-F-O; they get written out to memory. If D-R-A-M can keep up, the pipe stays flowing. If it can't — because the memory subsystem is contested, or the ring buffer is small and wrapping frequently — the F-I-F-O fills up. When it's full, the tracing unit has nowhere to put new packets.

At that moment, the hardware makes an unfortunate choice. It stops emitting packets until the F-I-F-O drains. Whatever branches happen in the meantime are simply lost — unrecoverable, no state kept. When draining completes, the tracing unit emits an overflow packet to let the decoder know.

In magic-trace, overflow shows up as an event labeled "decode error, Overflow packet." The decoder can't recover the lost branches; it can only acknowledge the gap. When the decoder sees one, it resets its per-thread call stack — because it no longer knows what frames are live — and starts fresh from the next synchronization point.

What causes overflow? Usually one of three things. Tight branchy code with very high instruction-per-cycle counts produces packets faster than D-R-A-M can absorb. A small ring buffer, set with a low dash-m value, makes overflow more likely because frequent wrapping increases contention. Aggressive timing settings with cycle-accurate packets on roughly double the byte rate.

Mitigations are practical. Increase the buffer size with a larger dash-m. Drop the timer resolution to the lowest setting, which disables cycle packets and dramatically reduces the byte rate. Consider sampling mode if you don't truly need per-branch fidelity.

Seeing overflow in a trace doesn't invalidate everything else — it just marks a specific gap. The rest of the trace remains valid; the decoder stitches across the gap using the next synchronization packet.

Up next: a compression trick for returns, and why sometimes you disable it.

---

## 45. Return compression and noretcomp

**Overview.** Returns are indirect branches, which normally require a T-I-P each. Intel added a feature where, if the C-P-U can match a return against a prior call, it omits the T-I-P entirely. This typically halves the byte rate. Magic-trace's high timer-resolution setting disables it for extra robustness.

**Detailed.** Consider the normal flow. A call instruction pushes the return address onto the stack. The called function runs. The return instruction pops the saved address and jumps there. Because the return is indirect — its target came off the stack, which the decoder can't see — the tracing unit normally emits a T-I-P for every return.

That's a lot of bytes. Typical code is call-heavy — thousands of calls per millisecond — so thousands of T-I-Ps per millisecond is the baseline. Intel noticed that most returns are "well-behaved": the return address on the stack is the one pushed by the matching call. If the tracing unit and the decoder both maintain a shadow call stack, the decoder can predict the return target without needing to be told.

That's return compression. With it enabled, the tracing unit elides the T-I-P for most returns. Only unusual returns — ones where the address doesn't match the shadow stack, perhaps because of set-jump-long-jump or exception unwinding — emit a T-I-P. The byte rate drops significantly.

The decoder has to maintain its own shadow stack in lockstep with the tracing hardware. If they get out of sync for any reason, decoding goes wrong. This is normally fine but can cause issues with code that manipulates stacks in unusual ways, like some garbage collectors or coroutine implementations.

Magic-trace exposes a knob called noretcomp. When set, return compression is turned off in the hardware. Every return emits a T-I-P. You get more robust traces — the decoder doesn't depend on an elaborate shadow-stack protocol — at the cost of roughly doubling the byte rate.

This is what magic-trace's High timer resolution setting includes. It turns noretcomp on as part of its "maximum fidelity" configuration. Normal mode leaves return compression on, which is fine for most code. If you're tracing something with exotic stack manipulation and seeing weirdness, noretcomp might help.

Up next: the clock that grounds everything — the time-stamp counter packet.

---

## 46. Timestamp counter packets

**Overview.** The timestamp counter packet, T-S-C, carries a wall-clock anchor in hardware cycle units. It's how the decoder assigns real nanoseconds to trace events. Emitted periodically and at certain boundaries, T-S-C is the ground truth for time in the stream.

**Detailed.** Recall that the C-P-U has an invariant timestamp counter — a register ticking at a fixed rate, unaffected by frequency scaling. When the tracing unit emits a T-S-C packet, it's saying "at this point in the stream, the invariant T-S-C read this value."

The decoder uses T-S-C as an anchor. Between T-S-C packets, it can estimate time using finer-grained timing packets. At each T-S-C, it gets a ground truth that rebaselines those estimates. If its estimates drift slightly between anchors — and they do, because cycle durations vary with frequency — the next T-S-C corrects them.

T-S-C packets aren't emitted on every event. They're emitted at each synchronization point — right after a P-S-B — and on certain async events like interrupts. Between T-S-Cs, the tracing unit relies on smaller timing packets to track elapsed time.

Converting a T-S-C value to nanoseconds requires three numbers: a multiplier, a shift, and a zero offset. The kernel measures these at boot and exposes them in a page of memory it shares with perf. The decoder reads them from that page. The formula is "multiply T-S-C by multiplier, shift right by shift, add the zero offset." The result is nanoseconds since some epoch that the kernel chose.

For magic-trace, the upshot is that every event in the trace has a real wall-clock nanosecond timestamp. When you hover over a duration in the viewer, the microseconds you see came from this chain: T-S-C packet in the hardware stream, shift-multiply conversion in the decoder, display in Perfetto.

Up next: a medium-resolution timing packet called M-T-C.

---

## 47. M-T-C, the mini timing counter

**Overview.** Between T-S-C anchors, the C-P-U emits a smaller timing packet called M-T-C, the mini timing counter. Each M-T-C is a short counter tick that gives the decoder a finer-grained estimate of elapsed time than T-S-C alone could provide.

**Detailed.** T-S-C packets are relatively rare. Typical intervals between T-S-Cs can be microseconds long. That's too coarse if you want to stamp branches with sub-microsecond precision. Enter M-T-C.

The C-P-U derives M-T-C ticks from a fast internal clock, one that runs at a fixed submultiple of the base frequency. It emits an M-T-C packet every time a specific number of these ticks pass. The payload is tiny — essentially a counter update — and the decoder uses it to estimate elapsed time between T-S-C anchors.

The period is configurable through an M-S-R called mtc-period. Lower period values produce M-T-C packets more frequently, giving finer resolution at the cost of more bytes. Magic-trace's Normal timer resolution sets mtc-period to zero, which means "emit M-T-C as often as the hardware can," producing the tightest resolution this packet can offer.

M-T-C by itself is a counter without a clear mapping to wall-clock time. It runs at a fixed ratio to T-S-C — but that ratio is only communicated to the decoder through yet another timing packet called T-M-A. T-M-A shows up near T-S-C and says "the T-S-C value I just emitted corresponds to this M-T-C value." That three-way linkage — T-S-C, M-T-C, T-M-A — is what lets the decoder maintain accurate wall-clock time even between T-S-C anchors.

The resolution M-T-C gives you, in practice, is roughly ten nanoseconds on modern chips. That's good enough for most performance work. If you want even tighter resolution, you use the packet type we'll cover next.

Up next: cycle-accurate packets, the finest-grained timing P-T offers.

---

## 48. C-Y-C packets, cycle-accurate timing

**Overview.** C-Y-C packets — the cycle-accurate timing packets — are how magic-trace achieves its famous forty-nanosecond resolution claim. They're emitted when enough cycles have elapsed since the previous packet, with a configurable threshold. Turning C-Y-C on roughly doubles the byte rate.

**Detailed.** For most performance work, M-T-C's ten-nanosecond resolution is fine. For really tight performance work — characterizing functions that take under a microsecond — it's too coarse. C-Y-C packets close the gap.

A C-Y-C packet carries a cycle count delta since the last packet. The payload is small — an exponential encoding where common small deltas fit in one byte and rare large ones can extend to several — and the decoder uses it to track time at cycle granularity.

The tracing unit doesn't emit a C-Y-C on every cycle, which would be absurd. It emits one whenever a threshold number of cycles has elapsed since the previous packet, and only when some other packet is being emitted anyway. So C-Y-C rides along with T-N-Ts and T-I-Ps, stamping them with cycle-accurate time.

There are two knobs. C-Y-C is the on-off bit: is cycle packet emission enabled at all. C-Y-C-thresh is the threshold: how many cycles must elapse before the tracing unit is obligated to emit a C-Y-C. Magic-trace's Normal timer resolution sets both to one, meaning "on, threshold one cycle." This gives the maximum C-Y-C density the hardware supports.

When you zoom into a trace and see branches a few hundred nanoseconds apart, you're looking at the result of C-Y-C packets. A branch at cycle ten thousand followed by another at cycle ten thousand two hundred gets a two-hundred-cycle delta, which the decoder converts to nanoseconds using its current cycle-to-time ratio. That's the forty-nanosecond resolution coming through.

The cost is real. With C-Y-C on, the byte rate roughly doubles compared to Low mode. Your ring buffer fills faster, and overflow becomes more likely on busy code. Most users run Normal mode by default and only drop to Low when they're hitting overflow problems.

Up next: the packet that reconciles M-T-C with T-S-C, called T-M-A.

---

## 49. T-M-A and the interpolation trick

**Overview.** T-M-A, timing mostly accurate, is the packet that stitches the M-T-C counter and the T-S-C counter together. It says, in effect, "at this moment, T-S-C read this value and M-T-C was at this count." The decoder uses it to interpolate time between T-S-C anchors.

**Detailed.** M-T-C on its own is a local counter without meaning. T-S-C on its own is sparse. T-M-A is the Rosetta stone between them. It's emitted periodically alongside T-S-C and tells the decoder which M-T-C value corresponds to the T-S-C reading.

With that pair, the decoder can build a linear model: from this T-S-C and M-T-C, derive the ratio of M-T-C ticks to T-S-C cycles, and use it to translate any subsequent M-T-C to an estimated T-S-C value. Then the shift-multiply formula turns that estimated T-S-C into nanoseconds.

When cycle packets are also on, the same idea extends down another level: between two M-T-Cs, use C-Y-C deltas to refine the estimate further. The decoder maintains a running best guess of wall-clock time and corrects it whenever it sees a higher-authority packet.

You don't interact with T-M-A directly. It happens automatically, the hardware emits it as part of the standard timing group, and the decoder consumes it without any configuration. But knowing it exists makes the whole timing picture complete: T-S-C for anchors, M-T-C for intermediate, C-Y-C for fine detail, T-M-A for converting between the first two.

If you see obvious timing artifacts in a trace — events that seem to be happening faster or slower than they should — it often traces back to misinterpreted timing packets, usually because the conversion factors the kernel provided were stale or the C-P-U changed frequency in a way that the decoder handled imperfectly. The latter is fixed by the packet we'll describe next.

Up next: the core bus ratio packet, which tells the decoder the C-P-U changed frequency.

---

## 50. C-B-R, core bus ratio changes

**Overview.** When the C-P-U changes frequency — because of turbo, thermal throttling, or power management — the ratio between cycles and nanoseconds changes. The core bus ratio packet, C-B-R, tells the decoder the new ratio so it can recompute timestamps correctly. Magic-trace recognizes these and emits them as visible power events.

**Detailed.** Modern C-P-Us constantly adjust their frequency. Under load, the turbo logic ramps up past the rated frequency. Under light load, the chip drops into lower power states. Thermal events can cause sudden throttles. A single workload can span many different frequencies over a few milliseconds.

This matters for timing because C-Y-C packets measure cycles. The conversion from cycles to nanoseconds depends on the frequency. Two hundred cycles at four gigahertz is fifty nanoseconds. Two hundred cycles at two gigahertz is a hundred nanoseconds. If the decoder is still using the old ratio after the frequency changed, its timestamps drift until it gets a new T-S-C anchor to rebaseline from.

C-B-R packets give the decoder an early correction. Every time the frequency changes, the tracing unit emits a C-B-R packet whose payload is the new ratio, expressed as a multiplier relative to a base frequency. The decoder updates its cycle-to-nanosecond factor immediately and continues.

Magic-trace surfaces C-B-R to the user as a power event. In perf's text output, you'll see lines labeled c-b-r along with a frequency in megahertz. The magic-trace decoder's regex catches those lines and produces a dedicated power-event entry in the trace. In the viewer, they show up as markers on a separate track so you can see when the C-P-U changed speed.

This is sometimes useful. If you see a function taking suspiciously long at one moment and suspiciously short at another, check whether a C-B-R event happened in the interval. Frequency drops explain a lot of "why did my trace look weird" questions.

Up next: the physical destination of all these packets — the tracing buffer.

---

## 51. Where packets go, physically

**Overview.** The tracing unit writes packets to a region of physical memory that the kernel set up in advance. The region is memory-mapped into perf's address space, and indirectly into magic-trace's via perf's file interface. The whole pipeline is designed around this shared-memory-plus-file-descriptor model.

**Detailed.** At a physical level, packets are just bytes being written to a specific memory address. The tracing unit has an output address, configured by the kernel through an M-S-R. When it produces bytes, it writes them out via the normal memory subsystem — no special bus, no special protocol. The D-R-A-M doesn't know that the bytes came from a tracing unit. They're just writes.

The kernel chooses where in physical memory this output region sits. It picks some physical pages, tells the tracing unit to use them as its output buffer, and then memory-maps them into the virtual address space of whatever process opened the perf event. That process — perf record, or magic-trace's direct backend — can now read the packets as ordinary memory.

The mechanics of this mapping are worth a moment. Perf's memory-mapped buffer has two regions. The first is called the data area; it holds perf's own events, like context-switch notifications and memory-map events. The second is called the A-U-X area; it holds the Intel Processor Trace packet stream. When perf record is running with Intel P-T, both regions are live, and the tool reads from both to get a complete picture.

Magic-trace, in its default mode, doesn't touch these regions directly. It runs perf as a subprocess, and perf reads the regions and writes a perf-dot-data file. Magic-trace then invokes perf script to re-read that file and emit text. The direct backend cuts out all that indirection: it opens the perf event itself, memory-maps the buffer itself, and feeds packets directly into libipt.

The upshot is that the tracing pipeline is designed around this one big idea: the hardware writes packets to memory, and a file descriptor with a memory map is how that memory gets exposed to user-space. Everything else — the data areas, the A-U-X areas, the sideband records — sits on top of this primitive.

Up next: the data structure that describes the output buffer to the tracing unit, called the toe-pah.

---

## 52. The table of physical addresses, or toe-pah

**Overview.** The tracing unit doesn't need to know about virtual memory. It writes to physical addresses. The kernel describes the set of physical pages the tracing unit may write to through a small table called the toe-pah, spelled T-o-P-A. The toe-pah can be configured to wrap around, which is what creates a ring buffer.

**Detailed.** The tracing unit needs somewhere to put its bytes. The simplest arrangement would be "here's a contiguous block of physical memory, write to it." But physical memory is usually not available as large contiguous blocks — the kernel allocates in page-size chunks scattered around D-R-A-M.

The solution is a table. Toe-pah, spelled T-o-P-A, is a list of entries, each entry pointing at one physical page and specifying its size and what to do when that page fills up. The tracing unit reads the table in order. When it fills one entry's page, it moves to the next entry. When it reaches the end, it depends on what the last entry says.

One option: stop. The last entry is marked as a stop, meaning when the tracing unit fills that page, it turns tracing off. This gives you a one-shot linear buffer. Useful for full-execution tracing of a short-lived program.

Another option: wrap. The last entry is marked to indicate the tracing unit should return to the first entry and start overwriting old data. This gives you a ring buffer — old data is lost as new data comes in. Perfect for snapshot mode, where the most interesting data is the most recent and you're fine losing ancient history.

Linux configures the toe-pah in ring mode for snapshot-style tracing, which is magic-trace's default. The ring walks around until perf is told to snapshot, at which point the kernel reads out the contents and copies them to disk.

There's a third option — an interrupt — where filling the table's last entry raises a hardware interrupt. This is used for tracing modes that stream to disk continuously rather than snapshotting. Magic-trace doesn't use this mode, but perf offers it for other workflows.

You don't configure the toe-pah directly as a user. Perf does it for you. But knowing it's there demystifies the mechanism — a ring buffer of the last ten milliseconds is really a toe-pah walking its own table in a circle, endlessly.

Up next: the distinction between ring mode and stop mode from the perspective of magic-trace.

---

## 53. Ring mode versus stop mode

**Overview.** A tracing buffer can either overwrite old data as new data comes in, or stop recording when it fills up. Magic-trace uses the former — ring mode — because its whole model is "the last few milliseconds before a trigger." Stop mode exists for full-execution tracing of short programs.

**Detailed.** Let me put this in user terms. Imagine you've been watching a TV show, and you press pause. You want to rewind, but how far back can you go? That depends on how much buffer the set has. A small buffer lets you go back a few minutes; a large one, hours.

Magic-trace is set up like a PVR with a fixed buffer. The tracing hardware is always recording into the buffer; old data continuously drops off the end; new data comes in at the front. When your trigger fires — Ctrl-C or a breakpoint hit — magic-trace snapshots whatever's in the buffer. That gives you the last ten milliseconds or so, depending on buffer size and workload.

That's ring mode. The toe-pah is configured to wrap; old data is overwritten. You can't look back before your snapshot window, but you can always snapshot on demand.

Stop mode is the opposite. The tracing unit fills the buffer until full, then stops. If your program finishes before the buffer fills, you've got a full record. If it doesn't, you've got a record of the beginning and no visibility into the rest.

Stop mode is useful for short programs where you want to see everything from start to finish. Magic-trace's dash-full-execution flag enables this. It's only practical for programs that run briefly — maybe a second or two — because otherwise the buffer fills and you lose everything after.

For most workflows, ring mode with snapshot triggers is the right answer. You don't care about the whole execution; you care about the specific moments where something interesting happened. Ring-plus-snapshot gives you exactly that: a fixed-size window positioned at the trigger moment.

Up next: the specific part of perf's memory-mapped buffer that holds the P-T packet stream.

---

## 54. The A-U-X area of perf's mmap

**Overview.** When you memory-map a perf-event file descriptor, you get two logical regions. The main data area holds perf's own events — memory maps, context switches, task creation and destruction. A separate A-U-X area holds auxiliary data from specific event types, including Intel Processor Trace. Magic-trace reads from the A-U-X area to get the P-T packet stream.

**Detailed.** Here's a concrete picture. A perf event is opened via perf-event-open, returning a file descriptor. You then call mmap on that F-D, typically requesting a buffer sized in pages. The kernel gives you back a virtual address pointing at what looks like a normal memory region, but with some structure.

The first part of the region is the metadata page — a fixed-size structure with read and write pointers, a capabilities flag, the timing conversion constants we talked about earlier, and so on. It's user-readable so that tools can check where the latest data ends without a system call.

The next part is the data area. This is where standard perf events go — every mmap event, every context switch, every sample. It's a ring buffer, and the metadata page tells you where the current read and write heads are.

When you're using an auxiliary-data event like Intel Processor Trace, there's a separate region, the A-U-X area, which is where the high-volume auxiliary data lands. P-T packets go here, not into the main data area. The metadata page has its own pointers for the A-U-X head and tail.

From magic-trace's perspective, this means it needs to read both areas and integrate them. The data area gives it sideband events — context switches, mmaps, exec events — and the A-U-X area gives it the actual packet stream. Libipt, when driven by the direct backend, reads the A-U-X bytes as its input and uses the data-area events to update its model of what's loaded where.

The size of each area is configurable. Data area size is controlled by one dash-m parameter to perf; A-U-X size by a separate one. Magic-trace sets them both to reasonable defaults. If you need a bigger buffer, you pass a bigger value; magic-trace rounds up to the nearest power of two because that's what the kernel wants.

Up next: why buffer sizes must be powers of two.

---

## 55. Why the buffer size is a power of two pages

**Overview.** Perf and the tracing hardware both require buffer sizes to be a power of two multiple of the page size. This isn't a minor preference — it's a hardware requirement for efficient ring arithmetic. Magic-trace has a small module that handles rounding up your requested size to the nearest valid value and warning you when it does.

**Detailed.** A ring buffer with a power-of-two size has a beautiful property. To get the position of the next write, you compute "current position plus one, bitwise-and with buffer size minus one." That bitwise-and is a single C-P-U instruction, and it correctly wraps around. If the buffer size were not a power of two, you'd need a modulo operation, which is much more expensive.

The tracing hardware, by running at full speed, cannot afford modulo in its inner loop. So it requires power-of-two buffers. The kernel accepts only such sizes for the A-U-X buffer. User-space has to supply a valid size.

Magic-trace exposes buffer size through a flag, but users don't always pick a valid value. They might ask for one megabyte or three megabytes — not power-of-two multiples of the four-kilobyte page. Magic-trace has a small utility, called pow-two-pages, whose job is to take the requested size and round it up to the nearest power-of-two page count. It also prints a warning if it had to round, so the user knows what actually got used.

The valid range is from four kilobytes at the low end — one page — up to hundreds of gigabytes at the high end. Realistically, you'll use something between two hundred fifty-six kilobytes and a few megabytes. The tool also enforces a floor and a ceiling, to avoid obviously-broken values.

For most users, the defaults are fine. Root users get four megabytes; unprivileged users get two hundred fifty-six kilobytes. The unprivileged limit comes from Linux's resource limits on locked memory — ordinary users are allowed to lock only so much memory into physical D-R-A-M, and the tracing buffer counts against that quota.

If you consistently hit overflow errors on noisy workloads, bumping up dash-m is the first thing to try, as long as you're running as root or have appropriate capabilities.

Up next: what it really means to take a snapshot of the tracing buffer.

---

## 56. Snapshots at the hardware level

**Overview.** A snapshot is the operation of pausing the tracing hardware, reading the current contents of the ring buffer, writing those contents to disk, and resuming. It all happens in milliseconds. The trigger — Ctrl-C or a breakpoint hit — is what sets the operation in motion.

**Detailed.** Here's the dance when magic-trace takes a snapshot, step by step. Something in magic-trace decides "now." Either Ctrl-C came in, or a breakpoint fired, or the target process exited. Magic-trace sends a snapshot command to perf, either through the modern control-file-descriptor protocol or, on older kernels, via an S-I-G-U-S-R-two signal.

Perf receives the command. It issues an ioctl against the tracing event, telling the kernel "stop tracing and let me copy the buffer." The kernel disables the tracing hardware — flips the trace-enable bit in the control M-S-R. The hardware stops emitting packets immediately.

Perf then reads the ring buffer from the point marked by the head pointer back to the tail pointer — essentially "the last N bytes, in order." It writes those bytes to the perf-dot-data file. The file format wraps the raw A-U-X bytes in a small envelope identifying them as P-T data.

Optionally, perf re-enables tracing. If magic-trace is in multi-snapshot mode, the next trigger can snapshot again. If it's single-snapshot mode, perf is told to shut down entirely, which tears down the event and exits.

All of this usually takes a few milliseconds. From the target process's perspective, there's a brief pause while the snapshot happens — but since magic-trace is external to the target, the pause doesn't show up in your program's logic. The tracing hardware was briefly disabled; that's the only effect.

The output on disk is a perf-dot-data file containing the raw packet bytes, plus a few metadata records. That's what magic-trace hands to perf script later for decoding.

What the snapshot contains, specifically, is the last ring-buffer's worth of packets. If the buffer is four megabytes and held roughly ten milliseconds of history, that's what your snapshot contains. No earlier; no later.

Up next: the filter that makes per-process tracing work.

---

## 57. The C-R-three match filter

**Overview.** Intel Processor Trace has a filtering M-S-R that can be configured to only emit packets when the current C-R-three register matches a specified value. Since Linux gives each process a unique C-R-three, this filter implements per-process tracing. It's how perf dash-p actually works at the hardware level.

**Detailed.** We talked earlier about C-R-three, the register that names a process's address space, and how the scheduler writes it on every context switch. Now we can see what Intel Processor Trace does with it.

There's an M-S-R called C-R-three-match. The kernel writes a specific C-R-three value into it. The tracing hardware watches the live C-R-three register against that stored value and only emits packets when the two match. On a core running the target process, tracing fires. On a core running anyone else, tracing is silent.

This is not a software filter that processes packets after they're emitted. It's a gate in the hardware packet-generation path. No packets are emitted at all outside of the matching C-R-three. That's important for the overhead story — tracing a single process doesn't pay the cost of generating and then discarding packets from other processes.

When the scheduler switches from your traced process to another, C-R-three changes. The tracing unit emits a P-G-D packet to mark tracing going off, and then stops. When the scheduler switches back, C-R-three matches again, the tracing unit emits a P-G-E to mark tracing coming back on, and resumes.

If the target is multi-threaded, all its threads share the same C-R-three — they're the same process. So the filter captures all of them. You trace the process as a whole. That's almost always what you want.

If you ask magic-trace to trace multiple P-I-Ds, the tool turns that into multiple C-R-three-match filters — one per target address space. Each core's tracing hardware then fires on any of those processes.

Up next: the bits that let you scope tracing to user-space or kernel-space specifically.

---

## 58. U-S-R and O-S enable bits

**Overview.** Two bits in the tracing control M-S-R decide whether user-space code gets traced, kernel-space code gets traced, or both. These correspond to the slash-u, slash-k, and slash-u-k selectors in perf's event syntax and to magic-trace's trace-scope flag.

**Detailed.** Recall the privilege rings. User code runs in ring three; kernel code runs in ring zero. Intel Processor Trace can trace either, both, or neither — independently configurable by two bits in the tracing control M-S-R called U-S-R and O-S.

If U-S-R is set and O-S is clear, the tracing unit only emits packets while the C-P-U is in ring three. Every time the program makes a system call and enters ring zero, tracing goes off. When the call returns and the C-P-U flips back to ring three, tracing resumes. This is the default for magic-trace — trace user-space only.

If O-S is set and U-S-R is clear, it's the reverse. Tracing only fires in ring zero. You see what the kernel is doing; you don't see user code. This is a specialized mode used for kernel performance work.

If both are set, tracing fires in both rings. You see the full execution, including syscalls and page-fault handlers and interrupt processing. This is the most detailed view and also produces the most data.

Magic-trace's trace-scope flag maps directly to these three possibilities. User-space is the default. Pass trace-include-kernel to get both. Pass trace-kernel-only to get just kernel. Under the hood, each option just sets different bits in the U-S-R and O-S configuration.

There's a subtle point worth noting. Even in user-only mode, syscalls and interrupts still show up as state-change events in the output — you see tr-end marks when tracing goes off at kernel entry and tr-strt marks when it resumes. That's because the hardware filter is engaging and disengaging as the privilege level flips. If you want to understand what happened during those tr-end gaps, you need to enable kernel tracing.

Up next: a filter that magic-trace doesn't expose but that exists in the hardware.

---

## 59. Address-range filters

**Overview.** Intel Processor Trace supports up to four address-range filters, where each filter names a virtual-address range and tracing only fires when the instruction pointer is within that range. Magic-trace doesn't expose these, but they're interesting to know about — a future enhancement might use them to trace only a specific library.

**Detailed.** Think of C-R-three filtering as "only trace when in this process." Address-range filtering is the same idea at a different granularity — "only trace when in this particular memory range." You can combine them: only trace when in this process, and also only when within this range of virtual addresses.

Each filter is a pair of M-S-Rs — a start address and an end address. You can have up to four such pairs active, plus a configuration bit that says for each filter whether matches should enable or disable tracing.

A plausible use case: you want to profile only a specific shared library. You know what virtual address range it's loaded at. You program a filter to "enable tracing when instruction pointer is within this range." Now you see only branches inside that library; all other code is invisible.

Another use case: you want to exclude a specific noisy region, like a busy-wait loop you don't care about. You program a filter to "disable tracing within this range." Branches elsewhere are captured; the loop is silent.

Magic-trace doesn't currently expose these. It has a dash-filter flag, but that's a post-processing filter applied at decode time, not a hardware filter — it restricts what you see in the final viewer, not what the hardware records. A hardware-level range filter would be a plausible future feature.

One reason hardware range filters haven't made it in is that they're awkward to use with position-independent code, where addresses shift per run. You'd need to resolve the library's load address at attach time and compute the range on the fly. Doable, but more complex than the current model.

Up next: why kernel tracing requires root.

---

## 60. Why kernel tracing requires root

**Overview.** Linux refuses to let unprivileged users trace kernel code. The justification is security — kernel internals are sensitive, and a full trace could leak information an attacker shouldn't have. Magic-trace checks for root up front before enabling kernel scope.

**Detailed.** The kernel handles private data on behalf of every process on the system. It has access to memory that no user process is allowed to see. It makes security-relevant decisions using secrets in its own memory.

A full trace of kernel execution would potentially leak a lot of that. You'd see exactly which branches were taken during a password check, which could be a side channel into password content. You'd see the addresses of kernel data structures, which attackers could use to bypass address-space layout randomization in exploits. You'd see timing information that could expose internal cryptographic operations.

For these reasons, Linux restricts kernel-level profiling to privileged users. Technically, the restriction is controlled by a system-wide setting called perf-event-paranoid and by the file capabilities on the perf binary. Users who are members of specific administrative groups can sometimes do kernel profiling without being root, but the cleanest answer is "be root."

Magic-trace enforces this by checking the effective U-I-D before starting. If you ask for kernel tracing and you're not U-I-D zero, you get an error right away. The check happens before any setup, so you don't have to wait for perf to fail later.

The check is technically stricter than necessary — linux capabilities could suffice — but the code notes this and errs on the side of simplicity. Root is a reliable proxy for "this user has elected to do privileged operations and accepts the security consequences."

When you do run as root and enable kernel tracing, you see a different world. All those tr-end gaps that were empty in user-only mode are now filled with kernel code — interrupt handlers, syscall implementations, scheduler decisions, memory management. It's enormously informative and also enormously more data.

Up next: the core decoding loop the decoder runs.

---

## 61. The binary-walking loop

**Overview.** The decoder walks through the binary, disassembling instructions, consuming packets when it hits branches, emitting events when control flow changes. That loop is the heart of all Intel Processor Trace decoding. Everything else is plumbing around it.

**Detailed.** Let me describe the loop directly. The decoder has two pieces of state: a current instruction pointer and a copy of the loaded binary. It starts at some known instruction pointer, typically given by a synchronization packet's anchor.

Then it enters a loop. At each iteration, it looks at the binary at the current instruction pointer and decodes one machine instruction. If the instruction is not a branch — an add, a move, a load — it just advances the instruction pointer past it and loops.

If the instruction is a direct branch — a direct call, a direct jump, a conditional jump — the decoder handles it. For a direct unconditional branch, it just changes the instruction pointer to the target encoded in the instruction. For a conditional branch, it consumes the next T-N-T bit from the packet stream: if the bit is one, jump to the target; if zero, fall through. For a direct call, it pushes the return address onto its shadow call stack and jumps to the target.

If the instruction is an indirect branch — an indirect jump, an indirect call, a return — the decoder consumes a T-I-P packet to get the actual target address. It sets the instruction pointer to that address and continues.

Throughout, whenever a branch crosses a function boundary, the decoder emits an event — "call this function," "return from that function," "jump from here to there." Magic-trace's upper layers consume these events to reconstruct the call stack.

The decoder also handles asynchronous events. When an F-U-P arrives, it knows an interrupt happened at the F-U-P's instruction pointer. It consumes associated mode and T-I-P packets to figure out where control went. It emits an event describing the transition.

On a synchronization packet — P-S-B — the decoder resets its internal state and starts fresh from whatever anchor the P-S-B group provides. On an overflow packet, it emits a decode error and waits for the next sync to recover.

This loop runs on every single branch in the trace. That's hundreds of thousands to millions of iterations for a typical magic-trace snapshot. Libipt, Intel's reference library, implements it in C for performance.

Up next: why the binary the decoder uses must be correct.

---

## 62. Why the binary must be correct at decode time

**Overview.** The decoder reads instruction bytes from the binary to figure out what each branch is. If the binary it reads doesn't match what the C-P-U actually executed, the walk goes off the rails immediately. This invariant is harder to maintain than it sounds, and several magic-trace gotchas trace back to it.

**Detailed.** Recall the decoder's core loop. It reads the instruction at the current instruction pointer and decides how to proceed. That read comes from a file on disk, not from the live process's memory. The decoder assumes the file matches what the C-P-U saw.

Normally, it does. The on-disk binary was mapped into memory unchanged. The C-P-U read instructions from that mapping. The decoder, reading the same file, sees the same bytes. Great.

But consider some complications. If code was modified in memory after being loaded — through a just-in-time compiler that patches its own output, or through a system that rewrites machine code for instrumentation — the in-memory bytes no longer match the disk. The decoder, reading the disk, will disassemble the wrong bytes. Every branch decision after that point will be wrong.

Or consider libraries. If a library was loaded while the trace was being recorded but no sideband mmap event was captured, the decoder doesn't know what binary to read for that address range. It falls back to "unknown" and the trace has gaps.

Or consider containers and chroots. If the decoder is running on a different filesystem view than the target process, it might read the wrong binary — a different libc, for example. Same file path, different contents.

Or consider simply running the decode offline much later. If the binary on disk was rebuilt or updated in the interim, the decoder reads the new version and gets different instructions than were actually executed.

Magic-trace mitigates these by decoding immediately after capture, while the process and its loaded binaries are still present. But edge cases remain. Magic-trace's direct backend captures explicit memory maps from slash-proc-slash-P-I-D-slash-maps to know what binary is where; the default backend gets this through perf's sideband events.

If you ever see decoded output that looks nonsensical — functions that couldn't possibly be in the call tree you're looking at — a mismatch between the decoded binary and the executed binary is a prime suspect.

Up next: the sideband events that tell the decoder what got loaded when.

---

## 63. Sideband events and why they matter

**Overview.** Perf records a stream of events alongside the P-T data that describes changes in the target process — new memory maps, context switches, exec calls. The decoder uses these sideband events to keep its model of "what binary is at what address" up to date. Without sideband, long-running traces would drift off into garbage.

**Detailed.** The P-T packet stream tells the decoder about branches. That's useful, but it doesn't tell the decoder everything it needs to know. What happens if, during the trace, the target process loads a new shared library? From the C-P-U's point of view, that's just a few syscalls and then some memory is mapped. The tracing hardware doesn't know about the mapping — it just sees the instructions that do the mapping.

Perf, meanwhile, is watching the process from the kernel side. It sees the syscall. It records an event describing the mapping: "this file has been loaded at this virtual address with these permissions." The event lands in the data area of perf's mmap buffer — the non-A-U-X region.

The decoder reads both streams in parallel. The A-U-X stream gives it branches; the sideband stream gives it memory-map events, exec events, context switches, task creation and exit. When a memory-map event arrives, the decoder updates its model: from now on, addresses in that range correspond to bytes from that file.

Libipt has a companion library called libipt-sideband — or libipt-sb for short — whose job is to consume these sideband records and keep libipt's state in sync. The default backend gets this automatically because perf does it internally. The direct backend wires it up manually, feeding perf's data stream to libipt-sb while feeding the A-U-X stream to libipt.

Sideband also captures context switches. When the scheduler moves a thread from one core to another, the decoder needs to know, because the per-core tracing buffers now have a different thread's execution in them. Context-switch events on the sideband stream tell the decoder "this thread left this core at this moment" and "this thread arrived at this core at this moment," and the decoder stitches accordingly.

All of this happens under the hood. Users don't interact with sideband directly. But it explains how long-running, multi-threaded, dynamically-linking programs can be traced coherently.

Up next: image section I-Ds, libipt's concept for identifying loaded binaries.

---

## 64. Image section I-Ds

**Overview.** Libipt gives each loaded binary segment a numeric identifier called an image section I-D, or I-S-I-D. Every decoded event is tagged with the I-S-I-D of the binary it came from, which lets the decoder look up the right symbol table. Magic-trace's direct backend uses I-S-I-D for exactly this purpose.

**Detailed.** Consider a process with several libraries loaded. The target binary, libc, libm, a handful of support libraries. Each is loaded at some virtual address range. Now imagine a trace event at address zero-x-seven-f-some-random-address. Which library is it in? You could search by address, but that's slow and not quite right — two different libraries could end up at overlapping ranges if sequences of loads and unloads happen.

I-S-I-D is libipt's solution. When a memory-map event is processed, libipt assigns a new I-S-I-D to that mapping. Every event the decoder emits thereafter carries the I-S-I-D of the mapping it came from. When magic-trace wants to resolve an address to a symbol, it first uses the I-S-I-D to find the right binary, then searches by offset within that binary's symbol table.

The practical effect is that symbol resolution can't accidentally confuse two binaries. If the same virtual address range gets unmapped and remapped with a different library, old events still point to the old I-S-I-D and resolve against the old binary; new events point to the new I-S-I-D and resolve against the new one.

Magic-trace's direct backend threads I-S-I-D through its event pipeline explicitly. Each event has an I-S-I-D field alongside its address. When it comes time to resolve, the resolver table is keyed by I-S-I-D. The default backend achieves the same thing implicitly through perf's built-in handling.

You'll never see I-S-I-D in any user-visible output. It's a purely internal bookkeeping value. But it's another piece of plumbing that makes the "binary must be correct at decode time" invariant robust to real-world complications.

Up next: the library that implements all this decoding for real.

---

## 65. Libipt, the decoder library

**Overview.** Libipt is Intel's open-source reference implementation of an Intel Processor Trace decoder. It's a C library that takes packet bytes and emits events. Both perf and magic-trace's direct backend use it. Anyone who wants to write their own P-T-consuming tool starts from libipt.

**Detailed.** Libipt is maintained in the open on G-i-t-H-u-b. It implements the full P-T decoding algorithm — the binary-walking loop, packet parsing, state machines for filtering and synchronization, everything. The companion library, libipt-s-b for sideband, handles the perf integration.

When you run perf script on a perf-dot-data file containing P-T data, perf reads the packets, feeds them to libipt, and gets back events. Perf then formats those events as text for output. That's literally what magic-trace's default path does — it calls perf script and parses the text.

Magic-trace's direct backend, as the name suggests, cuts out the text intermediate. It links against libipt directly through C stubs. The backend calls a few libipt functions: one to initialize a decoder, one to step the decoder forward to the next event, one to handle image-section updates. Events come out as a stream of C structs that the OCaml side consumes.

Libipt is fast. It's written to avoid memory allocation in the hot loop, to dispatch on packet type with a table rather than a switch, to cache disassembly state between adjacent events. Running it in-process, as the direct backend does, avoids the text-formatting and text-parsing overhead of the perf-script path.

Why, then, does magic-trace default to the perf-script path? Practical reasons. Perf has mountains of special-case handling for things like the virtual dynamic shared object, for kernel-call stitching, for various C-P-U quirks. Replicating all of that in the direct backend would be a big effort, and the maintenance burden of keeping up with libipt and kernel changes is nontrivial. The default path gets all the benefits of perf's maturity for free.

If you're curious, libipt ships with a simple example program called p-t-x-e-d that demonstrates the absolute minimum to decode a P-T buffer. It's a few hundred lines and serves as the canonical "hello world of P-T decoding."

Up next: perf script, the decoder front end everyone actually uses.

---

## 66. Perf script as a decoder front end

**Overview.** Perf script is a subcommand of the perf tool that reads a perf-dot-data file and prints human-readable events — one line per event. It wraps libipt behind a text interface. Magic-trace's default backend invokes it and parses its output with regular expressions.

**Detailed.** When a perf-dot-data file contains P-T data, ordinary perf report isn't very useful. It wants statistical aggregation, and P-T is trace data, not sampled data. What you want is to walk through the events in order. That's what perf script does.

You invoke it with a handful of flags telling it what to emit. A typical magic-trace invocation says something like dash-dash-itrace equals b-e-p — meaning emit branches, errors, and power events — plus dash-F for the fields to include in the text output, plus dash-dash-dlfilter pointing at a filter library to exclude uninteresting jumps.

Perf script opens the perf-dot-data file, reads the P-T A-U-X records, passes them to libipt, and translates libipt's emitted events into text lines. Each line has a consistent format: a pid-tid pair, a timestamp, a period, an event type, and then event-specific fields like the source and destination addresses.

The output looks spartan. It's a line per event, hundreds of thousands of lines for a typical snapshot. Magic-trace reads those lines with a set of regular expressions — one regex for the event header, one for the branch body, one for trace errors, one for power events. Each line becomes an event value in the OCaml code.

This design has two nice properties. First, the perf script invocation and its output are a stable A-B-I. Kernel updates that change the underlying decoding details don't break magic-trace, because perf smoothes them over. Second, the text is a convenient fixture format — magic-trace's tests include recorded perf script outputs as golden files, and the decoder can be run on those without needing real hardware.

The downside, relative to the direct backend, is performance. Formatting text and parsing it isn't free. For large traces, perf-script-plus-parsing takes longer than direct libipt would. In practice, it takes a few seconds even for big traces — not a bottleneck compared to capture, which is where the time budget really matters.

Up next: the architectural reason magic-trace shells out to perf.

---

## 67. Why magic-trace shells out to perf

**Overview.** Magic-trace could link against libipt and do all decoding in-process. It doesn't, by default. Instead, it runs perf as a subprocess. The reason is not performance — the reason is perf's enormous library of special-case handling for real-world complications.

**Detailed.** The obvious architecture for a P-T-based profiler is: open a perf event, memory-map the buffer, drive libipt in process, emit results. That's clean, fast, and self-contained. Magic-trace's direct backend does exactly that.

The actual default architecture is messier: spawn perf record, let it write a perf-dot-data file, then spawn perf script to read it back, decode, and emit text, which magic-trace parses. Two subprocesses and a text intermediate.

Why the indirection? It's not elegance and it's not performance. It's the long tail of fiddly real-world issues that perf has accumulated code for over years. The virtual dynamic shared object, which has no on-disk binary — perf handles it. Stitching kernel-call traces across user-kernel boundaries — perf handles it. Context-switch bookkeeping across multiple cores — perf handles it. Obscure Intel bugs that require specific workarounds — perf has patches for them.

Replicating all of that in magic-trace would be a lot of ongoing work. Every kernel release might introduce a new edge case. Every new C-P-U generation might need new handling. Perf has a paid kernel team keeping all of this up to date. Magic-trace, a tool from Jane Street, doesn't have the bandwidth to reinvent that wheel.

So the default is: lean on perf for everything that doesn't fundamentally need to be in-process. The price is some performance, a couple of subprocesses, and a parsing stage. Those costs are all small compared to the cost of maintaining a parallel Rosetta Stone for every kernel-P-T quirk.

The direct backend remains in the tree as an interesting alternative — proof that in-process libipt works, a platform for experimenting with deeper integration. But the ordinary production path is "ask perf, parse the result."

Up next: the two backends, described as a pair.

---

## 68. The two backends — tool and direct

**Overview.** Magic-trace has two capture-and-decode backends. The default one shells out to perf; the experimental one calls libipt directly. Both satisfy the same backend interface, so most of magic-trace's code is backend-agnostic. Only the default is production-ready.

**Detailed.** Inside magic-trace, the capture-and-decode pipeline is parameterized over something called a backend module. A backend has to provide a few operations: attach to a process and start recording, take a snapshot, finish recording, decode events. As long as a backend implements those, the rest of magic-trace works.

There are two implementations. The first, called the perf-tool backend, is what you get by default. It spawns perf record and perf script subprocesses and parses their output.

The second, called the direct backend, lives in its own subdirectory and calls libipt through C stubs. It opens the perf event itself, memory-maps the buffer, and threads packets directly to libipt. No subprocess, no text.

In principle, the direct backend should be faster. In practice, it's a work in progress. The readme in its subdirectory honestly acknowledges it doesn't yet handle the virtual dynamic shared object, it doesn't support multi-threaded recording well, and it's missing other features that perf has accumulated. Because of this, it's not wired into the CLI — you can't actually choose it with a flag on the main command.

The direct backend exists as reference code. If anyone ever wants to do something that requires deeper control — sub-microsecond analysis, experimenting with new decoding strategies, writing tools that perf doesn't support — the direct backend is the starting point. It's a lot of code, carefully commented, showing how to drive libipt in real time.

For all ordinary use, the default backend is what you want. It's what the command tree instantiates, and it's what every example in the docs assumes.

Up next: an overview of the capture pipeline, end to end.

---

## 69. The capture pipeline, overview

**Overview.** Let's tie together the capture side. Magic-trace starts, picks a backend, attaches to a P-I-D or spawns a child, launches perf, optionally arms a breakpoint, and waits for a trigger. On the trigger, it tells perf to snapshot and then decode. Everything after "decode" is the other pipeline.

**Detailed.** Here's the capture sequence at a high level. First, command-line parsing. Magic-trace's main function figures out which subcommand — run or attach or decode — the user invoked, and what flags came with it.

Second, capability probing. Before doing anything serious, magic-trace checks the environment — does Intel P-T exist, does perf support the control F-D protocol, does the kernel support snapshot-on-exit. The results tune subsequent behavior.

Third, target selection. For attach, the user provided a P-I-D, or the fuzzy picker let them pick one. For run, the child process is forked, suspended via ptrace, ready to be resumed. Either way, magic-trace now has a target P-I-D.

Fourth, symbol and trigger resolution. If the user specified a trigger function, magic-trace reads the target's E-L-F, finds the function, gets its address. If the user didn't specify a trigger, Ctrl-C becomes the default.

Fifth, perf record launch. Magic-trace constructs a perf command line with all the right flags — Intel-P-T event, ring-mode snapshot, the P-I-D to attach to, a control file descriptor for commands. It forks perf as a subprocess.

Sixth, trigger arming. If a breakpoint was requested, magic-trace uses the perf-event-open system call a second time, this time asking for a hardware breakpoint at the trigger address. The F-D for the breakpoint is polled in an async loop.

Seventh, wait. The main loop sits waiting for either the breakpoint to fire, or S-I-G-I-N-T from Ctrl-C, or the child process to exit. Any of these fills a shared done signal.

Eighth, snapshot. When done fires, magic-trace tells perf to take a snapshot, via the control F-D or via S-I-G-U-S-R-two on older kernels. Perf dumps its buffer to perf-dot-data.

Ninth, shutdown. Magic-trace tells perf to stop, waits for it to exit, reaps the subprocess. Capture is done.

Everything so far took at most a few hundred milliseconds plus however long the user waited for the trigger. Now decoding takes over, which we'll describe next.

Up next: the decode pipeline overview.

---

## 70. The decode pipeline, overview

**Overview.** Once capture is complete, magic-trace invokes perf script, parses its output, reconstructs call stacks, and writes a Fuchsia-format trace file. The output is a gzipped-dot-fxt file you can drop into Perfetto. This is all the work that happens after the snapshot.

**Detailed.** Let's walk the decode side. First, magic-trace spawns perf script on the perf-dot-data file. It configures the right flags for the workload — branches, errors, and power events for P-T mode; samples for sampling mode. Perf script begins writing lines of text to its standard output.

Second, magic-trace reads those lines through a Unix pipe into an OCaml Pipe of strings. A line-buffering stage groups lines — stack traces for sampling mode come as multiple lines that belong together.

Third, the parsing stage. Each line is matched against a set of regular expressions. One regex extracts the thread ids, timestamp, and event type from the line. Another extracts the specific event fields — source address, destination address, symbol names. A third handles trace-error lines.

Fourth, symbol resolution. For each address in an event, magic-trace tries three sources: perf's provided symbol, the target's perf map file for just-in-time code, and a placeholder unknown tag if both fail. In parallel, it enriches symbols with D-W-A-R-F line-number info if debug data is available.

Fifth, event construction. Each parsed line becomes an O-Caml value of type Event, carrying thread, timestamp, kind, source, and destination. These flow as a pipe into the trace writer.

Sixth, call-stack reconstruction. The trace writer maintains per-thread state — a stack of currently-open function calls. Each Call event pushes a frame. Each Return event pops one. Each jump or tail call triggers adjustments to maintain consistency. Async events create secondary call stacks. Trace-end events push a synthetic untraced frame.

Seventh, output. As the trace writer generates nested begin-end duration events, it hands them to a Fuchsia trace format writer that serializes them to a binary file. The file is gzip-compressed on the fly if the output name ends in dot-gz.

Eighth, finalization. When the input pipe closes, the writer flushes, closes the file, and magic-trace exits. Typical elapsed time for a big snapshot is a few seconds.

The resulting trace-dot-fxt-dot-gz file is what you open in the viewer. That's the whole pipeline.

Up next: attach versus run, in more detail.

---

## 71. Attach versus run

**Overview.** Magic-trace has two ways to start tracing a target. Attach connects to an already-running P-I-D. Run spawns a new process under magic-trace and traces it from its first instruction. The difference is mechanical but meaningful.

**Detailed.** Let's compare the two flows.

Attach is the simpler case. You pass a P-I-D, or let magic-trace pop a fuzzy picker to choose one. Magic-trace reads the target's executable path from slash-proc, loads its E-L-F for symbols, then tells perf record to attach via its dash-p flag. Perf uses the same perf-event-open system call you'd expect, configured with the target's P-I-D as a filter. Once perf is attached, tracing begins immediately.

Attach has one limitation: you can't trace the earliest instructions of a process you didn't start. By the time you've noticed it and attached, it's already past its early setup phase. If you need to see initialization — the dynamic linker, static constructors, the first calls out of main — you need the other option.

Run is the one that lets you see everything from the beginning. Magic-trace uses ptrace to fork a child, let the child set itself up to be traced, exec the target binary, and get stopped at its very first instruction — before any user code has executed. Then magic-trace attaches perf to the child's P-I-D, sets up the breakpoint, and resumes the child via ptrace detach. The first instruction of the target is now being traced.

In practice, attach is what most people use. You're running some long-lived server and it just had a weird slow request; you attach, wait for the next slow request via a trigger, snapshot. For short-lived benchmarks or programs where early initialization matters, run is the right choice.

There's a third subcommand, decode, which doesn't do capture at all. It takes an existing perf-dot-data file and runs just the decode side. Useful for debugging magic-trace itself, or for re-decoding a capture with different flags.

Up next: hardware breakpoints as the function-call trigger.

---

## 72. Hardware breakpoints as triggers

**Overview.** When you ask magic-trace to snapshot on a specific function call, it installs a hardware breakpoint at the function's address. The breakpoint is delivered as a perf event, readable through a file descriptor. Magic-trace polls that F-D in an async loop and triggers a snapshot when the breakpoint fires.

**Detailed.** x-eighty-six C-P-Us have four hardware breakpoint registers, called D-R-zero through D-R-three. Each can be programmed with an address and a condition — fire when read, fire when written, fire when executed. The firing causes a hardware debug exception that the kernel catches.

Linux exposes this capability through perf. You call perf-event-open with an event type of P-E-R-F-underscore-T-Y-P-E-underscore-B-R-E-A-K-P-O-I-N-T, an address, and a fire-on-execute flag. The kernel allocates a debug register, programs it, and hands back a file descriptor. When the breakpoint fires, the F-D becomes readable.

Magic-trace uses this mechanism for its trigger-on-function-call feature. When you pass dash-trigger with a symbol name, magic-trace resolves the symbol to an address, calls perf-event-open with that address, and gets back a file descriptor. It wraps the F-D in an async primitive and starts polling.

The polling loop waits on two things: the breakpoint F-D becoming readable, and an internal flag that Ctrl-C sets. Whichever fires first wins. If the breakpoint fires, magic-trace reads an event from the F-D, records that a hit happened, and asks perf to take a snapshot. If Ctrl-C fires, the same snapshot path runs, but marked as Ctrl-C-originated rather than breakpoint-originated.

One important safety feature. Magic-trace configures the breakpoint as single-hit by default. That means after the first fire, it disarms itself. If you accidentally pointed a trigger at a function that gets called a million times a second, you'd otherwise pay an eight-microsecond interrupt cost every call until the kernel auto-disabled your event. Single-hit mode means the breakpoint self-destructs after its first fire, regardless.

If you really want to capture multiple snapshots, there's a multi-snapshot flag. It disables the single-hit behavior, and you accept the per-call overhead and the fact that your trace file grows with each snapshot.

Up next: the control file-descriptor protocol for talking to perf.

---

## 73. The control F-D protocol

**Overview.** On recent kernels, perf supports a command protocol over file descriptors. Magic-trace creates a pair of pipes, passes their file descriptors to perf, and then writes command strings like quote snapshot unquote or quote stop unquote to tell perf what to do. This replaces the older signal-based mechanism.

**Detailed.** Old versions of perf had a clunky interface for commands. If you wanted perf to take a snapshot, you sent it S-I-G-U-S-R-two. If you wanted it to stop, S-I-G-T-E-R-M. Signals are fast but opaque — you can't tell whether perf actually received and processed them, and you can't pass any additional data.

Linux five-point-ten added a better interface: a control file descriptor. When you invoke perf record, you can pass a flag saying "accept commands on this file descriptor, send acknowledgments on that one." Perf opens the control F-D for reading and the ack F-D for writing. You then write commands as text strings — literal strings like snapshot-newline or stop-newline — to the control F-D. Perf reads them, executes them, and writes acknowledgments back on the ack F-D.

Magic-trace uses this whenever the kernel supports it. On startup, it creates a pair of pipes and passes the corresponding F-Ds on perf's command line. When it wants to take a snapshot, it writes snapshot-newline to its end of the command pipe and blocks waiting for an ack on the other pipe. Perf sees the command, tells the kernel to snapshot, dumps the buffer, and writes an acknowledgment.

The ack is important because snapshots are synchronous from magic-trace's perspective — you want to know when the snapshot actually completed before you proceed to decoding. Signals don't give you that handshake. The F-D protocol does.

The protocol is plain Unix-pipe I-O. The commands are fixed strings. The ack is a fixed byte sequence. Magic-trace handles the handshake carefully: if perf exits unexpectedly, the ack will never arrive, so there's a timeout. If the pipe breaks, magic-trace detects the error and bails gracefully.

On kernels older than five-point-ten, magic-trace falls back to signals. The capability-probing code detects which mechanism is available and selects accordingly.

Up next: how magic-trace probes the kernel's feature set.

---

## 74. Capability probing

**Overview.** Every P-T-related feature — control F-D, snapshot-on-exit, dlfilter, adjustable P-S-B period, kernel tracing — depends on a specific kernel version or specific perf patch. Magic-trace probes for each of these at startup and builds a bitfield of capabilities. The rest of the code consults the bitfield to decide which code paths to take.

**Detailed.** Magic-trace runs on a wide range of Linux installations. Some have kernels from the last couple of months; some have kernels that are years old. Distributions vary in which perf patches they pick up. Cloud VMs often disable Intel P-T entirely.

To handle all this, magic-trace has a single module whose job is "find out what this particular kernel and perf combination can do." The probe runs once at startup. It checks several things.

First, whether Intel P-T is exposed at all. It checks for the existence of a specific sysfs file under slash-sys-slash-bus-slash-event-source-slash-devices-slash-intel-underscore-p-t. If missing, P-T isn't available, and magic-trace falls back to sampling.

Second, whether the P-S-B period is configurable. This checks another sysfs file that reports whether the C-P-U supports the configurable-P-S-B-period capability.

Third, the kernel version, by invoking perf dash-version and parsing the response. Specific features came in specific versions. Snapshot-on-exit arrived in five-point-four; kcore support in five-point-five; control F-D in five-point-ten; dlfilter in five-point-fourteen.

Fourth, whether the current user is root, for kernel tracing eligibility.

Fifth, whether L-B-R is supported, by checking for the pdcm flag in slash-proc-slash-cpuinfo.

Each check sets a bit in a flags value. The result, a small bitfield, is passed around to anything that needs to make a feature-dependent decision. The tool never probes for the same thing twice, and the probing itself is cheap — a few file reads and a subprocess.

When you run magic-trace on an older machine and see a warning like "your machine has an older-generation processor, timing granularity will be coarser" — that warning came from a capability probe deciding your hardware can't support configurable P-S-B period and silently downgrading the timer-resolution setting.

Up next: the dlfilter shared library that reduces noise at capture time.

---

## 75. The perf dlfilter

**Overview.** Perf version five-point-fourteen and later supports loading a shared library that filters events at decode time, before they're formatted as text. Magic-trace ships such a library — a tiny C file — whose one job is to drop jumps that stay within the same symbol. Without it, branchy inner loops produce enormous amounts of noise.

**Detailed.** Recall that Intel P-T emits a packet for every branch. Some branches are actually interesting — function calls, returns, non-local jumps. Some are absolutely not — internal jumps within a single function, say loop iterations expressed as jump-conditional-backward. These latter ones are just noise; for almost any use of magic-trace, they clutter the output.

The old way to filter them was to parse the perf-script text, find the intra-symbol jumps, and drop them. That works but it means perf formats text for lines that will never be used. Inefficient.

Perf added dlfilter support to fix this. A user can write a shared library conforming to a specific A-B-I; perf loads it during decoding and calls into it for every event. The library can return "keep" or "drop." Dropped events are never formatted.

Magic-trace's dlfilter is short — about two dozen lines of C. For each event, it resolves the source instruction pointer and the destination instruction pointer to symbols. If both resolve to the same symbol, it returns drop. Otherwise, keep. That's the whole logic.

The library is a C file because perf's dlfilter A-B-I is C. The C file is compiled to a shared object at build time and stored as data inside magic-trace's binary. At decode time, magic-trace extracts the data to a temporary file and passes the file's path to perf script via the dash-dash-dlfilter option.

On kernels without dlfilter support, the same logic runs in OCaml at the parsing stage. It's slower but identical in effect. Either way, intra-symbol jumps don't make it to the final trace.

You can turn off dlfiltering with an environment variable if you want to see absolutely every branch, including the noise. Most people don't.

Up next: trace scope, one of the user-visible flags, explained in terms of what we've now seen.

---

## 76. Trace scope — user, kernel, or both

**Overview.** The trace-scope flag maps directly to the U-S-R and O-S enable bits in the tracing control M-S-R. User-space only is the default. Including the kernel requires being root. Kernel-only is rare but exists. This is the user-facing way of saying "which rings do I want traced."

**Detailed.** We've covered the U-S-R and O-S bits. The trace-scope flag is the user-facing way to pick among their combinations. The values are userspace, kernel, and userspace-and-kernel.

Userspace, the default, sets U-S-R and clears O-S. You see only ring-three execution. Syscalls, interrupts, and scheduler work are invisible — they produce tr-end events where tracing goes off and tr-strt events where it resumes, but the insides of those gaps are hidden.

Userspace-and-kernel, gated on root, sets both U-S-R and O-S. You see the full story: user code, syscalls as they transit into the kernel, kernel code doing the work, and syscalls returning. This is the most detailed view and usually the one you want when investigating unexplained gaps.

Kernel-only sets only O-S. You see only kernel code. This is a niche mode used for kernel performance work; if you're reading this primer you're probably not using it.

In perf's event-expression syntax, these map to slash-u, slash-u-k, and slash-k suffixes on the intel-underscore-p-t event name. You see those suffixes in perf-script text output — look at the branches colon-u-H pattern, where the u part is the scope and the H bits are additional filter info from perf.

Worth noting: in user-kernel mode, you get much larger traces because you're capturing everything. A simple hello-world with kernel tracing enabled produces visibly more data than user-only. You also tend to get more decode errors, because the kernel code paths involve more weird-but-legal control flow than user code typically does.

Up next: collection mode, the P-T versus sampling choice.

---

## 77. Collection mode — P-T or sampling

**Overview.** The collection-mode flag picks between Intel Processor Trace, which is the default, and stacktrace sampling, which is the fallback. Magic-trace auto-selects based on hardware availability. Explicit sampling mode is mainly useful for running in virtualized environments where P-T isn't available.

**Detailed.** We've spent most of this primer on the P-T path. Let me fill in the alternative.

The sampling path configures perf to sample on hardware cycles, at some rate — ten thousand hertz by default in magic-trace's Normal timer-resolution setting. Each sample captures the current instruction pointer and, depending on callgraph mode, a call stack derived from L-B-R or frame pointers or D-W-A-R-F. The samples accumulate during execution and get written to the perf-dot-data file.

On snapshot, perf dumps the accumulated samples. The decode side — instead of the P-T binary-walking loop — processes them as a sequence of stack traces over time. Magic-trace's trace writer, which doesn't know or care about the source, turns these into the same kind of nested duration events it produces from P-T data.

The result is a usable trace, but with important differences. It's statistical rather than complete. Functions shorter than a hundred microseconds tend to be invisible. You can't see exactly when a branch was taken; you can only see what was on the stack at the sample points.

Why use sampling at all? Two reasons. First, not every machine supports P-T. Cloud VMs usually don't. Older generations of Intel don't. A-M-D machines never will. Magic-trace auto-detects and falls back, so it still produces something useful in those environments.

Second, sometimes the overhead of P-T tracing is itself a problem. If you're tracing something extremely memory-bandwidth-sensitive, the small but nonzero cost of P-T packet emission might be unacceptable. Sampling is cheaper because it only pays overhead at sample points, not continuously.

Magic-trace's collection-mode flag defaults to P-T with a silent fallback. You can force sampling with dash-sampling. In either mode, the rest of the pipeline — trigger mechanism, snapshot semantics, trace-writer, output file — is identical.

Up next: the timer resolution flag, explained through the timing packets we've discussed.

---

## 78. Timer resolution — low, normal, and high

**Overview.** The timer-resolution flag selects how much timing information the tracing hardware emits. Low emits only TSC anchors; Normal adds cycle-accurate packets for nanosecond precision; High also disables return compression for extra robustness. Each level increases the byte rate.

**Detailed.** Timer resolution is a knob that balances precision against cost. Let me walk through the three preset levels.

Low means the tracing hardware emits only the basic timing packets — primarily T-S-C anchors. You get about microsecond-level resolution on events. M-T-C and C-Y-C are off. This mode produces the smallest traces and the lowest byte rate, so it's the best choice if you're hitting overflow errors or capturing long windows. The price is coarser timestamps.

Normal, the default, enables M-T-C at its finest supported period and enables C-Y-C with a threshold of one. You get roughly ten-to-forty-nanosecond resolution — the famous "forty-nanosecond" claim. The byte rate roughly doubles compared to Low. Most users want Normal.

High is Normal with one extra setting: noretcomp equals one. That disables return compression in the hardware, so every return emits a T-I-P. The decoder doesn't depend on a shadow-stack protocol to reconstruct returns. Traces of code with unusual stack manipulation — garbage collectors, exception-heavy code, coroutines — become more robust. The byte rate increases slightly more than Normal.

There's also a Custom setting that lets you specify individual knobs — cyc, cyc-thresh, mtc, mtc-period, noretcomp, psb-period — as their own sexp fields. This is for experts who know exactly what they want from the hardware.

And there's a Sample setting, but it's only valid with dash-sampling; it specifies the sampling frequency in hertz. A slightly awkward overload of the same flag, but convenient.

The general rule for choosing: start with Normal. If you're hitting overflow, try Low. If you're debugging code with exotic control flow and seeing inconsistencies, try High. Custom is for when you've read the Intel manual and know precisely which M-S-R bits you want.

Up next: symbol selection and the fuzzy-find picker.

---

## 79. Symbol selection and the fuzzy picker

**Overview.** When you pass a question mark to magic-trace's trigger flag, it opens a fuzzy picker that lets you search through all symbols in the target binary. The picker is implemented via f-z-f, an external command-line tool. Magic-trace supports picking functions, file-line pairs, or both.

**Detailed.** Magic-trace's trigger syntax accepts several forms. A literal symbol name picks that symbol. A dot is shorthand for magic-underscore-trace-underscore-stop-underscore-indicator, the canonical empty function you leave in instrumented code. A question mark, or variants like line-colon-question or symbol-colon-question, opens a fuzzy picker.

The picker is backed by f-z-f, the widely-used fuzzy finder. It's external to magic-trace — the tool must be in your path. If f-z-f isn't available, magic-trace tells you so and falls back to requiring an explicit symbol.

When you pick bare question mark, magic-trace shows all symbols in the binary. When you pick symbol-colon-question, only function symbols. When you pick line-colon-question, file-and-line pairs derived from D-W-A-R-F info. Each of these maps to a different input set passed to f-z-f.

There's a further option: demangling. Mangled names, especially OCaml ones, are hard to search for. Magic-trace has a flag that runs each symbol through the demangler before showing it to f-z-f, with a mapping back so that when you pick a demangled name, the mangled one gets passed downstream. Set a specific environment variable to enable this.

Similarly, for the attach subcommand with no P-I-D given, magic-trace uses f-z-f to pick among running processes. It lists them from slash-proc, passes the list through f-z-f, and takes the P-I-D you pick.

The user experience is that you type question mark, pick with f-z-f, and off it goes. Simple workflow, especially if you don't remember exact symbol names.

Up next: the stop-indicator pattern, a specific instrumentation idiom.

---

## 80. The magic-trace stop indicator

**Overview.** A convention in magic-trace-aware code is to define a function called magic-underscore-trace-underscore-stop-underscore-indicator that does nothing, and to call it at interesting moments. Magic-trace's dash-trigger dot is a shorthand that triggers on that function. It's the idiomatic way to mark "snapshot here" in production code.

**Detailed.** Sometimes you know exactly where in your code you want a snapshot to fire. "When my server takes more than five hundred milliseconds to handle a request, let me see the last ten milliseconds of execution." "After the garbage collector runs." "When a specific error condition is hit."

The pattern is: define an empty function with a distinctive name, and call it at those points. Magic-trace recognizes the convention, lets you trigger on that function without typing its name, and you leave the function in production code.

The conventional name is magic-underscore-trace-underscore-stop-underscore-indicator. Magic-trace's dash-trigger equals dot syntax is shorthand for triggering on that name. The function itself does nothing — just a return instruction.

Why leave it in production code? Two reasons. First, the cost is near-zero when magic-trace isn't attached — calling a function that does nothing is a few nanoseconds. Second, when you need to debug something in production, magic-trace can attach and fire on the indicator without requiring a code change. The indicator is your preinstalled tracepoint.

Magic-trace's library — the O-Caml package — provides a ready-made definition of the indicator, plus a corresponding C-stubs binding if you're calling it from C. You link against it, reference it somewhere in your code, and magic-trace can find it by name.

When you trace a production process this way, the cost is exactly what you'd expect. Until magic-trace attaches, the indicator is a free no-op. When magic-trace attaches and arms a breakpoint on it, each hit costs roughly eight microseconds — enough that you wouldn't want it in a tight inner loop, but fine for per-request hooks.

The feature is named and designed by the Jane Street engineers who built magic-trace. It's become the standard way their code gets instrumented for ad-hoc analysis.

Up next: multi-snapshot mode and its tradeoffs.

---

## 81. Multi-snapshot mode

**Overview.** By default, magic-trace takes one snapshot per run. The dash-multi-snapshot flag disables that behavior, so every trigger hit creates a new snapshot. Useful for capturing recurring events but comes with real costs: per-trigger overhead and ever-growing trace files.

**Detailed.** The single-snapshot default exists for two reasons. First, breakpoint safety — a mistakenly chosen trigger that fires millions of times per second would otherwise incur eight-microsecond overhead per fire, visibly slowing the target. Single-hit mode disarms the breakpoint after its first fire. Second, trace file size — each snapshot adds to the output, and you probably only care about one specific event.

Multi-snapshot mode disables both of these safeguards. Every trigger hit captures another snapshot. The trace file grows linearly with the number of hits.

When does this make sense? When the trigger fires rarely but each firing is interesting. Examples: a garbage collector running every so often; a specific network event; an error handler; a periodic audit function. If the trigger fires, say, a few dozen times per session, multi-snapshot captures each occurrence and you can compare them.

When it doesn't make sense: when the trigger fires frequently. Each snapshot has fixed overhead — a few milliseconds to dump and decode. A trigger that fires ten thousand times a second with multi-snapshot on will destroy your target's performance and produce a useless mega-trace that probably can't even be opened in the viewer.

Magic-trace doesn't protect you from this. It trusts you to know what your trigger fires on and set multi-snapshot only when appropriate. The warning in the flag's help text is direct: there's an eight-microsecond performance hit per trigger hit, and the trace file grows linearly.

When the tool does produce a multi-snapshot trace, magic-trace's trace writer handles the multiple snapshots gracefully — it clears its internal state between them, so call stacks from one snapshot don't leak into the next. In the viewer, you see them as separate clustered regions on the timeline.

Up next: how the trace writer rebuilds call stacks from a stream of branches.

---

## 82. Rebuilding call stacks from a branch stream

**Overview.** Given a stream of call events, return events, and jumps, the trace writer maintains a stack of live frames per thread. Pushing on call, popping on return. This is the simplest part of reconstruction, and it's the one that makes the whole thing look like a traditional call-tree view.

**Detailed.** Each thread gets its own data structure in the trace writer, tracking its current call stack and a few other pieces of state. The call stack is a stack of frames, each frame holding an address, a symbol, and a start time. When a call event arrives, push a new frame. When a return event arrives, pop the top frame and compute its duration from its start time to the return's time.

This is exactly how a traditional profiler presents a call tree: functions nested inside functions, each with a start and an end. The flame-chart visualization you see in the viewer is a direct reflection of this stack-over-time reconstruction.

A few edge cases keep it from being trivial. What if you see a return but the stack is empty? That means the trace started mid-execution and you returned out of a function whose call was before the snapshot began. The trace writer emits a special "return from untraced" event, leaving the root of the stack in a valid state.

What if you see a call but the top of the stack is already the function being called? That's usually a self-recursive call. Push another frame on top; that's correct.

What if the top of the stack doesn't match where the current instruction pointer says you are? That's the tail-call situation, which we'll cover separately in the next entry.

What if an interrupt fires in the middle of a function? The trace writer saves the current stack, starts a fresh stack for the interrupt handler, and switches back when the interrupt returns. This is the "stack of stacks" concept — interrupts run on their own stacks and don't mix with user code.

What if a thread ends, or the trace switches to a new snapshot? The trace writer flushes all open frames with their end times, resets, and starts over.

The whole reconstruction is deterministic — given the same branch stream, you always get the same call tree. That's the invariant that makes magic-trace's output reliable.

Up next: the tail-call repair that keeps the stack honest.

---

## 83. Tail-call repair

**Overview.** When a function tail-calls another function, the assembly typically doesn't emit a regular call — it emits a jump, and the stack frame is reused. From a tracer's perspective, this looks like control is now in function B while the stack still says A is on top. The trace writer has to detect this and patch it up.

**Detailed.** Let's build intuition. In straightforward code, when function A calls function B, the compiler emits a call instruction, which pushes a return address and jumps. B runs. When B returns, it pops the address and control goes back to A. Traces show this cleanly: a call event putting B on top of A in the stack, then a return event taking B off.

A tail call is an optimization. If function A does nothing after its call to B except return, the compiler can emit a jump to B instead of a call. A's stack frame gets reused by B. When B returns, it goes straight back to whoever called A. This saves a stack frame and sometimes a call instruction.

From the tracer's perspective, the sequence is: A is on top of the stack. A jump event happens. Now control is in B — the instruction pointer is inside B — but the stack still says A. That's wrong; the stack is now stale.

Magic-trace's trace writer handles this with a function called check-current-symbol. It runs after any event that could cause stack-instruction-pointer mismatch. If the I-P's symbol is not the same as the top-of-stack symbol, it synthesizes a fix: emit a return for A, then emit a call to B. The stack is now consistent. The fix happens at the same timestamp, so it doesn't distort the timing of either function.

This is essentially a heuristic. The trace writer doesn't know for certain that the jump was a tail call as opposed to some other weird jump. But in practice, jumps that change symbols almost always are tail calls, and the heuristic produces correct-looking stacks.

For users, the effect is that tail calls render as normal call-return pairs in the viewer. You don't see the jump directly. You see a proper stack frame for the tail-called function, with the right duration. The fact that it was a tail call is hidden from you, which is usually what you want.

Up next: pending events and time smearing.

---

## 84. Pending events and time smearing

**Overview.** Multiple events often share the same timestamp because the tracing hardware can only provide timing at certain resolutions. If you emitted them all at the identical time, their duration events would collapse to zero. Magic-trace buffers events at the same timestamp and spreads them evenly across the available nanosecond range.

**Detailed.** Intel Processor Trace timestamps events with nanosecond precision, but the timestamps aren't always unique. Multiple events can get the same timestamp because they happened inside the same cycle window, and the hardware didn't update its cycle counter between them.

If the trace writer emits these events one after another with identical timestamps, the duration events derived from them are all zero — start and end at the same moment. Perfetto will render them as infinitely thin bars you can't see or click.

Magic-trace fixes this with a time-smearing approach. As events come in, the trace writer buffers any events that share the current pending timestamp. When the next distinct timestamp arrives, it flushes the buffered events by spreading them evenly across the elapsed time.

The arithmetic is straightforward. Count the buffered events that consume time — calls, returns, and similar. Compute the total nanoseconds between the buffer's start time and the new timestamp. Give each event an equal share of those nanoseconds.

The result is a small illusion: events that "really" happened at the same moment are displayed as happening at evenly-spaced sub-moments. The illusion is harmless — the total duration is correct, and the order matches the true event order. The only lie is that the exact sub-nanosecond placement is artificial.

Without this trick, fast sequences of events would be unreadable in the viewer — collapsed lumps you couldn't interact with. With it, you get visible spans that you can click on and measure.

Users never need to think about this. It happens inside the trace writer; the output just looks reasonable.

Up next: the untraced frame, which we've mentioned but can now describe properly.

---

## 85. The untraced frame

**Overview.** When Intel P-T loses coverage — a system call, an interrupt-return, a scheduled-off window — the trace writer pushes a synthetic frame named left-square-untraced-right-square onto the call stack. You see it in the viewer as a pink band. It represents "time passed here but we don't know what happened."

**Detailed.** Recall the P-G-D packet. When tracing turns off, the tracing hardware emits one. When it turns back on, it emits P-G-E. In perf's text output, these appear as tr-end and tr-strt lines. The trace writer reacts to them specifically.

When a tr-end event arrives, the trace writer pushes a synthetic location called untraced onto the current thread's call stack. The address is zero; the symbol is the literal string "left-square-bracket untraced right-square-bracket." That frame stays on the stack until something pops it.

When a tr-strt event arrives, the trace writer typically pops the untraced frame — tracing resumed at the top of the previously-live function, so the stack should return to its earlier state.

The effect is that any gap in tracing becomes a visible frame. You see a call stack that includes a row with "left-square untraced right-square" in pink, spanning the duration of the gap. That's how the viewer shows "there was five hundred microseconds of execution here that I can't tell you about."

Most commonly, untraced frames correspond to system calls. The target process entered the kernel; tracing was user-only, so it turned off; the syscall did whatever it did; returned; tracing resumed. From your perspective, a big pink bar sitting underneath some user function.

If you enable kernel tracing, you'll see those gaps fill in with actual kernel code. The untraced frames go away, replaced by real syscall-handler frames. That's the pay-off for running as root.

Some untraced frames are harder to get rid of. Context switches — when the scheduler takes your thread off the C-P-U and puts it back later — produce untraced regions that kernel tracing doesn't fully fill in, because the "time elsewhere" is literally other processes running. Those remain pink.

Up next: how the trace writer compresses call stacks to fit in the output file.

---

## 86. Callstack compression

**Overview.** The trace writer annotates events with the full call stack at that moment. Writing the stack verbatim for every event would bloat the trace file. Magic-trace compresses stacks using symbol interning and common-prefix sharing. The compression is lossless — decompression reconstructs every stack exactly.

**Detailed.** Every event in the output file carries contextual info about the call stack at that moment. For a deep stack with twenty frames, naive serialization would put twenty symbol strings per event, and with hundreds of thousands of events, the resulting file would be huge.

Magic-trace has a small compression module that applies two tricks.

First, symbol interning. Every distinct symbol gets a small integer I-D the first time it's seen. Subsequent references use the I-D. A deep stack becomes a list of ten small integers instead of ten full symbol strings. The mapping from I-D to symbol is stored once in the output file.

Second, common-prefix compression. Adjacent stacks often share a deep prefix — functions that call each other repeatedly leave most of the stack unchanged between events. The compressor keeps a "follow table" that, given a symbol I-D, stores the symbol that most commonly comes after it on the stack. When writing a stack, if the follow-table prediction matches the next symbol, the compressor just increments a run-length counter; otherwise it writes the next I-D.

The output format for each stack becomes a list of integer-pairs: an I-D, and a run-length of how many subsequent I-Ds match the follow-table predictions. For a stack fully matching predictions, you write just one pair: the deepest I-D plus a length. For stacks with some deviation, you write multiple pairs.

Magic-trace's compressor is based on a similar design from another Jane Street tool. It's effective for real-world traces, where call patterns are repetitive. File sizes shrink substantially without any loss of information.

The compressor runs inline with the trace writer. Each event consults the interning table and the follow table, updates them, emits the compressed stack. The format is binary, documented by the module's type definitions. Consumers of the output — the Perfetto viewer — know how to decompress.

Up next: decode errors as they appear in the viewer.

---

## 87. Decode errors as visible spans

**Overview.** When the decoder can't make sense of a packet — most commonly because of an overflow — it emits an error rather than an event. Magic-trace's trace writer turns those errors into visible marker events in the trace, so you can see where and when decoding broke. The call stack is cleared at that point, because the writer no longer knows which frames are live.

**Detailed.** Decode errors happen for a few reasons. Overflow packets indicate the hardware dropped data. Corrupt packets indicate something went wrong with the capture. Out-of-sync conditions indicate the decoder got confused about where it was in the binary.

Whatever the cause, the effect in the trace writer is the same. An error event arrives with a message explaining the problem, plus an approximate time. The trace writer emits a duration-instant marker — a zero-width blip — labeled with the error message. In the viewer, you see a sharp vertical line with a readable tooltip.

Then the writer clears the current thread's call stack, because an error means we no longer know what functions are live. Every frame currently on the stack gets popped, each getting an end time at the error moment. From that point forward, the trace rebuilds a fresh stack as new events arrive.

The most common decoding error you'll see is "left-square decode error colon space overflow packet right-square." That's the hardware-overflow case. The mitigation is to increase the buffer size or drop the timer resolution, as we discussed earlier.

Other errors are possible but uncommon. Misaligned packet starts, malformed T-I-Ps, failed symbol lookups — each is its own kind of error event. Most real traces have zero errors. A few might have a handful from brief overflow situations. Heavy overflow, hundreds of errors, means capture went badly wrong and you should rerun with different settings.

The ability to see errors explicitly is one of the reasons magic-trace is useful. Some profilers silently drop bad data; magic-trace tells you where and why, so you know how much to trust each region of the trace.

Up next: OCaml exception tracking, a specific feature of magic-trace's trace writer.

---

## 88. OCaml exception tracking

**Overview.** OCaml programs use exceptions pervasively, and the compiler has its own mechanisms for raising, catching, and unwinding. Magic-trace's trace writer has special logic to track these correctly, using either annotations from the compiler or a heuristic. This is mostly invisible to non-OCaml users.

**Detailed.** Here's the issue. When an OCaml function raises an exception, the stack unwinds in a way that's not a normal return. A specific support function — c-a-m-l-underscore-raise-underscore-exception — manipulates the stack pointer directly, dropping multiple frames at once, and then jumps to the handler. From a tracer's perspective, this looks like a whole bunch of returns happening together, followed by a jump to some arbitrary address.

Without special handling, magic-trace's trace writer would miss the unwinding. The call stack would retain frames that had been jumped out of. Subsequent events would attach to the wrong ancestors.

Magic-trace has two modes for handling this. If the OCaml compiler emitted exception metadata — a table of which instructions can raise which exceptions — magic-trace reads it out of the E-L-F and uses it to unwind the stack precisely. For each exception-raising site, the metadata says how many frames to pop.

If that metadata isn't available, magic-trace falls back to a heuristic. It watches for calls into c-a-m-l-underscore-raise-underscore-exception and, when it sees one, tries to identify the handler and unwind the stack to match.

For non-OCaml users, this is entirely irrelevant. Exception tracking is OCaml-specific and doesn't interact with C, C-plus-plus, or Rust tracing. For OCaml users at Jane Street, where magic-trace originated, it's essential.

The feature is one of the main reasons the direct backend, which can do instruction-level decoding, has been kept alive as reference code. OCaml exception tracking was the original motivation for building it.

Up next: the Fuchsia Trace Format, the format magic-trace writes to disk.

---

## 89. Fuchsia Trace Format

**Overview.** F-X-T, the Fuchsia Trace Format, is a binary format designed by Google for their Fuchsia operating system's tracing facility. Magic-trace writes its output in this format because Perfetto consumes it natively. The file ends in dot-f-x-t, typically with a dot-g-z suffix added for compression.

**Detailed.** Every profiler needs a file format for writing traces to disk. F-X-T is the one magic-trace chose — not because it's famous, but because it's efficient, it's widely consumed by tracing viewers, and it has good properties for the event model magic-trace uses.

F-X-T is a binary format consisting of variable-length records, each starting with a type tag. Record types include things like duration-begin events, duration-end events, counter updates, thread metadata, process metadata, and so on. A trace is a sequence of these records in chronological order.

The Jane Street tracing library ships as a separate subdirectory in magic-trace's source tree. It implements the F-X-T writer: an A-P-I for writing processes, threads, and duration events into a buffer, with internal compression for repeated strings and a streaming-friendly layout.

Perfetto, the viewer Google maintains, can natively open F-X-T files. So can some other tracing tools. The format has a spec — open source, self-describing — that makes it easy to implement.

The alternative formats considered were Chrome's J-S-O-N trace format and various proprietary binary formats. F-X-T won on size — binary is much more compact than J-S-O-N — and on streaming properties — you can write it incrementally without holding the whole trace in memory.

Magic-trace's default output path is trace-dot-f-x-t-dot-gz. You can change it with the output flag. The double extension matters — the first extension identifies the format, the second signals compression.

Up next: how the file gets compressed on the fly.

---

## 90. Gzip and Zstandard compression

**Overview.** Magic-trace picks a compression strategy based on the output filename's suffix. Dot-g-z uses gzip. Dot-z-s-t uses Zstandard. No suffix means uncompressed. This happens transparently inside the trace writer — you pick the filename and the rest is automatic.

**Detailed.** Trace files can get large. A typical magic-trace snapshot might be ten or twenty megabytes of raw F-X-T. That's manageable but annoying to copy around, and compression typically halves the size or better.

The Jane Street tracing-writer library supports two compression formats natively. Gzip is the standard — widely supported, modest compression ratio, slow but not too slow. Zstandard is newer and better — typically two to three times faster at both compression and decompression, with better ratios.

Magic-trace picks between them based on what you named the output file. If the name ends in dot-g-z, gzip. If dot-z-s-t, Zstandard. Otherwise, no compression and the raw bytes go to disk.

The compression is done in a streaming pipeline. The trace writer produces F-X-T records; the compression layer consumes them and emits compressed bytes; the result goes to the file. There's no temporary uncompressed copy — the whole thing runs inline.

For almost all workflows, you want dot-g-z because it's broadly supported. If you're producing very large traces and transfer speed matters, dot-z-s-t is worth considering. The viewer, Perfetto, supports both.

Under the hood, the default file name in magic-trace is trace-dot-f-x-t-dot-g-z, chosen to make gzip the silent default. Users who don't explicitly pass an output flag get gzipped traces.

Up next: the Perfetto viewer itself.

---

## 91. Perfetto, and why magic-trace.org is a fork

**Overview.** Perfetto is Google's tracing system, originally built for Android. Its front-end viewer runs entirely in your browser and can open any F-X-T file. Magic-dash-trace-dot-org is a lightly-modified fork of that viewer — same engine, slightly different branding. Your traces never leave your browser.

**Detailed.** Perfetto is a mature tracing ecosystem. It has a capture side — a daemon called t-r-a-c-e-d — and a viewing side — a web-based U-I built with Web-Assembly and JavaScript. Google uses it extensively for Android performance work and for Chrome tracing.

The interesting part for us is the viewer. It's a browser app that loads a trace file and lets you navigate it with the keyboard and mouse. It handles very large traces — hundreds of megabytes — smoothly, with a virtualized timeline that only renders visible pixels. It has rich measurement tools, search, filtering, and so on.

Because it's entirely client-side — no server, no backend — you can just open it and drag a trace in. The trace never gets uploaded anywhere. Your code, your data, your traces, they all stay in your browser tab.

Jane Street forked the viewer and made a few small modifications for magic-trace's specific needs. Mainly cosmetic — branding, a welcome screen that's more helpful for new users — plus one or two features that bias the default display toward magic-trace-style traces. You can use stock Perfetto if you prefer; it opens the same files.

The fork lives at magic-dash-trace-dot-org. You open a browser, go there, click "open trace file," pick your dot-f-x-t-dot-g-z. The viewer expands it and you're looking at your trace.

Because the whole thing is client-side, you can also host your own copy if you want. The source is available. Some teams run an internal instance for traces that include data they're unwilling to have in browser memory on an external site.

Up next: what the flame-chart in the viewer actually represents.

---

## 92. What the flame-chart shows

**Overview.** The flame-chart is Perfetto's main visualization for trace data. The horizontal axis is time; the vertical axis is call-stack depth. Each colored rectangle is one function call. Reading the chart is reading a time-indexed history of the stack.

**Detailed.** Let me walk through what the chart means, piece by piece. The top of the viewport shows a time axis — maybe from zero nanoseconds to three hundred microseconds. Below that, a sequence of horizontal rows. Each row represents a stack frame — the top row is the outermost function, the second row is whatever the top row called, and so on down.

Within each row, rectangles span ranges of time. A rectangle from one microsecond to five microseconds, in the second row, means "during that period, this function was executing as the second-to-outermost frame on the stack." Its parent in the top row was the function that called it; its children in subsequent rows are functions it called.

When you see a vertical slice — a tall column of rectangles at some moment — you're reading the call stack at that exact point in time. Top to bottom is outermost to innermost.

The colors are arbitrary and carry no semantic meaning. They're hashed from the function name, giving adjacent distinct calls different colors so your eye can tell them apart. Same-colored rectangles mean same function name; different colors just mean different names.

When you zoom in with the keyboard — W zooms in on the cursor position, S zooms out — the rectangles widen to show more detail. Very thin rectangles at the current zoom level might become readable blocks when you zoom further. Magic-trace captures events at nanosecond precision; at the highest zoom you can see individual branches.

When you click a rectangle, a panel at the bottom shows the function name, start time, duration, and any metadata magic-trace attached — file and line if D-W-A-R-F was available, for instance.

Up next: tracks, thread groups, and how the viewer organizes multi-threaded traces.

---

## 93. Tracks and thread groups

**Overview.** The viewer organizes events into tracks — horizontal strips showing one thread's or one category's activity. Tracks are grouped into thread groups that represent processes. For a multi-threaded trace, you see each thread as its own track, stacked vertically, all grouped under the process.

**Detailed.** The flame-chart isn't a single pane. It's a stack of tracks. Each track has its own time axis, synchronized with the others, and contains its own events.

For typical magic-trace output, you get one track per thread. A single-threaded program has one track. A ten-thread program has ten tracks, stacked vertically. They share a time axis, so you can compare what thread A was doing at a given moment to what thread B was doing.

Tracks are grouped. In magic-trace's output, each thread's track goes under a group representing the process. You see a collapsible label at the top showing P-I-D-slash-T-I-D, and below it the tracks for that process's threads.

Some categories have their own tracks separate from the main call-stack tracks. If magic-trace is configured to capture extra events like cache misses or branch misses through sampling, those show up on dedicated counter tracks. Power events — the frequency-change notifications from C-B-R packets — have their own track too, showing C-P-U frequency over time.

The arrangement is useful because performance stories often span threads or event types. Why did thread B wait for so long? You can look down at the same moment on thread A's track and see what it was doing. Was a slow function slow because the C-P-U throttled? Check the power track at the same moment.

You can collapse tracks and groups you don't care about. You can reorder them. The viewer is fairly flexible at presenting the same data many ways.

Up next: the keyboard controls you use to move around.

---

## 94. Zoom, pan, and measurement

**Overview.** The viewer has a specific set of keyboard controls borrowed from Chrome's trace viewer. W zooms in; S zooms out; A and D pan left and right. Scroll wheel moves the viewport vertically through deep stacks. Click and drag measures durations. These are the fundamental navigation tools.

**Detailed.** Perfetto's navigation scheme is W-A-S-D. W zooms in where your cursor is. S zooms out from where your cursor is. A pans left. D pans right. It's the same as movement in many video games and similar to Chrome's built-in trace viewer.

Zooming is crucial because magic-trace captures events at nanosecond resolution but the initial view shows the whole snapshot — typically a few hundred microseconds. Most of what you care about is invisible at the default zoom. Press W a handful of times to get to the scale where individual branches become visible blocks.

Pan with A and D to move left and right in time. Scroll wheel moves the viewport vertically through the call-stack depth — when the stack is deeper than the screen, you need this to see the lower frames.

For measurement, click and drag on the white space between tracks. A time measurement pops up showing the duration of your drag. This is how you answer questions like "how long did this region of work take" without any math.

For flags, click on the time ruler at the top. A flag drops at that position. Flags persist as you pan and zoom — you can use them as landmarks for comparison.

Clicking a specific event rectangle selects it. The bottom panel shows its details — function name, duration, metadata. Shift-click adds to a selection for comparing.

There's a shortcut sheet under the keyboard icon in the viewer's side panel. It lists everything. If you use the viewer regularly, the shortcuts become second nature. If not, you can always mouse-navigate, it just takes a bit longer.

Up next: why virtual machines usually can't use magic-trace.

---

## 95. Why virtual machines usually can't use P-T

**Overview.** Intel Processor Trace depends on privileged C-P-U instructions and M-S-Rs that, in a virtualized environment, the hypervisor has to pass through to the guest. For various reasons — complexity, security, compatibility — most hypervisors don't. Magic-trace silently falls back to sampling mode in those environments.

**Detailed.** In a virtual machine, the guest operating system thinks it's running directly on hardware, but a hypervisor sits underneath trapping and emulating certain privileged operations. M-S-R writes are one of the things hypervisors have to handle specifically — the guest's M-S-R write might need to go through to real hardware, or get emulated, or get silently ignored.

Intel P-T requires writing several M-S-Rs to configure and enable tracing. For this to work in a V-M, the hypervisor has to cooperate. It has to present the P-T feature to the guest, pass through the writes correctly, and ensure the resulting packet stream lands in memory the guest can read.

Historically, this was barely supported. K-V-M, the Linux hypervisor, got usable P-T support around kernel five-point-ten. Before that, you could enable the feature bit but it wouldn't actually emit packets. Most public cloud images — AWS, GCP, Azure — run on older kernel revs or deliberately disable P-T for security or compatibility reasons.

The net effect is that if you try to use magic-trace in a typical cloud VM, the capability probe finds no P-T support. Magic-trace prints a message saying "Intel P-T support not found, will use sampling instead" and proceeds with the sampling backend.

The trace you get from sampling is still usable, but qualitatively different. You won't see branch-by-branch detail. Short functions will be invisible. The power of P-T — retrospective full-trace at low overhead — is gone.

The workaround, if P-T matters, is to trace on bare metal. A dedicated Linux host, a test bench, your development laptop if it's Intel. Once you have a trace, you can share it — the viewing works anywhere, including from a V-M.

Up next: self-modifying code, the other big decoder gotcha.

---

## 96. Self-modifying code

**Overview.** If a program rewrites its own instructions after loading — as some J-I-T compilers and runtime-patching systems do — the decoder reading the on-disk binary will see different bytes than the C-P-U saw. Every branch decision after the modification is then likely to be wrong. There's no clean solution; magic-trace minimizes the risk by decoding right after capture.

**Detailed.** Recall the decoder invariant: the binary it reads must match what the C-P-U executed. Self-modifying code breaks that. The program loaded from disk with one set of instructions, then at runtime patched them to be different, and the C-P-U executed the patched version. The decoder, reading the disk, sees the unpatched version. Each patched instruction is read wrong.

In practice, pure self-modifying code is rare. Most mainstream code doesn't do this. When it does appear, it's in specific contexts. Some J-I-Ts do tier-up by patching call sites when a function becomes hot. Some runtime tools rewrite specific instructions for observability or patching. A handful of low-level libraries do targeted patches for C-P-U feature dispatch.

If you're tracing one of these systems, you may see decoded output that just looks wrong — branches leading to nonsense addresses, call stacks with wrong frames. If you see this, suspect self-modifying code.

Magic-trace mitigates the risk, but doesn't eliminate it. The decode runs immediately after capture, with the target process still alive. The binary on disk is the one that was most recently loaded. If the process rebuilds a binary during its run, the decoder might still see the wrong version.

The only real fix would be to capture instruction bytes at trace time and carry them along for decode. Intel P-T doesn't offer this, and retrofitting it would be complicated. So self-modifying code remains a limitation.

Most users never hit this. If you're working with a J-I-T or a system that does runtime patching, and you see weird output, this is probably why.

Up next: the specific case of the virtual dynamic shared object.

---

## 97. The v-D-S-O problem

**Overview.** The virtual dynamic shared object, or v-D-S-O, is a page of code the kernel maps into every process to provide fast implementations of a handful of system calls. It has no on-disk file. The default backend handles it via perf's built-in v-D-S-O table. The direct backend doesn't, and that's a notable limitation.

**Detailed.** Linux programs often call functions like clock-get-time or get-p-i-d. On modern Linux, these don't actually enter the kernel — the kernel maps a small page of user-mode code into every process, and the C standard library calls into that page instead. The page contains optimized implementations that can read the system clock or process I-D directly without a ring transition.

This page is the v-D-S-O. It's a real piece of code executing in ring three, but it's not backed by any file on disk. The kernel generates it at boot and maps it in.

For a decoder, this creates a problem. The decoder wants to read instruction bytes from a file to disassemble them. The v-D-S-O has no file; it only exists in memory. If the decoder sees a branch into v-D-S-O territory, it doesn't know what instructions are there.

The default path in magic-trace handles this automatically because perf does. Perf has built-in knowledge of the v-D-S-O and can provide its contents to the decoder on request.

The direct backend doesn't yet. Its readme candidly documents this limitation: when a v-D-S-O syscall happens during a trace, the decoder encounters a gap and emits a decode error. That's partly why the direct backend isn't the default.

If you're tracing a program that does lots of fast clock or time lookups and you see periodic decode errors every few milliseconds, v-D-S-O is a likely culprit — though usually only if you're somehow using the direct backend.

Up next: how to spot and mitigate overflow in practice.

---

## 98. Overflow in practice

**Overview.** Overflow is the most common cause of visible decode errors in magic-trace output. Spotting it is easy — you see events labeled decode-error with the message Overflow packet. Mitigation is a small set of knobs: bigger buffer, lower timer resolution, narrower filter, or accept that some regions will be lossy.

**Detailed.** We've covered what overflow is — the hardware fills faster than memory drains. Let's be practical about what to do when you see one.

First, recognize it. In the viewer, you'll see zero-width marker events labeled something like "decode error colon overflow packet." They're vertical lines with tooltips. If there are one or two, they mark isolated incidents. If there are dozens, your trace has real problems.

Second, understand where they came from. The overflow happened because the tracing unit couldn't keep up. Common root causes: very high branch rates in the target code, tight loops producing huge amounts of T-N-T packets; memory-subsystem contention from other processes; buffer size too small for the workload.

Third, try mitigations in order of effort.

The lowest-effort mitigation is increasing buffer size with the dash-m flag. Pass a larger value — say, sixteen megabytes — if you're root. This gives D-R-A-M more slack before the on-chip F-I-F-O backs up.

Next, drop the timer resolution. Pass dash-timer-resolution Low. This turns off cycle-accurate packets, which typically halves the byte rate. You lose the forty-nanosecond resolution but you might gain overflow-free traces.

If the workload is fundamentally too busy, consider narrowing your trigger. If you only care about a specific rare event, trigger on it specifically and capture a much smaller window right around it.

If all else fails, switch to sampling mode. You lose P-T's per-branch fidelity but you don't have overflow issues — sampling only pays overhead at sample points.

In practice, the vast majority of overflow cases are solved by bumping buffer size. Timer-resolution drops are for the stubborn cases.

Up next: when to fall back to sampling as a deliberate choice.

---

## 99. When to fall back to sampling

**Overview.** Magic-trace's default is Intel P-T, and that's the right choice when it works. Sometimes you should deliberately choose sampling anyway — when you want longer capture windows, when overflow is unavoidable, when overhead must be minimized, or when you're on hardware that doesn't support P-T.

**Detailed.** P-T is the star feature, but sampling has its own niche. Let me describe when to reach for it.

First, when P-T isn't available. On A-R-M systems, A-M-D systems, virtual machines, older Intel chips — magic-trace falls back to sampling automatically, but you can also force it with dash-sampling to be explicit.

Second, when you want a long capture window. P-T's ring buffer is bounded and typically holds ten milliseconds or so. Sampling can run for minutes, accumulating a statistical picture of an entire workload. If you want to know "where is my web server spending time over five minutes of traffic" — that's a sampling question, not a P-T question.

Third, when the workload's branch rate is too high for P-T. If you can't get an overflow-free trace even with maxed-out buffers and Low timer resolution, sampling gives you something usable.

Fourth, when overhead must be minimized. P-T is low overhead — between two and ten percent — but not zero. Sampling can be as low as a fraction of a percent if you set the sample rate low. For deeply performance-sensitive measurements where even a few percent matters, sampling is the right choice.

The trade-off is well-known: you lose completeness. Functions shorter than your sample interval are invisible. You can't see exactly what happened leading up to a specific moment. You can only see statistical patterns.

If you're using sampling, consider the callgraph-mode flag we covered earlier. L-B-R-based callgraphs are usually best — low overhead, decent depth. Frame-pointer callgraphs are fine if your binary has frame pointers. D-W-A-R-F is a last resort because it's slow.

Magic-trace unifies the output: whether you used P-T or sampling, you get the same kind of F-X-T trace file, openable in the same viewer. The shape of the chart just looks different — sampling mode gives you fewer, coarser duration events.

Up next: limits on the viewer side, when traces get too big.

---

## 100. Huge traces and viewer limits

**Overview.** Traces over a few hundred megabytes start becoming painful to open. The browser-based viewer runs out of memory or stalls on very large files. Magic-trace doesn't limit you, but practical wisdom is to keep your snapshot windows modest and to avoid multi-snapshot mode unless you really need it.

**Detailed.** The Perfetto viewer is impressive at handling large traces, but it's still a browser app. Its memory is bounded by what the browser lets a tab have, typically a couple of gigabytes. Its performance is bounded by single-threaded JavaScript.

A normal magic-trace snapshot is maybe ten or twenty megabytes compressed, fifty or a hundred uncompressed. The viewer loads those in a couple of seconds and handles them smoothly.

A multi-snapshot trace that captured fifty separate windows might be a gigabyte. The viewer can technically load that, but you're in the territory where it may take many seconds to open, and scrolling or zooming may be noticeably slow.

A kernel-tracing run on a busy system for several seconds could produce multiple gigabytes. This might simply fail to open.

Practical wisdom. If you're exploring, take single snapshots and look at them individually. If you need to capture multiple events, save each to its own file and open them separately. Use dash-working-directory to make magic-trace not delete intermediate files, so you can rerun decoding on specific events.

If you absolutely need to open a huge trace, you can download Perfetto itself and run it natively on your desktop — the native version has fewer memory constraints than the browser version. Alternatively, you can host Perfetto locally with a Node-based server and point Chrome at it; that also typically handles larger files than the hosted version.

And that's the end. Over a hundred entries, we've built up from "what does a C-P-U do with one instruction" all the way to "what does the Perfetto viewer do with a two-hundred-megabyte trace file." Every piece of magic-trace you can configure has, somewhere in this primer, a reason rooted in how the hardware or the kernel or the decoder actually works. When you look at a trace or configure a run from here on, you'll have a mental model that goes all the way down. Good luck.

