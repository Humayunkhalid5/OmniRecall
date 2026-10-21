import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("renders the shell", () => {
  render(<App />);
  expect(screen.getByText("OmniRecall")).toBeInTheDocument();
});
