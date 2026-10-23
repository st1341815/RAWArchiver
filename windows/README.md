# RAW 归档 · Windows 版（Win10/11 x64 便携版）

把 RAW 归档做成 Windows 桌面应用：双击 `RawArchiver.exe` 打开的窗口程序，
**核心逻辑与 fnOS/macOS 版完全同一份**（`fnos/rawarchiver/app/scripts/raw_archiver.py`，构建时同步，零漂移）。

## 下载使用（普通用户）

1. 到 [Releases](https://github.com/st1341815/RAWArchiver/releases) 下载 `RawArchiver-windows-<版本>-x64.zip`
2. 解压到任意目录（如 `D:\RawArchiver`），双击里面的 **RawArchiver.exe**
3. 首次运行若 **Windows Defender / SmartScreen 拦截**（PyInstaller 打包的常见误报）：
   点「**更多信息 → 仍要运行**」，或把该文件夹加入杀软白名单
4. 插入 SD 卡 / U 盘 → 「选择源目录」（系统文件夹选择框，选 `D:\DCIM`）→「选择目标目录」→ 预览 → 开始

> 免安装、绿色便携：整个文件夹拷到别的电脑也能用，不写注册表。

### 与 macOS/fnOS 版的差异（行为一致，仅平台适配）

| 项 | Windows 版 | macOS 版 | fnOS 版 |
| --- | --- | --- | --- |
| 界面 | pywebview（EdgeChromium / WebView2，Win11 自带） | pywebview（WKWebView） | 飞牛网关微应用 |
| 目录选择 | 系统文件夹选择框（IFileDialog） | NSOpenPanel | pickSharedFile |
| 外接设备 | 盘符（U 盘/读卡器/移动硬盘，自动识别可移动盘） | `/Volumes/*` | `/vol00/*` |
| 任务状态目录 | `%APPDATA%\RawArchiver\.rawarchiver\` | `~/Library/Application Support/RawArchiver/` | `$TRIM_PKGVAR/.rawarchiver/` |
| 日志与报告 | `<输出目录>\log\`（同） | `<输出目录>/log/` | `<输出目录>/log/` |
| ExifTool | 随包 `exiftool.exe`（独立可执行，无需 perl） | 随包 perl 脚本 | 随包 perl 脚本 |
| 源目录 | **只读，零新增文件**（同） | 同 | 同 |

关闭窗口即退出应用；**归档任务是独立子进程，关窗口后仍会继续完成**（日志与报告照写到 `<输出目录>\log\`）。

「内部暂存」：SD 卡源推荐勾选（先完整拷到系统盘再归档，中途拔卡不损数据）；
空间紧张可取消勾选（直接从卡上读）。

## 本地构建（开发者，Windows + git-bash 或 CI）

```sh
cd windows
bash build.sh       # 产物 dist/RawArchiver/ + dist/RawArchiver-windows-<版本>-x64.zip
```

## CI 构建（推荐）

GitHub Actions（`.github/workflows/build-windows.yml`）在 `windows-latest` runner 上自动构建：

- push 改动 `windows/`、前端、核心脚本 → 自动构建，产物进 Artifacts
- 手动 **Run workflow** 填 `release_tag`（如 `windows-v1.0.18`）→ 自动发布 Release `.zip`

## 结构

```
windows/
├── app/
│   ├── main_win.py      # 入口：无参=GUI（pywebview EdgeChromium）；带参=CLI 转发 core
│   ├── server_win.py    # 127.0.0.1 TCP API 服务（token 鉴权；平台适配版）
│   ├── scripts/         # ← 构建时从 fnOS 副本同步（不进 git）
│   ├── www/             # ← 同上（同一份 index.html，含 windows 分支）
│   └── vendor/exiftool/ # ← 构建时下载 exiftool.exe
├── RawArchiver.spec     # PyInstaller（onedir + 双 exe：GUI console=False / CLI console=True）
├── make_icon.py         # 源图 → .ico
├── build.sh             # 一键构建
└── tests/smoke.py       # CI smoke test（GUI 服务 + API 全链路）
```

关键设计：核心脚本以源文件形态打进 `_internal/scripts/`，运行时动态 import——与 fnOS/macOS 版零漂移。
**双 exe 的原因**：Windows 下 `console=False`（不弹黑窗）的程序 `sys.stdout` 为 None，core 的 `print`
（日志）会崩；归档 worker 因此用 `console=True` 的 `RawArchiver-cli.exe`（能正常输出日志到
`<输出目录>\log\rawarchiver_<任务ID>.log`），GUI 主程序仍是无黑窗的 `RawArchiver.exe`。
