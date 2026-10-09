# macOS 签名与分发

`tools/sign_distribution.py` 只在 macOS 上为显式指定的候选 `.app` 制作新的签名副本。输入包保持不变，输出路径必须不存在，不能位于输入包内。不要把正式存档放进应用包；封印完成后，包内文件应保持只读。

## 本地资源封印

在工程根目录运行，路径按实际新候选调整：

```sh
python3.12 -B tools/sign_distribution.py \
  --app 'build/release-1.0.8-build29/灶神.app' \
  --output 'build/sealed-1.0.8/灶神.app' \
  --ad-hoc > 'signing-1.0.8.json'
```

`--ad-hoc` 不需要证书，也不访问 Apple 时间戳服务。它先签内置 Python 可执行文件、动态库和扩展模块，再签外层应用并生成资源封印。工具逐项校验 Mach-O，最后执行 `codesign --verify --deep --strict`，成功才输出 JSON 报告。新副本中的旧签名会被替换；输入中的签名保持不变。

这证明资源完整性可校验，不证明开发者身份可信、公证通过或 Gatekeeper 放行。报告中的 `notarization: not-performed` 和 `gatekeeper: not-assessed` 不应改写成通过。签名失败时命令返回非零状态，不产生成功报告；若最终复制阶段发生磁盘错误，可能留下不完整的新输出，不能分发。

报告保存各 Mach-O 的签名前、签后 SHA-256 及资源封印 SHA-256。`Contents/Resources/Runtime/runtime-manifest.json` 仍是构建时的来源记录，其中 `codesignInvoked: false` 和原哈希描述签名前状态；签后字节以签名报告为准。不要把签名报告写进已封印的 `.app`。

此工具只覆盖当前原生主程序和独立 Python `bin/lib` 布局。遇到额外 `.app`、`.framework`、`.xpc`、`.appex` 或 `.bundle` 会停下，避免把未规划的嵌套应用当作普通资源。只接受指向包内文件的相对符号链接。

## Developer ID 与公证

2026-10-09 本机只读查询结果为 `0 valid identities found`。当前未执行 Developer ID 签名、公证提交、票据装订或外机 Gatekeeper 验收。开发者账号、有效证书及其私钥由账号持有人配置；工具不创建证书、不配置钥匙串、不读取或保存账号凭证。

有有效的 **Developer ID Application** 身份后，显式传入其完整名称或 40 位证书 SHA-1，并使用另一个新输出路径：

```sh
python3.12 -B tools/sign_distribution.py \
  --app 'build/release-1.0.8-build29/灶神.app' \
  --output 'build/developer-id-1.0.8/灶神.app' \
  --identity 'Developer ID Application: 完整证书名称 (TEAMID)' \
  > 'signing-developer-id-1.0.8.json'
```

工具只匹配唯一、有效的 Developer ID Application 身份；缺失或歧义时失败，不退回 ad hoc。此模式为每个 Mach-O 启用 Hardened Runtime 和安全时间戳，时间戳步骤会访问 Apple 服务。它不会自动添加运行时豁免权限；须在正式签名后重新验证内置 Python 导入、后台服务、退出和存档行为。签名、公证要求见 [Apple 公证准备文档](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)及[常见公证问题](https://developer.apple.com/documentation/security/resolving-common-notarization-issues)。

以下是获得上传授权、由账号持有人配置好公证凭证后才执行的人工步骤，本轮未执行：

1. 用 `ditto -c -k --keepParent` 将 Developer ID 签名后的应用压缩为新的提交 ZIP。
2. 用 `xcrun notarytool submit <提交ZIP> --keychain-profile <已配置的名称> --wait --output-format json` 提交，保留请求 ID、最终状态和日志。只有最终 `Accepted` 才表示公证接受；请求已排队不等于接受。
3. 接受后对该 `.app` 执行 `xcrun stapler staple <应用路径>`，再执行 `xcrun stapler validate <应用路径>`。
4. 将装订后的应用重新压缩为最终分发 ZIP，记录 ZIP 的 SHA-256。不能继续分发装订前的旧 ZIP。
5. 在另一台符合支持范围的 Mac 上，通过真实下载保留隔离属性，检查 `spctl --assess --type execute --verbose=4 <应用路径>`，再实际打开并验证功能。不得以清除隔离属性代替 Gatekeeper 验收。

公证与装订步骤依据 [Apple 自定义公证流程](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)。正式签名、Apple 接受、票据装订、本机验证、外机首次启动应分别留证。最低系统版本声明与本机构建成功，不等于已在该最低版本实测，也不证明 Intel、Windows 或其他设备兼容。

## 工具检查

```sh
python3.12 -B -m unittest tests.test_sign_distribution -v
```

7 项检查在临时目录编译真实最小应用、模拟 Python 可执行体、dylib 和扩展模块；验证完整封印、资源篡改检出、原包不变、既有输出不覆、包内输出拒绝、越界链接拒绝，以及缺少正式身份时失败。只执行命令行校验，不启动游戏。Developer ID 成功路径与公证仍待真实身份和服务回执验证。
