# 灶神 · artificialgods

一款常驻 macOS 桌面的像素神龛养成小游戏。小道童陪着一座桌角神龛，供奉、捕虫、陈设与每日小仪式构成日常体验；独立计时工具可以陪伴工作。

当前源码版本：**1.0.7 / build 27 · 菜单栏与退出修复候选**。游戏中文名改为《灶神》，英文名为 `artificialgods`，仓库名为 `artificialgods`。本仓库保存当前代码、正式美术、第三方来源与许可、测试和必要设计说明。个人存档、临时验证档、缓存、历史安装包和原始参考资料保留在本地。

本轮菜单栏改用 macOS 原生菜单，其中“退出”作为独立入口，直接退出应用，不受场景菜单隐藏偏好的影响。本轮构建与针对性检查已完成，见下方验证状态。

![灶神原生场景预览](docs/images/zaoshen-game-preview.png)

上图为游戏原生绘制层的150%预览。初阶泥像采用相背双身造型，头冠完整收在横梁内；背侧闭眼，前侧带附眼点。附眼设定已确认为共6只，只画当前视角实际可见的部分。人体、衣袍和法器关系已整体重绘，视觉仍待用户验收。后续升级像保留原有独立资源，尚未统一重绘。

黄色底、奶白软绒团图标沿用已确认版本。图标来源与精确提示词在 `assets/production/brand/`；新神像的[来源记录](docs/art/zaoshen-g0-idol-v04.json)与[本轮验收范围](docs/design/2026-10-08-zaoshen-acceptance.md)分别记录生成过程和待确认事项。神像定制仍是后续方向。

## 当前功能

- 神龛与道童场景、独立桌面虫层、虫瓶与陈设。
- 五项半弧菜单及独立小钟，使用原生毛玻璃材质。
- Catime 核心计时：时钟、倒计时、正计时、番茄钟，支持暂停、继续和按原时长重来。
- 国风换算：一刻15分钟、一时辰2小时；茶默认10分钟、香默认30分钟，可修改。支持“半炷香”“三刻”等中文时长；时钟按十二时辰初正与96刻显示。

## 在 Mac 上构建

需要 Apple Silicon Mac、已安装的 Xcode Command Line Tools 和 Python 3.12。进入仓库后，使用一个尚不存在的输出目录：

```sh
python3.12 -B tools/build_native.py --output "$PWD/build/local/灶神.app"
```

这是依赖构建时本机 Python 的开发包。当前机器的 macOS 27 SDK 缺少 SwiftUI 宏插件，本机构建使用现有的 macOS 26.5 SDK，命令示例：

```sh
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
python3.12 -B tools/build_native.py --output "$PWD/build/local/灶神.app"
```

可搬移交付包另加 `--embed-python`。该选项目前校验指定的 Python 3.12.14、20260814 arm64 独立运行环境；普通 Python 安装不保证满足该校验。工具不会自动下载安装运行环境。详情与来源摘要见 [运行环境说明](tools/python_runtime_licenses/README.md)。

初次试运行请显式使用新建体验档：

```sh
"$PWD/build/local/灶神.app/Contents/MacOS/Tianmu" \
  --save-file "$PWD/build/local/体验存档/state.json"
```

不要同时打开多个游戏实例。直接双击应用会使用本机正式默认存档，体验档与正式档不自动合并。

## 验证状态

**1.0.7 当前验证：**139项菜单、后台退出、存档、计时与打包检查通过；内置Python的新候选构建成功，两次搬移后端检查通过。隔离异常退出实测最慢约1.32秒，真实桌面操作与用户验收仍待确认。详见[1.0.7 检查记录](docs/verification/1.0.7.md)。

**1.0.6 历史验证：**名称、图标打包、启动边界、原生展示和无窗口通知等30项针对性检查通过。重绘神像通过真实 `TianmuView` 原生绘制层输出20%、75%、150%及浅深背景预览；冠饰与法器留在龛内。该版构建与内置运行环境的验证见[1.0.6 检查记录](docs/verification/1.0.6.md)。

用户准备先做整体验收，尚未宣布验收通过。苍蝇美术的真实感和其他产品细节留待体验反馈，本版沿用既有果蝇资源；附眼细节在默认小尺寸下不保证逐点可辨。

**1.0.5 历史基线：**43项品牌、打包、启动、恢复和原生控件检查通过；结果见 [176检查记录](evidence/1.0/176-targeted-checks.json)。

**1.0.4 历史基线：**两轮合并去重覆盖645个用例，最后冻结源码的107项针对性复测通过；21项旧可见GUI/Tk用例排除。完整测试目录包含会打开旧界面的历史测试；安全回归入口为 [174-run-safe-regression.py](evidence/1.0/174-run-safe-regression.py)，运行后会写入当前副本的 `evidence/1.0`，不要覆盖你要保留的原验证记录。

[最终回归记录](evidence/1.0/174-final-regression-summary.json)与[界面观察](evidence/1.0/174-ui-observation.md)分别记录自动测试和实际观察。真实Finder框选入瓶、全局鼠标、多屏、Mission Control、睡眠、通知声音和用户新视觉接受仍待验收；这些未被自动测试替代。扩展开场仍是设计提案。

## 目录

- `native/`：Swift、AppKit、SwiftUI 展示与桌面交互。
- `tianmu_mvp/`：Python 规则、计时适配、存档和后台服务。
- `assets/production/`：当前构建采用的资源，其视觉验收状态以对应记录为准；`assets/incoming/`仅含测试需要的两组原始夹具。
- `third_party/`：固定版本的计时、轮盘和果蝇参考源码及许可。
- `tools/`、`tests/`、`docs/`：构建工具、测试与设计记录。

## 开源与来源

默认代码许可为 **AGPL-3.0-only**，全文见 [LICENSE](LICENSE)。菜单已实际接入并翻译BongoCat的AGPL代码，因此整合代码不采用MIT。Catime保留Apache-2.0，果蝇乐园保留原包MIT声明及来源边界；详见[成熟实现复用记录](成熟实现复用记录_1.0.md)和各 `third_party/` 归因文件。

美术与原始参考的来源、单独授权范围见[资源声明](ASSET-LICENSES.md)。原始参考图不随仓库发布；代码开源不表示所有参考图或美术都采用同一种许可。应用与对应版本源码一起提供。
