from tools.offline_eval import OfflineGoldLLM


def test_offline_gold_llm_replays_one_validated_sql_then_composition():
    llm = OfflineGoldLLM([
        {"sql": "SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster"},
    ])

    assert llm.complete("sql prompt") == "SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster"
    assert llm.complete("answer prompt") == "Offline synthetic contract answer."
