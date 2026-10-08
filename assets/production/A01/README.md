# A01 道童生产资源

当前运行资源以 `manifest.json` 为准：像素站姿采用 `stand-pixel-20261001.png`，保留全白小髻、灰肤、红瞳、长尖耳、素黑袍及白内领的身份。行走和日常动作使用同一站姿的固定部件与独立小道具，分别由 `fixedWalk` 和 `fixedActions` 描述。

2026-10-01生成的行走atlas已因外观反馈撤回，当前不引用；撤回PNG及其旧manifest只保留在本地，不随公开源码发布。技术运动与用户动作审美验收分开记录。

`stand.png`与`manifest-handpainted-20260927.json`为此前接入的手绘站姿，仍供风格比较工具使用；它不是当前manifest选中的角色图。来源是用户提供的本项目AI创作资产，原图未覆盖。当前像素原图和道具的原始文件保留，AppKit根据manifest进行运行时裁切与绘制。

主manifest支持`stand`、可选帧动画和当前固定部件动作；`sourceRect`以PNG左上为原点。构建仅复制主manifest引用的资源。身份、实际图像、运动效果与用户整体验收是不同核验项。
