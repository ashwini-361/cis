import "@testing-library/jest-dom/vitest";

// jsdom does not implement ResizeObserver, but Recharts' ResponsiveContainer
// needs it to measure its container. Provide a minimal stub for tests.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver =
  globalThis.ResizeObserver ?? (ResizeObserverStub as unknown as typeof ResizeObserver);
