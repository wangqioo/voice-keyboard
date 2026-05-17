# Windows 打包

当前实现：托盘常驻应用，入口为 `agent.windows_tray`，使用 PyInstaller onedir 模式输出：

```
dist/VoiceKeyboard/VoiceKeyboard.exe
```

运行后在系统托盘显示 Voice Keyboard 图标，右键菜单提供：

- 打开配置
- 打开配置目录
- 列出麦克风设备
- 测试提示窗
- 重载配置
- 注册/取消开机自启
- 退出

## 构建

在项目根目录运行：

```bat
build_windows_app.bat
```

或手动运行：

```bat
.venv\Scripts\pyinstaller.exe --clean --noconfirm packaging\windows\voice-keyboard-tray.spec
```

## 运行

```bat
dist\VoiceKeyboard\VoiceKeyboard.exe
```

配置文件仍在：

```text
%USERPROFILE%\.voice-keyboard\config.yaml
```

## 注意

- 当前固定使用 PTT 模式；Python 3.13+ 下暂不依赖 webrtcvad。
- 微信 / 钉钉 / Electron 应用如拦截 Unicode 输入，可在配置中设置 `typing.method: clip`。
- 中文键盘右 Alt 有时是 `alt_gr`，本机当前听写键配置为 `shift_r`。

## 企业安全软件拦截

PyInstaller 生成的无签名托盘程序常被企业安全软件拦截，原因通常包括：

- exe 未做代码签名
- 程序常驻托盘后台运行
- 使用全局键盘监听（PTT 热键）
- 调用 Win32 输入/窗口 API
- 打包器产物特征被风控命中

这不是代码一定有恶意，而是行为特征命中了安全策略。企业电脑推荐：

1. 使用源码 + 虚拟环境运行：

   ```bat
   start_tray_windows.bat
   ```

2. 如必须使用 exe，把以下路径和构建后的 SHA256 提交给 IT 做白名单：

   ```text
   dist\VoiceKeyboard\VoiceKeyboard.exe
   ```

3. 面向正式分发时，应使用企业代码签名证书签名 exe，再交给安全软件管理员放行。

SHA256 可用以下命令生成：

```powershell
Get-FileHash -Algorithm SHA256 dist\VoiceKeyboard\VoiceKeyboard.exe
```
