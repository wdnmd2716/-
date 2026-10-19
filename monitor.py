"""美股持仓 & 新闻监控，结果推送到微信（PushPlus 或 Server酱）。

用法: python monitor.py [check|summary]
  check   - 盘中检查：只在触发阈值或有新新闻时推送
  summary - 收盘汇总：推送全部持仓盈亏
"""
import json
import os
import sys
from pathlib import Path

import requests
import yaml
import yfinance as yf

import ai

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_news": {}, "alerted": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def push(title, content):
    pushplus = os.getenv("PUSHPLUS_TOKEN")
    serverchan = os.getenv("SERVERCHAN_KEY")
    if pushplus:
        requests.post("https://www.pushplus.plus/send", timeout=15, json={
            "token": pushplus, "title": title, "content": content, "template": "markdown"})
    elif serverchan:
        requests.post(f"https://sctapi.ftqq.com/{serverchan}.send", timeout=15,
                      data={"title": title, "desp": content})
    else:
        print(f"[未配置推送] {title}\n{content}")


def quote(symbol):
    """返回 (现价, 当日涨跌幅%, 日期)。"""
    hist = yf.Ticker(symbol).history(period="5d")
    if len(hist) < 2:
        return None
    price, prev = hist["Close"].iloc[-1], hist["Close"].iloc[-2]
    return price, (price / prev - 1) * 100, str(hist.index[-1].date())


def fetch_news(symbol, seen, limit):
    fresh = []
    for item in yf.Ticker(symbol).news or []:
        c = item.get("content", item)
        nid = item.get("id") or c.get("id")
        title = c.get("title")
        url = (c.get("canonicalUrl") or {}).get("url") or c.get("link", "")
        if not nid or not title or nid in seen:
            continue
        seen.append(nid)
        fresh.append({"id": nid, "symbol": symbol, "title": title, "url": url,
                      "summary": (c.get("summary") or "")[:500]})
    del seen[:-200]  # 只保留最近 200 条，防止文件膨胀
    return fresh[:limit]


def main(mode):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    a = cfg["alerts"]
    state = load_state()
    holdings = {h["symbol"]: h for h in cfg.get("holdings", [])}
    symbols = list(holdings) + [s for s in cfg.get("watchlist", []) if s not in holdings]

    alerts, news_lines, rows, all_news, portfolio = [], [], [], [], []
    total_value = total_cost = 0
    for sym in symbols:
        try:
            q = quote(sym)
        except Exception as e:
            print(f"{sym} 行情获取失败: {e}")
            continue
        if not q:
            continue
        price, chg, day = q
        line = f"{sym} ${price:.2f} ({chg:+.2f}%)"
        triggers = []
        if abs(chg) >= a["move_pct"]:
            triggers.append(f"日内{'大涨' if chg > 0 else '大跌'}")
        h = holdings.get(sym)
        if h:
            pnl = (price / h["cost"] - 1) * 100
            total_value += price * h["shares"]
            total_cost += h["cost"] * h["shares"]
            line += f" 持仓{h['shares']}股 盈亏{pnl:+.1f}% (${(price - h['cost']) * h['shares']:+,.0f})"
            if pnl <= a["stop_loss_pct"]:
                triggers.append("触及止损线")
            if pnl >= a["take_profit_pct"]:
                triggers.append("触及止盈线")
        rows.append(f"- {line}")
        portfolio.append({"symbol": sym, "price": round(price, 2), "day_change_pct": round(chg, 2),
                          **({"shares": h["shares"], "cost": h["cost"],
                              "pnl_pct": round((price / h["cost"] - 1) * 100, 1)} if h else {"watch_only": True})})

        # 同一天同一类提醒只推一次
        key = f"{sym}:{day}"
        done = state["alerted"].setdefault(key, [])
        new = [t for t in triggers if t not in done]
        if new:
            done.extend(new)
            alerts.append(f"- **{sym}** {'、'.join(new)}：{line}")

        if cfg["news"]["enabled"]:
            try:
                fresh = fetch_news(sym, state["seen_news"].setdefault(sym, []),
                                   cfg["news"]["max_per_symbol"])
            except Exception as e:
                print(f"{sym} 新闻获取失败: {e}")
                fresh = []
            all_news.extend(fresh)

    # AI 过滤新闻：只推 high/medium；未启用 AI 则全部推送
    ratings = {}
    if all_news and ai.enabled():
        try:
            ratings = ai.rate_news(portfolio, [{k: n[k] for k in ("id", "symbol", "title", "summary")}
                                               for n in all_news])
        except Exception as e:
            print(f"AI 新闻分析失败，改为全部推送: {e}")
    icon = {"high": "🔴", "medium": "🟡"}
    for n in all_news:
        r = ratings.get(n["id"])
        if ratings and (not r or r["impact"] not in icon):
            continue
        if r:
            line = f"- {icon[r['impact']]} **{n['symbol']}** {r['direction']}：[{n['title']}]({n['url']})\n  {r['reason']}"
            if r["impact"] == "high":
                state.setdefault("important_news", []).append(
                    {"symbol": n["symbol"], "title": n["title"], "reason": r["reason"]})
        else:
            line = f"- **{n['symbol']}** [{n['title']}]({n['url']})"
        news_lines.append(line)
    state["important_news"] = state.get("important_news", [])[-30:]

    # 清理旧提醒记录
    state["alerted"] = dict(list(state["alerted"].items())[-100:])

    if mode == "summary":
        body = "\n".join(rows)
        if total_cost:
            body += f"\n\n**总市值** ${total_value:,.0f}，**总盈亏** ${total_value - total_cost:+,.0f} ({(total_value / total_cost - 1) * 100:+.2f}%)"
        if ai.enabled():
            try:
                r = ai.assess_risk(portfolio, state.get("important_news", []))
                body += (f"\n\n## 🤖 AI 仓位风险：{r['risk_level']}\n{r['summary']}\n\n**风险点**\n"
                         + "\n".join(f"- {x}" for x in r["risks"])
                         + "\n\n**建议**\n" + "\n".join(f"- {x}" for x in r["suggestions"]))
            except Exception as e:
                print(f"AI 风险评估失败: {e}")
        push("📊 美股收盘汇总", body)
    elif alerts or news_lines:
        parts = []
        if alerts:
            parts.append("## ⚠️ 价格提醒\n" + "\n".join(alerts))
        if news_lines:
            parts.append("## 📰 重要新闻\n" + "\n".join(news_lines))
        push("⚠️ 美股提醒" if alerts else "📰 持仓新闻", "\n\n".join(parts))
    else:
        print("无新提醒")
    save_state(state)


def auto_mode():
    """服务器 cron 用：按纽约时间判断该盘中检查、收盘汇总，还是跳过。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return None
    t = now.hour * 60 + now.minute
    if 9 * 60 + 30 <= t <= 16 * 60:
        return "check"
    state = load_state()
    if t > 16 * 60 and state.get("summary_date") != str(now.date()):
        state["summary_date"] = str(now.date())
        save_state(state)
        return "summary"
    return None


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "auto":
        mode = auto_mode()
        if not mode:
            sys.exit(0)
    main(mode)
