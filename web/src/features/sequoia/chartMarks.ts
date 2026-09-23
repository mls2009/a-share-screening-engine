import type { ConditionMark } from '../watchlist/model';
import type { EvidenceGroup } from './api';

export const STRATEGY_COLORS: Record<string, string> = {
  turtle: '#f3c969',
  ma_volume: '#50d5a0',
  high_flag: '#72a9ff',
  shakeout: '#ff8494',
  trend_drop: '#b49aff',
  rps: '#6bc5ff',
  placement: '#ffb86b',
};

export function sequoiaChartMarks(groups: EvidenceGroup[], savedMarks: ConditionMark[] = []): ConditionMark[] {
  const marks: ConditionMark[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    for (const hit of group.occurrences ?? [{ date: '', checks: group.checks }]) {
      const check = hit.checks.find(item => item.mark?.date === hit.date) ?? hit.checks.find(item => item.mark);
      if (!check?.mark) continue;
      const day = group.id === 'placement' ? check.mark.date : hit.date || check.mark.date;
      const key = `${group.id}:${day}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const referenceStartDate = group.id === 'turtle'
        ? hit.checks.map(item => item.mark?.startDate).filter((value): value is string => Boolean(value)).sort()[0]
        : undefined;
      const savedTurtle = group.id === 'turtle'
        ? savedMarks.find(mark => mark.date === day && mark.label.startsWith('海龟突破 · 首次满足'))
        : undefined;
      marks.push({
        metric: 'close', timeframe: '1d', date: day, startDate: day, periods: 1,
        referenceStartDate,
        strategyId: group.id, strategyName: group.name,
        label: savedTurtle?.label ?? (group.id === 'turtle' ? `海龟突破 · 首次满足 ${day}` : `${group.name} · 命中 ${day}`),
      });
    }
  }
  return marks;
}
