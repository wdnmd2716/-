# 美股持仓 & 新闻监控

不用盯盘：GitHub Actions 在美股交易时段每 30 分钟检查一次，有异动或新新闻才推送到微信，收盘后推送持仓汇总。

## 使用
1. 编辑 `config.yaml`：填入持仓（代码/股数/成本）、关注列表和提醒阈值。
2. 获取微信推送 token（二选一）：
   - PushPlus：https://www.pushplus.plus 微信登录后复制 token
   - Server酱：https://sct.ftqq.com 复制 SendKey
3. 仓库 Settings → Secrets and variables → Actions，添加 `PUSHPLUS_TOKEN` 或 `SERVERCHAN_KEY`。
4. Actions 页面手动运行一次 `Stock Monitor` 测试。

## 提醒规则
- 单日涨跌幅超过 `move_pct`
- 持仓亏损达到 `stop_loss_pct` / 盈利达到 `take_profit_pct`
- 持仓/关注股票出现新新闻（已推送过的不重复）
- 同一提醒每天只推一次

本地测试：`pip install -r requirements.txt && python monitor.py check`（未配置 token 时打印到终端）
