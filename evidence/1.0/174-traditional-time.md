# 174 国风时间换算与解析

本轮仅新增传统时间换算层，并接入既有 Catime 输入适配器。所有时长最终都是整数秒；没有第二套计时循环，没有修改 third_party/Catime 上游源码。香、茶是可设置的产品单位，默认一盏茶 600 秒、一炷香 1800 秒。

## 口径与来源

- [香港天文台：天干和地支，表三](https://www.hko.gov.hk/tc/gts/time/stemsandbranches.htm) 列出十二时辰与现代时间对应关系：辰时为 07:00–09:00，子时跨 23:00–01:00。本次换算沿用这套对应。
- [故宫博物院：御制银镀金简平地平合璧仪](https://www.dpm.org.cn/collection/clock/228946.html) 藏品说明记录十二时辰分初、正。2026-10-08 通过官方页面的搜索索引核对到该说明；直接页面抓取超时，未声称实物现场核验。
- [故宫博物院：新法地平日晷](https://www.dpm.org.cn/collection/clock/234638.html) 说明此日晷将百刻改为一日 96 刻。这里按 24 小时 ÷ 96 推得一刻 15 分钟；这是本项目既定的 96 刻显示口径，不混入百刻制。
- 上述资料不为“一盏茶固定 10 分钟”或“一炷香固定 30 分钟”提供历史定长证明。本次仅把它们设为可修改的产品约定，不宣传为统一古制。
- “辰时三刻”在产品中采用省略“初”的输入别名，从辰初 07:00 起加三刻，即 07:45；完整显示为“辰初三刻”。这是一项已明示的输入规则，不宣称所有历史语境都如此解读。

## 已提供的 API

```python
from tianmu_mvp.duration import parse_duration, duration_label, traditional_elapsed
from tianmu_mvp.traditional_time import parse_traditional_clock, traditional_clock_label
from tianmu_mvp.clock import clock_readout

parse_duration(text, *, tea_seconds=600, incense_seconds=1800)  # -> positive int seconds
duration_label(seconds, *, tea_seconds=600, incense_seconds=1800)  # -> exact alias str
traditional_elapsed(seconds)  # -> exact elapsed/remaining str, supports legacy large counts
parse_traditional_clock(text)  # -> datetime.time, naive local clock address
traditional_clock_label(moment)  # datetime/time already in desired zone -> str
clock_readout(now, timezone='local', show_traditional=True)  # explicit timestamp -> str
```

`duration_label` 不内含现代数字，UI 可组合为“一炷香 · 30 分钟”。默认示例：300 秒“半盏茶”、600 秒“一盏茶”、900 秒“一刻”、1800 秒“一炷香”、2700 秒“三刻”、3600 秒“半个时辰”。任意余量交给 `traditional_elapsed`：1500 秒“一刻10分”、3900 秒“四刻5分”、7201 秒“一时辰1秒”，不向上进刻。

中文时长支持正整数阿拉伯数字、规范的一至九十九、两、半，单位包含时辰、刻、盏茶、炷香、小时、分钟、分、秒；允许单位间空格或“又”。例如“一时辰三刻”“2 刻 5 分钟 3 秒”。不接受一二刻、十十刻、零值、负数、不完整句、重复单位、未知尾词或小数。重复小时家族（如一小时一时辰）也拒绝，避免不明确的输入。ASCII 输入仍原样进入 Catime，保留 `25`、`1h30m`、`1 30`、`1 30 15` 原有规则。

时长解析保持 Catime int32 正数上限；显示函数不套该上限，以兼容既有大计时记录。茶／香配置在此纯换算层要求 1–2147483647 的整数秒；持久化服务可施加更窄的产品设置范围。奇数秒单位能整份使用，但“半份”必须整秒可除，否则明确报错，不截断。

## 时刻与时长边界

`parse_duration('辰时三刻')` 报“这是时刻，不是时长”，绝不启动 45 分钟倒计时。独立时刻 API 能解析“辰时三刻”“辰初三刻”“辰正二刻”“子时四刻”，并处理子时跨午夜；显式初／正仅接受零至三刻，整时辰允许零至七刻。

该 API 不选择日期、不推算下次到点、不创建闹钟；DST 跳时／重叠与日期定位仍未实现，不能把解析成功说成绝对时刻提醒已完成。实际时钟显示按 caller 提供的时间与时区生成，秒计时继续由既有 Catime 核心负责。

## 验证

- 先写新测试并执行，中文解析、时刻区分和新 API 缺失产生预期失败，记录 `174-traditional-red.log`。
- 修复规范数字检查：防止 Python 子串判断把“一二”误识别为“一”；现有非法输入测试已覆盖。
- 大整数非法时间戳先产生 OverflowError，追加验证后统一转为 ValueError，记录 `174-traditional-clock-invalid-red.log`。
- 最终回归命令与结果见 `174-traditional-green.log`，使用项目 Python 3.12。运行范围：传统时间、原 duration、clock、timer_session 及主代理新增 traditional_timer_service。此文件之外的完整无窗口回归由主代理统一执行。
- 初次追加 service 测试误用了系统 Python 3.9，因既有 routine.py 的 `str | None` 注解无法加载而退出；切换项目 `python3.12` 后通过。该失败不是产品功能通过的证据，未修改既有 routine.py。
- 未启动可见应用、未修改正式存档、未把自动化测试结果记为实机界面验收。原文件备份位于 `evidence/1.0/174-before/tianmu_mvp/`。
