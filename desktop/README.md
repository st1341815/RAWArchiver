# RAW 归档 · 桌面原生 GUI（macOS SwiftUI / Windows WPF）

桌面版（macOS / Windows）采用**系统原生 GUI**，不含任何 WebView / HTML 渲染。
归档逻辑全部在 Python 核心引擎 `raw_archiver.py`（三平台唯一真源），GUI 只负责界面，
通过**子进程 + NDJSON（stdin/stdout）**调用它。

## 架构

```
┌─────────────────────┐  ┌──────────────────────┐
│  macOS SwiftUI (.app)│  │  Windows WPF (.exe)   │   ← 原生 GUI，只做界面
└──────────┬──────────┘  └──────────┬───────────┘
           │  子进程 stdin/stdout   │
           │      NDJSON 协议       │
           └──────────┬─────────────┘
                      ▼
        ┌─────────────────────────────┐
        │ core-ipc / ipc_main.py --ipc │   ← Python 核心 IPC 服务
        │  preview/start/cancel/…      │      （worker 子进程跑归档）
        └──────────┬──────────────────┘
                   ▼
        ┌─────────────────────────────┐
        │ raw_archiver.py（零改动）    │
        └─────────────────────────────┘
```

- **通信契约**：见 [`core-ipc/PROTOCOL.md`](core-ipc/PROTOCOL.md)
- **核心引擎**：`fnos/rawarchiver/app/scripts/raw_archiver.py`（三平台唯一真源，GUI 不重写任何归档逻辑）
- **进度**：GUI 启动 worker 子进程后，由 IPC 服务轮询 `state.json` 推送 progress/done 事件

## 构建

| 平台 | 命令 | 产物 |
| --- | --- | --- |
| macOS | `cd desktop/macos && bash build.sh` | `dist/RawArchiver.app` + `RawArchiver-macOS-1.1.0-arm64.dmg` |
| Windows | `cd desktop/windows && bash build.sh` | `dist/publish/RawArchiver.exe` + `RawArchiver-windows-1.1.0-x64.zip` |

均由 GitHub Actions（`build-macos.yml` / `build-windows.yml`）自动构建/发布。

## 目录

```
desktop/
├── core-ipc/        Python 核心 IPC 服务 + 协议 + 端到端测试
├── macos/           SwiftUI 工程（SPM）：Sources/RawArchiver/*.swift + build.sh
└── windows/         WPF 工程（.NET 8）：RawArchiver/* + build.sh + tests/smoke.py
```

## 依赖（打包时内嵌）

- macOS：SwiftUI（系统）+ Python CLI（PyInstaller onedir，含 ExifTool perl 脚本）
- Windows：WPF（.NET 8 self-contained）+ Python CLI（PyInstaller onedir，含 exiftool.exe）
