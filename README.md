# Options Expiration Calendar

用于 SPX 0DTE 交易准备的独立日历，初始覆盖 2026–2027，已上市 VIX/SPXO 周度日期采用 Cboe 当前清单。

- SPX 标准月度 AM 最后交易日（全天提醒，通常 17:00 ET）、AM 结算（开盘参考 09:30 ET）。
- 月度 OPEX / 季度 Triple Witching：SPXW PM 到期截止及标的常规收盘，通常 16:00 ET，半日 13:00 ET。SPY 期权实际停止交易及行权截止时间不同，须查券商和交易所。
- SPXW 月末及季末到期；季末替代月末，不重复。
- VIX 周度期权、SPXO AM 周度期权：仅发布 Cboe Available Weeklys 当前列出的日期，保留过去已记录日期。09:30 是开盘参考，不保证实际结算值发布时刻；不提供 VIX 最后交易截止时间。VIX 月度结算已由 Futures Roll 提醒，不重复生成。
- 不生成日常 SPXW 每日期权到期、期货到期或换月。

## 安装
1. 创建公开仓库 `options-expiration`（README 可开启）。上传本目录八个普通文件：脚本、测试、requirements.txt、config.json、holidays_snapshot.json、listed_weeklys.json、options-expiration.ics，以及 README。
2. 单独创建 `.github/workflows/update-calendar.yml` 并粘贴工作流。Actions → Update Options Expiration → Run workflow。配置修改也会自动触发运行。
3. 订阅 `https://raw.githubusercontent.com/rickeylau/options-expiration/refs/heads/main/options-expiration.ics#1` 。初始 ICS 已生成。Google Calendar 可能缓存或延迟刷新。
4. 新日历正常后，将 economic-calendar/config.json 中 `options_expiration` 设置为 false，取消重复 OPEX。保留 Futures Roll。

## 自动更新
每天 UTC 08:23；读取 market-holidays 的 Cboe 假日快照和 Cboe Available Weeklys。任一抓取或解析失败时不发布，不猜测未上市周度合约。年度标准日期按交易规则计算，仅覆盖假日快照中已有年份。临时调整应核对官方公告；本程序不连接交易账户。定时事件的 5 分钟只是显示长度。

## 数据来源
- https://www.cboe.com/about/hours/us-options/
- https://www.cboe.com/available_weeklys/
- https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications
- https://www.cboe.com/tradable-products/vix/vix-options/specifications
- https://www.optionseducation.org/referencelibrary/expiration-calendar
- https://www.cboe.com/insights/posts/cboe-introduces-am-settled-weekly-options-on-the-s-p-500-index/

## 测试
`python -m pip install -r requirements.txt`，`python -m unittest -v`；`python options_expiration.py --offline` 用本地快照生成，不访问网络。首次真实 GitHub Actions 运行需验证抓取及发布。config.json 各开关为 true/false。
