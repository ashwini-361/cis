import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TimelineChart } from "./TimelineChart";
import type { ConfidencePoint } from "../useVerdictStream";

describe("TimelineChart", () => {
  it("shows a placeholder when there is no history yet", () => {
    render(<TimelineChart history={[]} />);
    expect(screen.getByText(/no data yet/i)).toBeInTheDocument();
  });

  it("renders a chart container once history points exist", () => {
    const history: ConfidencePoint[] = [
      { ts: 0, P1: 0.2, P3: 0.1 },
      { ts: 5, P1: 0.5, P3: 0.2 },
    ];
    const { container } = render(<TimelineChart history={history} />);
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });
});
