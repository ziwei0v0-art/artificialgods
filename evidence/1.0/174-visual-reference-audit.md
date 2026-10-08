# 174 轻透轮盘参考与实现边界

核验：2026-10-08。已打开 README 原始图片、173 菜单联系表与173独立计时窗图片逐图查看；未运行外部 BongoCat 或 Catime。所有外部参考为作者仓库/Apple 官方文档。

## 参考对应

- BongoCat 固定源：[f455f7c3 README](https://github.com/vladelaina/BongoCat/blob/f455f7c3b903ee98d2b9c0c5119c5d508c623f95/README.md)，[原截图](https://github.com/user-attachments/assets/aa376965-539e-4bbd-827d-bb9a29006069)。截图本轮已下载、打开；本地 `174-visual-reference/bongocat-readme-original.png`。图像是 11 瓣整环、外圈模型缩略图、中心角色，不能把它说成五项半弧。
- [当前 BongoCat README](https://github.com/vladelaina/BongoCat)：本轮重新读取并保存 `bongocat-current-README.md`，固定源用于复原原轮盘常量，当前 README 不能替代固定源。
- [Catime 固定源](https://github.com/vladelaina/Catime/tree/f47ed51044743d55e029872e7844ed6469a253dc) 与 [当前 README](https://github.com/vladelaina/Catime)：原作主张透明计时显示；本轮读取当前 README 并保存。README 的 `734037a7...` 图片实际是插件比特币信息示例，已打开核验，**不能当作原计时控件图**。右键等原软件路由不引入本项目。

## 173 为什么厚重

生产位置：`native/v1/main.swift` 的 `SceneWheelButton`、`SceneSemicircleLayout`、`SceneDialSurface`；计时位置 `native/v1/TimerControls.swift`。截图副本保存在 `174-visual-reference/before-173-menu.png` 与 `before-173-detached-timer.png`。

| 项 | BongoCat 固定源 | 天姥173 | 174处理 |
|---|---|---|---|
| 根布局 | 11瓣整环，内/外径82/184，图标径132；608逻辑画布 | 五瓣半弧，64/122、图标径94；264×166 | 保留已验证半弧与转向边缘布局，禁止搬入大整窗 |
| 静态瓣色 | 白→#F6F9FF→#EEF3FC渐变，alpha=FF | #FCFAF0约.98；悬停绿底alpha1 | 原作白底并非透明玻璃。按用户本轮要求改成真正AppKit后景模糊+低alpha叠色 |
| 中心 | 原有功能图标/标题及渐消背景，非此绘图函数中的角色 | 独立金黄圆饼alpha.99 | 保留中心求签/返回动作，改成同一玻璃材质 |
| 边框 | 常规1.1，外缘1.4逻辑单位；白色alpha250/235 | 常规0.7、中心1.2pt，白色alpha.85 | 缩为0.5pt低alpha边，取消金色厚饼 |
| 阴影 | 6层低alpha描边扩散（常规每层alpha3/255） | 每瓣黑.08 blur3 | 轻黑.04 blur2；不能额外铺大半圆底层 |
| 图标 | 28，语义蓝/青/粉/红等；hover ×1.15 | 32、统一深绿，hover不缩图标 | 28、中性深灰；正式虫瓶/签筒原图保持；hover ×1.15 |
| 出现 | 22ms逐瓣错开，360ms cubic，局部zoom .72→1，径向pull -26→0；全盘700ms quartic | ease仅作用alpha；形变只有全盘opening | 恢复局部zoom和pull，按122/184等比调整位移，保留时序 |
| hover | response17，zoom +.055，pull+7.5；按住zoom×.96 | 径向1+.018lift，无局部缩放 | 保留原局部变换；按住回馈需要按钮持续触发渲染 |
| 装扮二级 | 短外圈缩略图瓣 | 两个90°大扇面 | 保留两类，限制单瓣半角不超过π/10，消除厚大半圆板 |
| 独立计时窗 | 原作主张透明桌面文字 | 300×160奶油背景alpha1，多排按钮 | 主代理单独实施；本代理不写TimerControls |

原截图已经合成到海岸壁纸，像素 alpha 全255不能单独反推出图层透明度；源文件的静态颜色alpha=FF是更直接证据。截图里透底的是瓣间和中心空间。不能据“看着轻”断言原作使用了模糊材质。

本轮像素记录：原图1149×904，alpha范围255…255；普通顶部瓣 `(620,160)` 与 `(600,190)` 均为RGBA `(250,252,255,255)`，`(618,284)` 为 `(244,247,255,255)`；蓝色悬停瓣 `(390,320)` 为 `(87,176,255,255)`，`(425,346)` 为 `(71,163,250,255)`。位置是整张原图坐标，不是控件逻辑坐标；所有SHA-256与采样值见 `174-visual-reference/reference-manifest.json`。

## AppKit 毛玻璃可行路径

[Apple maskImage](https://developer.apple.com/documentation/appkit/nsvisualeffectview/maskimage) 规定使用图像alpha遮罩；[blendingMode](https://developer.apple.com/documentation/appkit/nsvisualeffectview/blendingmode-swift.property) 的 `.behindWindow` 模糊窗口后方内容。原文 JSON 已存本参考目录。

每个按钮配一个 `SceneDialGlassView: NSVisualEffectView`，在按钮同级下方、跟随同一 frame 和扇瓣 path，`maskImage` 由 path 的白色alpha生成。玻璃 `hitTest` 返回nil；业务按钮仍按实际path包含关系接收事件。这样外部矩形、瓣间缝与中心空隙没有背景填充。不能只给大 NSVisualEffectView 设置半圆cornerRadius，也不能只降低一张奶油不透明NSView的alpha并称其毛玻璃。

将材质设为 `.hudWindow`、`.active`、`.behindWindow`，效果alpha从0.72开始。浅/深系统外观交由AppKit；绘制层只叠约.05–.14的中性色和很薄的边。AppKit按系统“减少透明度”可能回退；实际桌面模糊是否显示需主代理在唯一运行实例中确认。无窗口 raster 只证实几何/叠色/文字，不证明WindowServer后景模糊。

## 验收点

1. 五个主瓣、中心与两个装扮类别保留 toolTip/AX label；无常驻文字。
2. 每瓣mask存在且玻璃不劫持hit；真正命中仍为绘制路径。瓣间不能触发邻瓣。
3. 四个方向中 hover 最大外移也不裁边，常态44pt触区保留。
4. 逐瓣局部zoom/pull和图标hover尺寸确实变化，静止后60Hz timer停止。
5. 无窗口测试不会启动后台worker、第二游戏或写存档。真实桌面材质由主代理统一检查，未检查前不标完成。

## 已实施与本地验证

已精准改写 `native/v1/main.swift` 的 `SceneMenuArtwork` 至 `SceneMenuPanel` 声明前区域；原区段与测试备份位于 `174-before/SceneMenu.swift.fragment` 和 `174-before/test_semicircle_menu.py`。未改TimerControls、主代理TimerView或服务。保持五项动作、中心求签/显示/返回与左右上下布局。

- `tests/test_semicircle_menu.py` 新增真实玻璃mask、mask透明角/不透明中心、hover几何/图标大小与逐瓣早末帧几何检查。旧代码先在“Every root, category and hub has a masked native glass surface”失败，日志 `red-menu-tests.log`；新实现最终9项全通过，24.383秒，日志 `green-menu-tests.log`。
- 编译命令环境采用 `SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk`，Python `python3.12`；未硬编码产品工具链。最初默认SDK27缺SwiftUIMacros插件，改用项目已验证的SDK26.5后完成红绿验证。
- 已生成并实际打开 `overlay-only-review-2x.png`、`hover-mask-up.png`、`overlay-only-reveal-2x.png` 与 `reference-contact-sheet.png`。联系表明确标注174仅含叠色/图标，**未伪造或模拟WindowServer模糊**。离屏1×/2×、四方向悬停mask和40/120/240/450/750ms出现帧均保留。
- 新子菜单只剩两瓣短形和中心返回；原大四分之一环块已消除。图标使用动态labelColor/选中色，深浅背景的手动draw检查均可辨认。
- 玻璃本身 `hitTest=nil`；瓣间仍走原 `SceneDialSurface.mouseDown` 空白关闭逻辑。没有宣称这些像素会穿透原生菜单窗口到下面应用。
- 主代理需统一检查实际单实例桌面模糊、系统外观与真实鼠标；`SceneMenuPanel` 创建处的 `hasShadow=true` 位于本分工区域外，已建议主代理关闭，避免系统窗口阴影再叠一层。
