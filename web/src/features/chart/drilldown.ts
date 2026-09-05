import type { Bar, Timeframe } from "../../types";

export interface ChartWindow {
  timeframe: Timeframe;
  start: string;
  end: string;
  startAt?: string;
  endAt?: string;
  label: string;
}

const DRILLDOWN: Record<Timeframe, Timeframe[]> = {
  "1mo": ["1w", "1d", "60m", "30m", "15m", "5m"],
  "1w": ["1d", "60m", "30m", "15m", "5m"],
  "1d": ["60m", "30m", "15m", "5m"],
  "60m": ["30m", "15m", "5m"],
  "30m": ["15m", "5m"],
  "15m": ["5m"],
  "5m": [],
};

const MINUTES: Partial<Record<Timeframe, number>> = {
  "5m": 5,
  "15m": 15,
  "30m": 30,
  "60m": 60,
};

function shiftDate(value: string, days: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function monthEnd(value: string) {
  const [year, month] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month, 0, 12)).toISOString().slice(0, 10);
}

function offsetMinutes(value: string) {
  if (value.endsWith("Z")) return 0;
  const match = value.match(/([+-])(\d{2}):(\d{2})$/);
  if (!match) return 0;
  const minutes = Number(match[2]) * 60 + Number(match[3]);
  return match[1] === "+" ? minutes : -minutes;
}

function timestampInOriginalOffset(value: string, deltaMinutes = 0) {
  const offset = offsetMinutes(value);
  const instant = new Date(value).getTime() + deltaMinutes * 60_000;
  const local = new Date(instant + offset * 60_000).toISOString().slice(0, 19);
  if (offset === 0 && value.endsWith("Z")) return `${local}Z`;
  const sign = offset >= 0 ? "+" : "-";
  const absolute = Math.abs(offset);
  const hours = String(Math.floor(absolute / 60)).padStart(2, "0");
  const minutes = String(absolute % 60).padStart(2, "0");
  return `${local}${sign}${hours}:${minutes}`;
}

export function drilldownTimeframes(timeframe: Timeframe) {
  return [...DRILLDOWN[timeframe]];
}

export function drillWindow(bar: Bar, parent: Timeframe, target: Timeframe): ChartWindow {
  if (!DRILLDOWN[parent].includes(target)) throw new Error("目标周期必须小于当前周期");
  const tradeDate = bar.timestamp.slice(0, 10);

  if (parent === "1mo") {
    return {
      timeframe: target,
      start: `${tradeDate.slice(0, 7)}-01`,
      end: monthEnd(tradeDate),
      label: tradeDate.slice(0, 7),
    };
  }
  if (parent === "1w") {
    const day = new Date(`${tradeDate}T12:00:00Z`).getUTCDay();
    const start = shiftDate(tradeDate, day === 0 ? -6 : 1 - day);
    const end = shiftDate(start, 4);
    return { timeframe: target, start, end, label: `${start}～${end.slice(5)}` };
  }
  if (parent === "1d") {
    return { timeframe: target, start: tradeDate, end: tradeDate, label: tradeDate };
  }

  const startAt = timestampInOriginalOffset(bar.timestamp, -(MINUTES[parent] ?? 0));
  const endAt = timestampInOriginalOffset(bar.timestamp);
  return {
    timeframe: target,
    start: startAt.slice(0, 10),
    end: endAt.slice(0, 10),
    startAt,
    endAt,
    label: `${startAt.slice(5, 16)}～${endAt.slice(11, 16)}`,
  };
}

export function filterWindowBars(bars: Bar[], window: ChartWindow) {
  if (!window.startAt || !window.endAt) return bars;
  const start = new Date(window.startAt).getTime();
  const end = new Date(window.endAt).getTime();
  return bars.filter((bar) => {
    const timestamp = new Date(bar.timestamp).getTime();
    return timestamp > start && timestamp <= end;
  });
}
