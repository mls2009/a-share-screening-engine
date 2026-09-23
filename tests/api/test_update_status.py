from test_screening_api import _client


def test_market_update_status_reports_local_data_and_scheduler(tmp_path):
    client, database = _client(tmp_path)
    response = client.get("/api/market-updates/status")
    assert response.status_code == 200
    result = response.json()
    assert result["scheduled_at"] == "16:10"
    assert result["timezone"] == "Asia/Shanghai"
    assert result["latest_daily_date"] == "2026-08-20"
    assert result["latest_job"] is None
    assert result["scheduler_running"] is False
    database.connection.close()


def test_market_update_status_bounds_coverage_to_recent_window(tmp_path):
    client, database = _client(tmp_path)
    con = database.connection
    con.execute(
        "insert into symbols(symbol,name,exchange,board,is_listed) values ('600002.SH','旧股','SH','main',true)"
    )
    con.execute(
        "insert into market_features(symbol,timeframe,feature_date,feature_version) values ('600001.SH','1d','2026-08-19','v1'),('600002.SH','1d','2026-08-10','v1')"
    )
    result = client.get("/api/market-updates/status").json()
    assert result["daily_coverage"] == [
        {"date": "2026-08-20", "stocks": 1},
        {"date": None, "stocks": 1},
    ]
    assert result["coverage_window_start"] == "2026-08-13"
    database.connection.close()
