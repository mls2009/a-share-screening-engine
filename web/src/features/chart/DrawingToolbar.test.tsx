import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DrawingToolbar } from "./DrawingToolbar";

it("手动画线先选支撑或压力，再选水平或趋势", async () => {
  const changes: string[] = [];
  render(<DrawingToolbar kind={null} geometry="horizontal" anchors={0} onKindChange={(kind) => changes.push(String(kind))} onGeometryChange={(geometry) => changes.push(geometry)} onCancel={() => changes.push("cancel")} />);
  await userEvent.click(screen.getByRole("button", { name: "画压力" }));
  await userEvent.click(screen.getByRole("button", { name: "趋势区间" }));
  expect(changes).toEqual(["resistance", "trend"]);
});
