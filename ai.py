"""用 Claude 判断新闻对持仓的影响、评估仓位风险。未设置 ANTHROPIC_API_KEY 时不启用。"""
import json
import os

import anthropic

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

NEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "impact": {"type": "string", "enum": ["high", "medium", "low", "none"]},
                    "direction": {"type": "string", "enum": ["利好", "利空", "中性"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "impact", "direction", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

RISK_SCHEMA = {
    "type": "object",
    "properties": {
        "risk_level": {"type": "string", "enum": ["低", "中", "高"]},
        "summary": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["risk_level", "summary", "risks", "suggestions"],
    "additionalProperties": False,
}


def enabled():
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _ask(system, prompt, schema, effort):
    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude 拒绝了该请求")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def rate_news(portfolio, news):
    """news: [{id, symbol, title, summary}] -> {id: {impact, direction, reason}}"""
    system = ("你是美股投资风控助手。判断每条新闻对用户持仓的实际影响程度。"
              "high=可能显著影响股价或基本面（财报、指引、监管、诉讼、并购、高管变动、重大订单等）；"
              "medium=值得关注；low=关系不大；none=无关或重复的泛泛报道。reason 用一句中文说明。")
    prompt = (f"用户持仓与关注:\n{json.dumps(portfolio, ensure_ascii=False)}\n\n"
              f"新闻:\n{json.dumps(news, ensure_ascii=False)}")
    result = _ask(system, prompt, NEWS_SCHEMA, "low")
    return {i["id"]: i for i in result["items"]}


def assess_risk(portfolio, important_news):
    system = ("你是美股投资风控助手。基于用户持仓、当日行情和近期重要新闻，评估整体仓位风险："
              "集中度、单票亏损、行业相关性、波动、新闻事件风险。用中文，简洁具体，不要空话。")
    prompt = (f"持仓与行情:\n{json.dumps(portfolio, ensure_ascii=False)}\n\n"
              f"近期重要新闻:\n{json.dumps(important_news, ensure_ascii=False)}")
    return _ask(system, prompt, RISK_SCHEMA, "medium")
