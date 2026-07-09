import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useVerdictStream } from "./useVerdictStream";
import { decidableVerdict } from "./test-fixtures";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
    this.onclose?.();
  }

  emitOpen(): void {
    this.onopen?.();
  }

  emitMessage(data: unknown): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }
}

describe("useVerdictStream", () => {
  const originalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    FakeWebSocket.instances = [];
    // @ts-expect-error -- test double replaces the real WebSocket global
    globalThis.WebSocket = FakeWebSocket;
  });

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket;
  });

  it("connects to the given URL and starts in the connecting state", () => {
    const { result } = renderHook(() =>
      useVerdictStream("sess_1", "ws://test/sessions/sess_1/stream")
    );
    expect(result.current.connectionState).toBe("connecting");
    expect(FakeWebSocket.instances[0]?.url).toBe("ws://test/sessions/sess_1/stream");
  });

  it("transitions to open and stores the verdict + history on message", () => {
    const { result } = renderHook(() =>
      useVerdictStream("sess_1", "ws://test/sessions/sess_1/stream")
    );
    const socket = FakeWebSocket.instances[0];

    act(() => socket.emitOpen());
    expect(result.current.connectionState).toBe("open");

    act(() => socket.emitMessage(decidableVerdict));
    expect(result.current.verdict).toEqual(decidableVerdict);
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0].P1).toBe(0.97);
  });

  it("transitions to closed on close", () => {
    const { result } = renderHook(() =>
      useVerdictStream("sess_1", "ws://test/sessions/sess_1/stream")
    );
    const socket = FakeWebSocket.instances[0];
    act(() => socket.close());
    expect(result.current.connectionState).toBe("closed");
  });
});
