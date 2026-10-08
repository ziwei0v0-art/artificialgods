# Catime 计时核心与时长解析模块

来源：https://github.com/vladelaina/Catime
固定提交：f47ed51044743d55e029872e7844ed6469a253dc
许可：Apache-2.0，完整文本见 upstream/LICENSE。

2026-10-04 实查 GitHub API：`main` 仍为本固定提交；当日 `releases/latest` 为 v1.6.2（2026-08-27），不能把 README 旧标题 v1.5.0 当作当前发布版本。此目录按提交固定，不追随浮动 main。

## 原件与实际执行

- 既有解析原件：`src/utils/time_parser.c`、`time_parser_advanced.c`、`time_format.c`、`include/utils/time_parser.h`。适配头 `include/utils/time_parser.h` 以 BOOL/TRUE/FALSE 定义替代 windows.h，C 解析算法不变。早期保存的原件及 LICENSE 比官方 blob 仅多一个末尾换行，已重新核对，没有悄悄替换。
- 新保留原件：`src/timer/timer.c`、`timer_events_main.c`、`timer_events_pomodoro.c`、`timer_format.c`、`include/timer/timer.h`；逐字节 SHA 与官方 git blob 在 `UPSTREAM_CORE.json`，原件只读。
- 运行使用 `portable/timer_core.c` / `.h`。这是明确标记过修改的 Catime 核心抽取件，**不是声称原封移植整个 Windows 程序**。Python `TimerSession` 每次调用以下 C 核心，未保留另一个 Python 秒数推进算法；面板与独立小钟仍共享同一会话。

| 执行函数 | 固定上游出处 | 最小适配 |
| --- | --- | --- |
| `TimeParser_ParseAdvanced` | `src/utils/time_parser_advanced.c`，及 basic parser | 既有纯 C 算法直接编译；只暴露时长输入，不含 `ParseInput` 的绝对时刻分支 |
| `Catime_ResetTimer` | `timer.c:224-244` `ResetTimer` | 全局量变显式会话；调用者输入毫秒；删除 Windows/display reset 调用 |
| `Catime_TogglePauseTimer` | `timer.c:247-266` `TogglePauseTimer` | 同样移交平台边界；暂停标记替代时间戳 `> 0` 哨兵，从而支持合法零时刻 |
| `Catime_ReadMilliseconds` / `Catime_ReadSeconds` | `timer_events_main.c:119-136` `HandleMainTimer` | 保留正计时向下、倒计时向上取整和总时长上限；int32 扩为 int64；保存亚秒信息。`(ms+999)/1000` 改成等价商余式以避免溢出 |
| `Catime_Tick` | `timer_events_main.c:138-155` | 保留单次到期锁；用返回事件替换 Windows 窗口/通知/自动下一段分派 |
| `Catime_AdvancePomodoroState` | `timer_events_pomodoro.c:11-26` | 函数体原样复制，状态改显式参数；仅在用户按“下一段”后调用 |
| `Catime_FormatSeconds` | `timer_format.c:11-15,36-39` | 保留 H/M/S 分解，int64 安全格式化；用 Mac 原有补零显示替换 Windows 对齐空格 |

## Mac 与产品边界

`QueryPerformanceCounter/GetTickCount64`、WinMM 调度、`HWND/InvalidateRect`、Windows 通知与 INI 存储不进入 Mac。调用方仍提供既有真实时间 `now`；运行中/退出后的恢复以保存的 `deadline/started_at` 为准，因此休眠/重开经过时间不变。**这次没有声称已经移植 Catime 的 QPC 抗系统时钟校正或双时钟睡眠修正。** 游戏有效时间仍由原有 worker 独立控制。

`TimerSession` 继续保存原来的整数字段，新增可选 `remaining_milliseconds`、`elapsed_milliseconds`、`pause_started_at`，旧档缺少这些字段按已有整秒值无损恢复；新增字段与整秒镜像矛盾或非整数时拒绝。C 边界预留溢出空间，把不切实际的大于约 3600 万年的数据视为无效，正常旧档不改变。`preset_seconds` 为四个不同的 1–86400 秒整数，旧档默认 `[300,900,1500,2700]`。

手动番茄下一段、一次提醒后等待、单一任务替换确认、传统 96 刻及本地/北京时间显示，保持天姥已确认要求。Catime 自动推进多轮、到期关机/重启/锁屏/开网址、右键主入口不照搬。系统通知由现有 Mac 通知服务适配，保存成功后才提示；不因源码有该功能就引入新的系统动作。

## 构建与验证

`duration.native_library_path(root=None)` 只计算源码/头文件摘要路径；`duration.ensure_native_library(root=None)` 是开发和打包预编译入口，返回 `build/catime-core-<digest>.dylib`。摘要覆盖三份解析 C、适配头和 portable C/header。开发缺库时才调用 clang，采用临时文件后原子替换；已有库直接加载，不运行编译器。正式包应在构建阶段预编译并将库带进 `Contents/Resources/backend/build/`，避免在用户机编译或写入应用包。

`tests/test_catime_core.py` 在临时目录直接提取、编译上述未改上游函数体作为独立 oracle，仅 stub 平台端点，与移植件做 2400 步 tick/抖动/暂停/恢复/到期差分；另对真正的 TimerSession 连同 JSON 重载比对。`test_timer_precision.py` 覆盖重复亚秒暂停、整毫秒边界、存档精度、旧档迁移、常用值、双会话隔离及预编译加载。完整本轮证据见 `evidence/1.0/167-catime-source-audit.md`。

## 许可

代码 Apache-2.0，随目录保留完整 `upstream/LICENSE`、来源/固定提交和修改说明；固定提交树未发现独立 NOTICE。**软件图标另有作者保留权利条款，字体也分许可证**，没有导入 Catime 的图标、字体、壁纸或发布 EXE。参见该固定提交 README `Copyright Notice`。
