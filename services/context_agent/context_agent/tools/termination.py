from langchain_core.tools import tool


@tool
def finish(output_json: str) -> str:
    """검색 완료. consistent reference 목록을 JSON 문자열로 전달해 종료한다.
    output_json: Reference 객체 list의 JSON 문자열."""
    return f"__FINISH__:{output_json}"


@tool
def give_up(reason: str) -> str:
    """검색 실패로 종료. 0건이거나 모든 reference가 consistent가 아닐 때 사용.
    reason: 종료 사유 (예: zero_hits_after_paraphrase, all_contradicts)"""
    return f"__GIVE_UP__:{reason}"
