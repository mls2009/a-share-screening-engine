import type { Timeframe } from "../../types";

const timeframes: Array<[Timeframe, string]> = [
  ["5m", "5分"], ["15m", "15分"], ["30m", "30分"], ["60m", "60分"],
  ["1d", "日"], ["1w", "周"], ["1mo", "月"],
];

export function TimeframeToolbar({ value, onChange }: { value: Timeframe; onChange: (value: Timeframe) => void }) {
  return (
    <div className="timeframe-toolbar" aria-label="K 线周期">
      {timeframes.map(([timeframe, label]) => (
        <button key={timeframe} type="button" aria-label={label} className={value === timeframe ? "active" : ""} onClick={() => onChange(timeframe)}>{label}</button>
      ))}
    </div>
  );
}
