import { Ban, Minus, TrendingUp } from "lucide-react";

import type { DrawingGeometry, DrawingKind } from "./drawing";

export function DrawingToolbar({ kind, geometry, anchors, onKindChange, onGeometryChange, onCancel }: {
  kind: DrawingKind | null;
  geometry: DrawingGeometry;
  anchors: number;
  onKindChange: (kind: DrawingKind) => void;
  onGeometryChange: (geometry: DrawingGeometry) => void;
  onCancel: () => void;
}) {
  return (
    <div className="drawing-toolbar">
      <div className="drawing-kinds">
        <button type="button" aria-label="画支撑" className={kind === "support" ? "support active" : "support"} onClick={() => onKindChange("support")}><span />画支撑</button>
        <button type="button" aria-label="画压力" className={kind === "resistance" ? "resistance active" : "resistance"} onClick={() => onKindChange("resistance")}><span />画压力</button>
      </div>
      <div className="geometry-kinds">
        <button type="button" aria-label="水平线" className={geometry === "horizontal" ? "active" : ""} onClick={() => onGeometryChange("horizontal")}><Minus size={14} />水平线</button>
        <button type="button" aria-label="趋势线" className={geometry === "trend" ? "active" : ""} onClick={() => onGeometryChange("trend")}><TrendingUp size={14} />趋势线</button>
      </div>
      {kind && <p>{anchors === 0 ? "请在 K 线图上选择第一个锚点" : "再选择一个锚点即自动保存"}</p>}
      {kind && <button type="button" className="cancel-drawing" onClick={onCancel}><Ban size={13} />取消画线</button>}
    </div>
  );
}
