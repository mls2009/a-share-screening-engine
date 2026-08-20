import type { Timeframe } from "../../types";

export interface DrawingAnchor { date: string; price: number }
export type DrawingKind = "support" | "resistance";
export type DrawingGeometry = "horizontal" | "trend";

export function buildManualZonePayload(
  timeframe: Timeframe,
  kind: DrawingKind,
  geometry: DrawingGeometry,
  anchors: [DrawingAnchor, DrawingAnchor],
) {
  const ordered = [...anchors].sort((left, right) => left.date.localeCompare(right.date)) as [DrawingAnchor, DrawingAnchor];
  const [first, second] = ordered;
  const center = geometry === "horizontal" ? (first.price + second.price) / 2 : second.price;
  const halfWidth = Math.max(center * 0.003, 0.01);
  const days = Math.max(1, (Date.parse(second.date) - Date.parse(first.date)) / 86_400_000);
  const slope = geometry === "trend" ? (second.price - first.price) / days : null;
  return {
    timeframe,
    as_of_date: second.date,
    zone_kind: kind,
    geometry,
    lower_price: center - halfWidth,
    center_price: center,
    upper_price: center + halfWidth,
    slope,
    intercept: geometry === "trend" ? first.price : null,
    anchors: ordered.map((anchor) => [anchor.date, anchor.price] as [string, number]),
  };
}
