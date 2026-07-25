# HarmonyOS 构建、签名与真机调试

## 已验证环境

- macOS（Apple Silicon）
- DevEco Studio 6.1.0 Release
- HarmonyOS SDK 6.1.0 / API 23
- Hvigor 6.23.7
- HarmonyOS 6.1 手机模拟器和真机

其他版本可能可以工作，但提交 Issue 时请注明 DevEco Studio、SDK/API 和设备版本。

## DevEco Studio 构建

1. 克隆仓库。
2. 使用 DevEco Studio 打开 `harmony-app/`，不要打开仓库根目录。
3. 等待 SDK、ohpm 和 Hvigor 同步完成。
4. 选择 `entry` 模块。
5. 运行 **Build → Build Hap(s)/APP(s) → Build Hap(s)**。

未配置签名时，输出通常位于：

```text
harmony-app/entry/build/default/outputs/default/entry-default-unsigned.hap
```

## 命令行构建

仓库脚本默认使用 `/Applications/DevEco-Studio.app` 内置的 Node、JDK 和 SDK：

```bash
./tools/harmony/build-debug.sh
```

核心命令为：

```bash
hvigorw assembleHap \
  --mode module \
  -p module=entry@default \
  -p product=default \
  -p buildMode=debug \
  --no-daemon
```

如果 DevEco Studio 安装在其他位置，请调整脚本中的 `DEVECO_APP`。

## 本机签名

公开仓库故意不包含签名配置、证书、Profile、密钥库或口令。每位开发者需要生成自己的
签名：

1. 登录 DevEco Studio 中的华为开发者账号。
2. 打开 **File → Project Structure → Signing Configs**。
3. 选择 `default` 产品并启用自动签名。
4. 确认 Bundle Name 为 `com.laborlaw.aiassistant`，或改成你拥有的唯一包名。
5. 点击 **Apply / OK**，等待 Profile 与证书生成。

DevEco 可能把本机绝对路径和口令写入 `harmony-app/build-profile.json5`。提交代码前
必须移除 `signingConfigs` 和产品中的 `signingConfig`；证书与密钥文件也不得进入 Git。

## 模拟器运行

1. 在 Device Manager 创建 HarmonyOS 6.1 Phone 设备。
2. 推荐至少 4 GB RAM 和 6 GB 存储。
3. 启动模拟器，等待 DevEco 顶部设备列表出现设备。
4. 选择设备并运行 `entry`。

内置索引约 52 MiB，首次启动需要解析本地 JSON；模拟器性能明显低于真机时请耐心等待。

## 真机运行

1. 将手机升级到工程兼容的 HarmonyOS 版本。
2. 开启开发者模式和 USB 调试。
3. 用 USB 数据线连接 Mac，并在手机上确认调试授权。
4. 在 DevEco 顶部设备列表中选择手机。
5. 确认已配置本机签名，点击运行。

日志出现以下阶段即表示安装和拉起成功：

```text
bm install
aa start -a EntryAbility -b com.laborlaw.aiassistant -m entry
successfully launched
```

安装完成后可以拔线独立使用。后续重新调试、查看日志或覆盖安装时需要再次连接。

## HDC 命令

HDC 位于 DevEco SDK toolchains 目录。常用命令：

```bash
hdc list targets
hdc install -r path/to/entry-default-signed.hap
hdc shell aa start \
  -a EntryAbility \
  -b com.laborlaw.aiassistant \
  -m entry
```

具体路径随 DevEco Studio 版本而变化，优先使用 IDE 自动调用。

## 常见问题

### “没有要运行的内容”

先完成工程同步，确认选择的是 `entry` 模块和可运行设备；必要时重新打开
`harmony-app/`。

### 签名或 Profile 错误

不要使用其他人的 `.p12/.p7b/.cer`。在 Project Structure 中删除失效配置后重新启用
自动签名，并确保账号、设备和包名匹配。

### 真机安装后 API 配置丢失

普通覆盖安装通常保留数据；卸载应用会清除 Preferences 和 Asset Store 中的配置。
不要把真实 API Key 写入代码来规避重新配置。

### 构建很慢或内存占用高

清理 `entry/build/` 后重新同步。内置索引较大，资源打包和首次加载耗时会高于空工程。
