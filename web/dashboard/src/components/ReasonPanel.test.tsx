import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReasonPanel } from "./ReasonPanel";
import { decidableVerdict, notDecidingVerdict } from "../test-fixtures";

describe("ReasonPanel", () => {
  it("renders nothing when no verdict has arrived yet", () => {
    const { container } = render(<ReasonPanel verdict={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the reasons as a bullet list", () => {
    render(<ReasonPanel verdict={decidableVerdict} />);
    expect(screen.getByText(/email matched calendar metadata/i)).toBeInTheDocument();
    expect(screen.getByText(/joined first/i)).toBeInTheDocument();
  });

  it("renders rejected hypotheses when present", () => {
    render(<ReasonPanel verdict={decidableVerdict} />);
    expect(screen.getByText(/priya sharma/i)).toBeInTheDocument();
    expect(screen.getByText(/transcript role strongly indicates interviewer/i)).toBeInTheDocument();
  });

  it("omits the rejected-hypotheses section when there are none", () => {
    render(<ReasonPanel verdict={notDecidingVerdict} />);
    expect(screen.queryByText(/rejected hypotheses/i)).not.toBeInTheDocument();
  });
});
