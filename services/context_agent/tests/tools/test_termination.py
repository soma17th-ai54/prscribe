import json
from context_agent.tools.termination import finish, give_up


def test_finish_returns_finish_marker():
    refs = [{"chunk_id": "c1", "title": "T", "url": "https://x.com",
             "source_kind": "blog", "excerpt": "...", "fetched_at": "2026-05-08T00:00:00"}]
    result = finish.invoke({"output_json": json.dumps(refs)})
    assert "__FINISH__" in result
    data = json.loads(result.replace("__FINISH__:", "").strip())
    assert data[0]["chunk_id"] == "c1"


def test_give_up_returns_give_up_marker():
    result = give_up.invoke({"reason": "zero_hits_after_paraphrase"})
    assert "__GIVE_UP__" in result
    assert "zero_hits_after_paraphrase" in result
