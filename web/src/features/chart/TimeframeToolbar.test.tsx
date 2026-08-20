import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TimeframeToolbar } from "./TimeframeToolbar";

it("提供 5/15/30/60 分钟、日线、周线和月线", async () => {
  const selected: string[] = [];
  render(<TimeframeToolbar value="1d" onChange={(value) => selected.push(value)} />);

  for (const label of ["5分", "15分", "30分", "60分", "日", "周", "月"]) {
    expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
  }
  await userEvent.click(screen.getByRole("button", { name: "15分" }));
  expect(selected).toEqual(["15m"]);
});
