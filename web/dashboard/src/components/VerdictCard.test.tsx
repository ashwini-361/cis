import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VerdictCard } from "./VerdictCard";
import { decidableVerdict, notDecidingVerdict } from "../test-fixtures";

describe("VerdictCard", () => {
  it("shows a waiting state when no verdict has arrived yet", () => {
    render(<VerdictCard verdict={null} />);
    expect(screen.getByText(/waiting for verdict/i)).toBeInTheDocument();
  });

  it("shows the candidate name and confidence when decidable", () => {
    render(<VerdictCard verdict={decidableVerdict} />);
    expect(screen.getByText(/candidate: ashwini/i)).toBeInTheDocument();
    expect(screen.getByText("97% confidence")).toBeInTheDocument();
  });

  it("shows a still-deciding state with the reason when not decidable", () => {
    render(<VerdictCard verdict={notDecidingVerdict} />);
    expect(screen.getByText(/still deciding/i)).toBeInTheDocument();
    expect(screen.getByText(/top confidence 0.42 < threshold 0.55/i)).toBeInTheDocument();
  });
});
