from datetime import date, timedelta

from astock.domain.market import Timeframe
from astock.screening.annotations import condition_marks, entry_histories


def test_saved_ma_support_marks_use_saved_hits_after_rule_changes():
    hit = {"date": "2025-08-19", "start_date": "2025-08-18", "ma": 120,
           "supports": [
               {"date": "2025-04-14", "confirmation_start": "2025-04-15", "confirmation_end": "2025-05-15"},
               {"date": "2025-07-15", "confirmation_start": "2025-07-16", "confirmation_end": "2025-08-12"}],
           "types": ["双K"]}
    histories = {Timeframe.DAY: [{"feature_date": date(2026, 9, 24),
                                 "ma120_250_repeat_support_hits": []}]}
    saved = {"ma120_250_repeat_support_hits": [hit]}
    frozen = entry_histories(histories, "close", date(2026, 9, 25), saved)
    tree = {"kind": "condition", "metric": "ma120_250_repeat_support_2y", "timeframe": "1d"}
    marks = condition_marks(tree, {"result": "true"}, frozen)
    assert len(marks) == 5
    assert marks[-1]["date"] == "2025-08-19"


def test_window_marks_respect_less_than_comparison():
    tree = {"kind": "condition", "metric": "close", "timeframe": "1d",
            "operator": "at_least", "comparison_operator": "lt", "lookback": 2,
            "occurrences": 1, "right": {"kind": "constant", "value": 10, "unit": "price"}}
    rows = [{"feature_date": date(2026, 9, 4), "close": 9},
            {"feature_date": date(2026, 9, 3), "close": 11}]
    marks = condition_marks(tree, {"result": "true"}, {Timeframe.DAY: rows})
    assert [mark["date"] for mark in marks] == ["2026-09-04"]


def test_continuous_marks_actual_days_and_both_price_and_average():
    tree = {"kind": "condition", "metric": "close", "timeframe": "1d", "operator": "continuous",
            "lookback": 3, "right": {"kind": "metric", "metric": "ma_20", "timeframe": "1d"}}
    rows = [{"feature_date": date(2026, 9, 4) - timedelta(days=index), "close": 11, "ma_20": 10}
            for index in range(3)]
    marks = condition_marks(tree, {"result": "true", "actual": 11, "expected": 10}, {Timeframe.DAY: rows})
    assert len(marks) == 6
    assert {mark["date"] for mark in marks} == {"2026-09-04", "2026-09-03", "2026-09-02"}
    assert {mark["metric"] for mark in marks} == {"close", "ma_20"}


def test_non_matching_or_branch_has_no_mark():
    child = {"kind": "condition", "metric": "close", "timeframe": "1d", "operator": "gt",
             "right": {"kind": "constant", "value": 10, "unit": "price"}}
    tree = {"kind": "group", "logic": "or", "children": [child, {**child, "metric": "ma_20"}]}
    explanation = {"result": "true", "children": [{"result": "true"}, {"result": "false"}]}
    marks = condition_marks(tree, explanation, {Timeframe.DAY: [{"feature_date": date(2026, 9, 4)}]})
    assert [mark["metric"] for mark in marks] == ["close"]


def test_flatness_marks_five_average_points():
    tree = {"kind": "condition", "metric": "ma_10_slope_abs_5", "timeframe": "1d", "operator": "lte",
            "right": {"kind": "constant", "value": 0.05, "unit": "percent"}}
    rows = [{"feature_date": date(2026, 9, 4) - timedelta(days=index)} for index in range(6)]
    marks = condition_marks(tree, {"result": "true"}, {Timeframe.DAY: rows})
    assert marks[0]["metric"] == "ma_10"
    assert marks[0]["periods"] == 5


def test_weekly_pinbar_marks_keep_week_timeframe_and_month_support():
    tree = {'kind':'condition','metric':'pw_bull_within_156','timeframe':'1w',
            'operator':'eq','right':{'kind':'constant','value':True,'unit':'boolean'}}
    hit = {'date':'2026-06-12','start_date':'2026-06-05','bars':2,
           'zone':{'lower':9,'upper':10,'anchor_date':'2025-03-12'},
           'details':{'pa2_prominent':True,'pa2_bull_trend':True}}
    marks = condition_marks(tree,{'result':'true'}, {Timeframe.WEEK:[{'pw_bull_year_hits':[hit]}]})
    assert len(marks)==2
    assert all(m['timeframe']=='1w' for m in marks)
    assert marks[0]['periods']==2 and '月线' in marks[0]['label']
    assert marks[1]['priceLow']==9 and '260周历史月线' in marks[1]['label']


def test_body_low_retest_marks_both_references_and_current_visit():
    tree={'kind':'condition','metric':'body_low_retest','timeframe':'1d','operator':'eq',
          'right':{'kind':'constant','value':True,'unit':'boolean'}}
    levels=[dict(rank=i,price=9+i,lower=(9+i)*.95,upper=(9+i)*1.05,
                 date='2025-01-01',confirmed_date='2025-01-08') for i in (1,2)]
    marks=condition_marks(tree,{'result':'true'},{Timeframe.DAY:[dict(feature_date=date(2026,9,22),body_low_retest_levels=levels,body_low_retest_hits=levels[:1])]})
    assert len(marks)==3
    assert marks[0]['priceLow']==9.5
    assert '次低' in marks[1]['label']
    assert marks[2]['label'].startswith('实体低点回访：')


def test_ma_pierce_2y_marks_each_hit_date():
    tree = {"kind": "condition", "metric": "ma_cluster_pierce_up_2y", "timeframe": "1d",
            "operator": "eq", "right": {"kind": "constant", "value": True, "unit": "boolean"}}
    rows = [{"feature_date": date(2026, 9, 24), "ma_cluster_pierce_2y_hits": [
        {"date": "2025-08-08", "open": 9.5, "close": 11.0},
        {"date": "2026-03-12", "open": 8.8, "close": 10.2},
    ]}]
    marks = condition_marks(tree, {"result": "true"}, {Timeframe.DAY: rows})
    assert [mark["date"] for mark in marks] == ["2025-08-08", "2026-03-12"]
    assert {mark["metric"] for mark in marks} == {"close"}
    assert "均线粘连走平" in marks[0]["label"]


def test_ma_pierce_single_k_marks_latest_bar():
    tree = {"kind": "condition", "metric": "ma_cluster_pierce_up", "timeframe": "1d",
            "operator": "eq", "right": {"kind": "constant", "value": True, "unit": "boolean"}}
    rows = [{"feature_date": date(2026, 9, 24)}]
    marks = condition_marks(tree, {"result": "true", "actual": True}, {Timeframe.DAY: rows})
    assert [mark["date"] for mark in marks] == ["2026-09-24"]
