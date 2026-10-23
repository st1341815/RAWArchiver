# RAW 归档 · macOS 版（MacBook / Apple Silicon）

把 RAW 归档做成原生 Mac 应用：双击打开的窗口程序，**核心逻辑与 fnOS 版完全同一份**
（`fnos/rawarchiver/app/scripts/raw_archiver.py`，构建时同步，零漂移）。

## 下载使用（普通用户）

1. 到 [Releases](https://github.com/st1341815/RAWArchiver/releases) 下载 `RawArchiver-macOS-<版本>-arm64.zip`
2. 解压，把 `RawArchiver.app` 拖进「应用程序」（或任意位置双击）
3. **首次打开**：因未做 Apple 开发者公证，直接双击会被 Gatekeeper 拦——
   **右键 RawArchiver.app → 打开 → 再点「打开」**（只需一次，之后可正常双击）
4. 插入 SD 卡 / U 盘，打开应用 → 「选择源目录」（macOS 系统目录选择框，选 `/Volumes/卡名/DCIM`）
   → 「选择目标目录」→ 预览 → 开始

> 若提示「已损坏」：终端跑 `xattr -cr /Applications/RawArchiver.app` 后再打开
> （浏览器下载的 zip 偶发携带扩展属性）。

### 与 fnOS 版的差异（行为一致，仅平台适配）

| 项 | macOS 版 | fnOS 版 |
| --- | --- | --- |
| 界面 | pywebview 原生窗口（同一份 web UI） | 飞牛统一网关微应用 |
| 目录选择 | macOS 系统选择框（NSOpenPanel） | 飞牛 pickSharedFile 弹窗 |
| 外接设备 | `/Volumes/*`（SD 卡 / U 盘 / 移动硬盘） | `/vol00/*` |
| 任务状态目录 | `~/Library/Application Support/RawArchiver/.rawarchiver/` | `$TRIM_PKGVAR/.rawarchiver/` |
| 日志与报告 | `<输出目录>/log/`（同 fnOS） | `<输出目录>/log/` |
| ExifTool | 随包 perl 脚本，走系统 `perl` | 随包 perl 脚本 |
| 源目录 | **只读，零新增文件**（同 fnOS） | 同 |

关闭窗口即退出应用；**归档任务是独立子进程，关窗口后仍会继续完成**
（日志与报告照写到 `<输出目录>/log/`），重开应用可重新预览/补清源。

「内部暂存」：SD 卡源推荐勾选（先完整拷到启动盘再归档，中途拔卡不损数据）；
空间紧张可取消勾选（直接从卡上读）。

## 本地构建（开发者）

要求：macOS（Apple Silicon）+ 系统 python3（`xcode-select --install` 后自带）。

```sh
cd macos
bash build.sh          # 产物 dist/RawArchiver.app + dist/RawArchiver-macOS-<版本>-arm64.zip
```

build.sh 做的事：同步 fnOS 平台副本的核心/前端 → 下载 ExifTool 13.00 → venv 依赖 →
icns → PyInstaller（arm64 onedir + .app）→ CLI 自测（doctor/preview）→ ad-hoc 签名 → zip。

## CI 构建（推荐）

GitHub Actions（`.github/workflows/build-macos.yml`）在 `macos-14`（M1）runner 上自动构建：

- push 改动 `macos/`、前端、核心脚本 → 自动构建，产物进 Artifacts
- 手动 **Run workflow** 并填 `release_tag`（如 `macos-v1.0.18`）→ 构建成功后自动创建/更新对应 Release 并上传 zip 附件

## 结构

```
macos/
├── app/
│   ├── main_mac.py      # 入口：无参=GUI（pywebview）；带参=CLI 转发 core
│   ├── server_mac.py    # 127.0.0.1 TCP API 服务（token 鉴权；fnos server.py 的平台适配版）
│   ├── scripts/         # ← 构建时从 fnOS 副本同步（不进 git）
│   ├── www/             # ← 同上（同一份 index.html，含 macos 分支）
│   └── vendor/exiftool/ # ← 构建时下载
├── RawArchiver.spec     # PyInstaller 配置（arm64 / windowed / hiddenimports）
├── make_icns.py         # 源图 → iconset（fnos/icon-source.png）
├── build.sh             # 一键构建
└── tests/               # 本地逻辑测试（平台无关部分，Linux 也能跑）
```

关键设计：**核心脚本以源文件形态打进 `Contents/Resources/scripts/`，运行时动态 import**
——`__file__` 的相对路径逻辑（找 vendor/exiftool、state_root 回退）与 fnOS 版完全一致，
核心一行不改。frozen 下归档 worker = 应用二进制自身（`main_mac.py` 判定 argv 非空 → 转发 CLI），
`server_mac.worker_cmd()` 负责两种形态（frozen / 开发）的切换。
