import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TypewriterEngine } from "./typewriter-engine";

function flushRAF(times = 1): void {
  for (let i = 0; i < times; i += 1) {
    vi.advanceTimersToNextFrame();
  }
}

describe("TypewriterEngine", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reveals text over multiple frames rather than all at once", () => {
    let visible = "";
    const engine = new TypewriterEngine(
      { onTextRevealed: (chunk) => (visible += chunk), onArtifactReleased: () => {} },
      { charsPerSecond: 100 },
    );

    engine.pushText("hello world");
    expect(visible).toBe(""); // nothing revealed synchronously on push

    flushRAF(3);
    expect(visible.length).toBeGreaterThan(0);
    expect(visible.length).toBeLessThan("hello world".length);

    flushRAF(20);
    expect(visible).toBe("hello world");
    engine.dispose();
  });

  it("defers an artifact until every text chunk queued ahead of it is fully revealed", () => {
    let visible = "";
    const released: string[] = [];
    const engine = new TypewriterEngine(
      {
        onTextRevealed: (chunk) => (visible += chunk),
        onArtifactReleased: (id) => released.push(id),
      },
      { charsPerSecond: 30 },
    );

    engine.pushText("abc");
    engine.pushArtifact("artifact-1");
    engine.pushText("def");

    // Advance just enough frames to reveal "abc" -- the artifact (queued
    // right after it) releases for free the moment it reaches the front,
    // same tick "abc" finishes, without waiting on any "def" budget.
    while (released.length === 0) flushRAF(1);
    expect(visible).toBe("abc");
    expect(released).toEqual(["artifact-1"]);

    flushRAF(20);
    expect(visible).toBe("abcdef");
    engine.dispose();
  });

  it("flushes everything immediately when the tab is hidden", () => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    let visible = "";
    const released: string[] = [];
    const engine = new TypewriterEngine({
      onTextRevealed: (chunk) => (visible += chunk),
      onArtifactReleased: (id) => released.push(id),
    });

    engine.pushText("background tab text");
    engine.pushArtifact("a1");

    expect(visible).toBe("background tab text");
    expect(released).toEqual(["a1"]);
    engine.dispose();
  });

  it("reduced motion renders text immediately instead of animating", () => {
    let visible = "";
    const engine = new TypewriterEngine(
      { onTextRevealed: (chunk) => (visible += chunk), onArtifactReleased: () => {} },
      { reducedMotion: true },
    );

    engine.pushText("no animation here");
    expect(visible).toBe("no animation here");
    engine.dispose();
  });

  it("finalize flushes any remaining queued text synchronously", () => {
    let visible = "";
    const engine = new TypewriterEngine(
      { onTextRevealed: (chunk) => (visible += chunk), onArtifactReleased: () => {} },
      { charsPerSecond: 5 },
    );

    engine.pushText("a much longer message than one frame reveals");
    flushRAF(1);
    expect(visible.length).toBeLessThan(45);

    engine.finalize();
    expect(visible).toBe("a much longer message than one frame reveals");
    engine.dispose();
  });
});
