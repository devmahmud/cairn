// Cairn frontend — the typewriter buffer (BLUEPRINT.md §4.2, §8 step 8).
//
// Framework-agnostic (no React/Zustand here -- `stores/chat-store.ts` is the
// one place this gets wired to state updates). Drains an ordered queue of
// text chunks and artifact markers at a target chars/sec, rAF-driven:
//
// - **Latency-bounded**: once the undelivered backlog exceeds `maxLagChars`,
//   the per-tick reveal budget grows by the overage, so a burst of tokens
//   can't leave the visible text arbitrarily far behind the network.
// - **Visibility-aware**: `document.hidden` (checked at push-time, at tick
//   time, and reactively via a `visibilitychange` listener -- rAF callbacks
//   are throttled or fully paused in background tabs, so *only* checking
//   inside `tick` would miss a tab that goes hidden between one scheduled
//   frame and the next) bypasses the metered loop entirely: everything
//   queued is flushed synchronously, and every push after that is emitted
//   immediately rather than enqueued, until the tab is visible again.
// - **Ordered artifact deferral**: an artifact marker only reaches the front
//   of the queue once every text chunk queued ahead of it has been fully
//   revealed -- "hold a `tool_result` card until its parent text finishes
//   typing" falls out of plain FIFO queue order, no separate bookkeeping.
// - **`prefers-reduced-motion`**: same bypass path as a hidden tab -- render
//   immediately, no animation.

export interface TypewriterOptions {
  charsPerSecond?: number;
  maxLagChars?: number;
  reducedMotion?: boolean;
}

export interface TypewriterCallbacks {
  onTextRevealed(chunk: string): void;
  onArtifactReleased(id: string): void;
  onIdle?(): void;
}

type QueueItem = { kind: "text"; text: string } | { kind: "artifact"; id: string };

const DEFAULT_CPS = 45;
const DEFAULT_MAX_LAG_CHARS = 240;
const DEFAULT_FRAME_MS = 16;

// Resolved *per call*, not cached at module load: a test suite installs fake
// timers (`vi.useFakeTimers({ toFake: ["requestAnimationFrame", ...] })`)
// well after this module is first imported, which replaces
// `globalThis.requestAnimationFrame` -- binding to the real one up front
// here would silently keep scheduling against a clock the fake-timer API
// never advances.
function raf(cb: (time: number) => void): number {
  if (typeof requestAnimationFrame === "function") return requestAnimationFrame(cb);
  return setTimeout(() => cb(performance.now()), DEFAULT_FRAME_MS) as unknown as number;
}

function caf(handle: number): void {
  if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(handle);
  else clearTimeout(handle);
}

function isHidden(): boolean {
  return typeof document !== "undefined" && document.hidden;
}

export class TypewriterEngine {
  private queue: QueueItem[] = [];
  private carry = 0;
  private frameHandle: number | null = null;
  private lastTickAt: number | null = null;
  private disposed = false;
  private reducedMotion: boolean;
  private readonly cps: number;
  private readonly maxLagChars: number;
  private readonly callbacks: TypewriterCallbacks;
  private readonly handleVisibilityChange = (): void => {
    if (isHidden()) this.flushAll();
  };

  constructor(callbacks: TypewriterCallbacks, options: TypewriterOptions = {}) {
    this.callbacks = callbacks;
    this.cps = options.charsPerSecond ?? DEFAULT_CPS;
    this.maxLagChars = options.maxLagChars ?? DEFAULT_MAX_LAG_CHARS;
    this.reducedMotion = options.reducedMotion ?? false;
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", this.handleVisibilityChange);
    }
  }

  setReducedMotion(value: boolean): void {
    this.reducedMotion = value;
    if (value) this.flushAll();
  }

  pushText(text: string): void {
    if (!text) return;
    if (this.shouldBypass()) {
      this.callbacks.onTextRevealed(text);
      return;
    }
    this.queue.push({ kind: "text", text });
    this.ensureScheduled();
  }

  pushArtifact(id: string): void {
    if (this.shouldBypass()) {
      this.callbacks.onArtifactReleased(id);
      return;
    }
    this.queue.push({ kind: "artifact", id });
    this.ensureScheduled();
  }

  /** Everything still queued is emitted immediately, in order -- used when a
   * turn ends so the visible transcript always converges on the final text,
   * however far typing had gotten. */
  finalize(): void {
    this.flushAll();
  }

  dispose(): void {
    this.disposed = true;
    this.cancelScheduled();
    if (typeof document !== "undefined") {
      document.removeEventListener("visibilitychange", this.handleVisibilityChange);
    }
  }

  hasPending(): boolean {
    return this.queue.length > 0;
  }

  private shouldBypass(): boolean {
    return this.reducedMotion || isHidden();
  }

  private ensureScheduled(): void {
    if (this.disposed || this.frameHandle !== null) return;
    if (this.shouldBypass()) {
      this.flushAll();
      return;
    }
    this.lastTickAt = null;
    this.frameHandle = raf(this.tick);
  }

  private cancelScheduled(): void {
    if (this.frameHandle !== null) {
      caf(this.frameHandle);
      this.frameHandle = null;
    }
  }

  private readonly tick = (): void => {
    this.frameHandle = null;
    if (this.disposed) return;
    if (this.shouldBypass()) {
      this.flushAll();
      return;
    }

    const now = performance.now();
    const elapsedMs = this.lastTickAt === null ? DEFAULT_FRAME_MS : now - this.lastTickAt;
    this.lastTickAt = now;

    const overLag = Math.max(0, this.pendingCharCount() - this.maxLagChars);
    const budget = (this.cps * elapsedMs) / 1000 + this.carry + overLag;
    this.carry = budget - Math.floor(budget);
    let charsToReveal = Math.floor(budget);

    // Artifacts drain for free whenever they reach the front -- only text
    // consumption is metered against `charsToReveal`, so a tick with zero
    // character budget left can still release an artifact queued right
    // after the text that just finished revealing.
    while (this.queue.length > 0) {
      const front = this.queue[0];
      if (!front) break;
      if (front.kind === "artifact") {
        this.queue.shift();
        this.callbacks.onArtifactReleased(front.id);
        continue;
      }
      if (charsToReveal <= 0) break;
      const take = Math.min(charsToReveal, front.text.length);
      this.callbacks.onTextRevealed(front.text.slice(0, take));
      front.text = front.text.slice(take);
      charsToReveal -= take;
      if (front.text.length === 0) this.queue.shift();
    }

    if (this.queue.length > 0) {
      this.frameHandle = raf(this.tick);
    } else {
      this.callbacks.onIdle?.();
    }
  };

  private pendingCharCount(): number {
    let total = 0;
    for (const item of this.queue) if (item.kind === "text") total += item.text.length;
    return total;
  }

  private flushAll(): void {
    this.cancelScheduled();
    const pending = this.queue;
    this.queue = [];
    for (const item of pending) {
      if (item.kind === "text") this.callbacks.onTextRevealed(item.text);
      else this.callbacks.onArtifactReleased(item.id);
    }
    this.callbacks.onIdle?.();
  }
}
