# RAW 归档（RAW Archiver）

> **RAW Archiver** — a self-hosted **photo / video organizer for NAS**. It scans camera cards or folders, reads **EXIF capture dates**, and archives **RAW / JPG / video** into date-based folders (`YYYYMMDD/`, optionally `Brand/YYYYMMDD/`). Built as a **fnOS (飞牛) fnpack app**; the core script also runs as a plain **Python CLI**.
>
> - **Search keywords**: photo organizer · RAW workflow · EXIF date sorting · digital asset management (DAM) · NAS photo backup · camera card offload · 飞牛 fnOS 相册整理 · RAW 归档
> - **Formats**: NEF/NRW/CR2/CR3/CRW/ARW/SRF/SR2/RAF/ORF/RW2/DNG/PEF · JPG/JPEG · MP4/MOV/MTS/M2TS/AVI/MKV/3GP/MPG/MPEG/WMV/FLV/M4V/TS/MOD/MXF
> - **Brands**: Canon · Nikon · Sony · Fujifilm · Hasselblad · Leica · Olympus · Panasonic · Pentax/Ricoh · Sigma · Phase One · Samsung · Apple · Huawei · Xiaomi · DJI · GoPro
> - **Safety**: source is **read-only** · photos without EXIF date are **skipped** · resumable · optional source cleanup after verified copy · machine-readable JSON report
> - **Download**: [Releases](https://github.com/st1341815/RAWArchiver/releases)
> - **三平台产物统一在版本 Release 里**（如 `v1.1.0`）：`.fpk` = fnOS 应用包 · `.dmg` = macOS 安装包 · `.zip` = Windows 便携包
> - **macOS 版**（MacBook / Apple Silicon M 系列，**原生 SwiftUI**）：下载 `RawArchiver-macOS-<版本>-arm64.dmg` → 双击挂载 → 把 `RawArchiver.app` 拖进「应用程序」→ **首次打开右键 → 打开**（未做 Apple 公证）
> - **Windows 版**（Win10/11 x64，**原生 WPF**）：下载 `RawArchiver-windows-<版本>-x64.zip` → 解压双击 `RawArchiver.exe`（免安装便携版）

相机照片/视频按**拍摄日期（EXIF）**归档到 NAS 的工具。设计准则：**源只读、目标可写、可断点续跑、可清源**。
照片读不到 EXIF 一律视为未知并**跳过**；视频可用文件时间兜底。支持 RAW（NEF/CR2/ARW…）/ JPG / 视频。

**已支持设备**（读 EXIF `Make` 识别品牌，「按品牌分层」时按品牌建目录）：
- **相机**：佳能 Canon、尼康 Nikon、索尼 Sony、富士 Fujifilm、哈苏 Hasselblad、徕卡 Leica 等
- **运动相机**：大疆 DJI、GoPro 等
- 品牌表另含：奥林巴斯 Olympus、松下 Panasonic、宾得/理光 Pentax、适马 Sigma、飞思 PhaseOne、三星 Samsung、Apple、华为 Huawei、小米 Xiaomi
- 未收录的机型也能归档（按拍摄日期分目录），只是「按品牌分层」不会细分品牌

**支持格式**

| 类别 | 扩展名 |
| --- | --- |
| RAW | `.nef` `.nrw` `.cr2` `.cr3` `.crw` `.arw` `.srf` `.sr2` `.raf` `.orf` `.rw2` `.dng` `.pef` |
| 照片 | `.jpg` `.jpeg` |
| 视频 | `.mp4` `.mov` `.mts` `.m2ts` `.avi` `.mkv` `.3gp` `.mpg` `.mpeg` `.wmv` `.flv` `.m4v` `.ts` `.mod` `.mxf` |

**手机照片**：手机拍的 **JPG 照片与视频**同样可归档（Android 多数直接出 JPG）。**iPhone 默认的 HEIC / HEIF 暂不支持**——需在手机端改为兼容格式（设置 → 相机 → 格式 → 兼容性最佳）或先转成 JPG；不在上述清单内的扩展名不会被扫描，也就不会归档。

## 目录结构

```
RAWArchiver/          项目本体（源码 + 文档 + 更正资料）
├── scripts/raw_archiver.py   核心脚本（仅标准库；ExifTool 随包）
├── app/rawarchiver/          DSM（群晖）Web 面板 + CGI 入口
├── agent/agent.py            本机 FastAPI 版（8765）
├── pkg/                      DSM SPK / fnOS FPK 打包源
├── vendor/exiftool/          随包 ExifTool
└── corrections/              更正版开发说明 PDF + 核对报告 + 差异清单

fnos/                 fnOS（飞牛）应用包工程
├── rawarchiver/              打包源（manifest / config / wizard / cmd / app）
├── dist/rawarchiver.fpk      打包产物
├── build.sh                  一键出包（fnpack）
└── gen_icons.py              生成图标

desktop/              桌面原生 GUI（macOS SwiftUI / Windows WPF，共享 Python 核心 IPC）
├── core-ipc/                 Python 核心引擎 IPC 服务（NDJSON；Swift/WPF 通过子进程调用）
│   ├── ipc_main.py           --ipc 模式（preview/start/cancel/cleanup/rollback/doctor + 进度事件流）
│   └── PROTOCOL.md           通信契约
├── macos/                    macOS 原生应用（SwiftUI + SPM）
│   ├── Sources/RawArchiver/  主界面 / IPC 客户端 / 预览表 / 进度
│   └── build.sh              swift build + PyInstaller CLI + 组装 .app + dmg
└── windows/                  Windows 原生应用（WPF + .NET 8）
    ├── RawArchiver/          MainWindow / IpcClient
    └── build.sh              dotnet publish + PyInstaller CLI + zip
```

> 核心引擎 `fnos/rawarchiver/app/scripts/raw_archiver.py` 是三平台唯一真源；
> 桌面 GUI（Swift/WPF）不实现任何归档逻辑，只负责界面 + 通过 IPC 调用 Python 核心。

## 构建

- **fnOS 应用包（.fpk）**
  ```
  cd fnos && bash build.sh          # 产出 fnos/dist/rawarchiver.fpk
  ```
- **macOS 原生应用（SwiftUI .app，需在 Apple Silicon Mac 上构建）**
  ```
  cd desktop/macos && bash build.sh # 产出 desktop/macos/dist/RawArchiver.app + RawArchiver-macOS-<版本>-arm64.dmg
  ```
  或由 GitHub Actions（`build-macos.yml`，macos-14 arm64 runner）自动构建/发布。
- **Windows 原生应用（WPF .exe，Win10/11 x64）**
  ```
  cd desktop/windows && bash build.sh  # 产出 RawArchiver.exe + RawArchiver-windows-<版本>-x64.zip
  ```
  或由 GitHub Actions（`build-windows.yml`，windows-latest runner）自动构建/发布。
- **本体：DSM 套件（SPK）/ fnOS 包（FPK）/ 源码包**
  ```
  cd RAWArchiver
  sh scripts/fetch_exiftool.sh
  sh build_all.sh
  ```

## 发版（GitHub Release）规范

> 以下是**固定规范**，每次发版照做，不要再临时决定命名。

1. **版本号同步**：`fnos/rawarchiver/manifest` 的 `version` + `changelog`、`app/server.py` 的 `VERSION`、`app/api/index.cgi` 的 `version`、`app/www/index.html` 的 `<h1><small>vX.Y.Z`、本 README 的「版本」段 —— 一处都不能漏。**内容变了就换版本号**（同一个版本号不允许对应两份不同内容的包）。
2. **构建**：`cd fnos && bash build.sh` → 产出 `fnos/dist/rawarchiver.fpk`（**仓库内路径固定不带版本号**，`build.sh` 与 `app install-fpk` 都依赖它；构建结束会打印本次应使用的 Release 附件名）。
3. **Release 附件名固定为** `rawarchiver-<版本>.fpk`（例：`rawarchiver-1.0.16.fpk`）。**不允许**再上传不带版本号的 `rawarchiver.fpk` —— 多版本混在一起，下载下来分不清。
4. **Release 正文**：写清本次更新内容；引用附件名时必须带版本号（正文里保留 `fnos/dist/rawarchiver.fpk` 这个仓库内路径的写法，别一起改掉）。
5. **替换 / 改名已有附件时的安全顺序**：`下载旧附件 → 上传新名 → 回读 sha256 校验一致 → 才删旧名`。不要先删后传，否则中途失败 Release 会没有安装包。
6. **推完自检**：远端 `main` 与本机 `HEAD` 是否同一个 commit（同一个 commit 即整棵树逐字节相同）；Release 附件大小与 `fnos/dist/rawarchiver.fpk` 一致；下载一次比 sha256。
7. 仓库为 **public**，下载无需登录。

## 加入 FnDepot 外部源（可自动更新）

仓库根目录的 `fnpack.json` 是按 **FnDepot 外部应用源 V2** 规范编写的源文件，可直接在 FnDepot 客户端里添加：

- **GitHub 仓库模式**：`https://github.com/st1341815/RAWArchiver`
- **JSON 直链模式**：`https://cdn.jsdelivr.net/gh/st1341815/RAWArchiver@main/fnpack.json`

源里已填好：`appname=rawarchiver`、`platform=all`、`categories=["影音娱乐"]`、`run_as=package`、`install_type=""`、`is_docker=false`，图标走 jsDelivr（国内可达），安装包走该版本 GitHub Release 附件并带 `sha256` + `size`。

**以后发版要同步改 `fnpack.json`**：在 `releases` 下新增 `"<新版本>"` 节点，填该版本 FPK 的 `download_url`、`sha256`、`size`（旧版本条目**保留**——规范要求已发布的「版本 + 架构」文件不可变，不要静默替换同版本包）。

## 安装与使用（fnOS）

1. 应用中心 → 手动安装 → 选 `fnos/dist/rawarchiver.fpk`。
2. 安装后到「应用中心 → RAW 归档 → 设置 → **授权目录**」授权**源目录（读）**与**归档目录（读+写）**；
   否则以包用户运行时读写共享目录会 `Permission denied`。
3. 打开应用 → 选择源/输出目录 → **预览**（文件清单可折叠）→ 确认并开始。

## 盘面约定（v1.0.14 起）

| 位置 | 内容 |
| --- | --- |
| 源目录 | **只读**，归档过程不产生任何文件或文件夹 |
| `<输出目录>/` | 只落归档照片/视频（按 `YYYYMMDD` 或 `品牌/YYYYMMDD`） |
| `<输出目录>/log/` | 运行日志 `rawarchiver_<任务ID>.log` + 下游报告 `_report_<任务ID>.json` |
| 应用数据目录 `$TRIM_PKGVAR/.rawarchiver/` | 任务态 `tasks/<任务ID>/{state.json,cancel,stage/}`（断点续跑、取消、内部暂存） |

> 「内部暂存」放在应用数据目录，所以暂存会占用**应用所在存储卷**的空间（临时占用 ≈ 卡容量，跑完自动清理）。
> 卡容量大于该卷可用空间时，请取消勾选「内部暂存」。

## 版本

- 当前 `1.1.0`（**桌面 GUI 重构为原生窗口**：macOS 改用 SwiftUI、Windows 改用 WPF，弃用 pywebview/内嵌 WebView；功能与 1.0.18 等价。核心引擎经新增的 `desktop/core-ipc`（NDJSON）被原生 GUI 调用，`raw_archiver.py` 逻辑不变）。
- `1.0.18`（**小修**：飞牛外接存储 `/vol00` 正确识别为可移动介质；move 模式清源失败时日志说明原因并给出「手动删除或改用复制模式」的指引）。
- **同版本新增 macOS 平台**：`RawArchiver.app`（Apple Silicon / M 系列，pywebview 原生窗口 + 同一份核心/前端），Release 附件 `RawArchiver-macOS-1.0.18-arm64.dmg`。核心引擎零改动，仅新增平台壳（`macos/`）。
- **同版本新增 Windows 平台**：`RawArchiver.exe`（Win10/11 x64，pywebview EdgeChromium 窗口 + 同一份核心/前端），Release 附件 `RawArchiver-windows-1.0.18-x64.zip`；core 的 `is_removable` 增加 Windows 盘符（GetDriveTypeW）识别，纯增量、POSIX 无影响。
- `1.0.17`（**修复移动模式误报 + 日志增强**：move 模式源目录不可删时不再「文件已复制却报全部失败」，归档统一 copy2、清源失败仅告警；运行日志逐文件记录源→目标映射并输出成功/失败/跳过总数与完成时间）。
- `1.0.16`（**软件介绍补全**：已支持相机/运动相机品牌 + 支持格式清单 + 手机照片说明；应用中心 desc、应用内页头、README 三处同步）。
- `1.0.15`（软件介绍补充「已支持设备」品牌清单）。
- `1.0.14`（**盘面整理**：任务态从输出目录迁到应用数据目录 `$TRIM_PKGVAR/.rawarchiver/`，日志与报告统一落 `<输出目录>/log/`，源目录与输出目录根部零残留；目录选择按钮文案改为「选择源目录」/「选择目标目录」）。
- `1.0.13`：改造成飞牛统一网关微应用，目录选择走飞牛 JS SDK 系统内部弹窗（`pickSharedFile`）。
- 核心与 fnOS 包的最新改动见 `RAWArchiver/CHANGELOG.md`。

---

> 说明：`RAWArchiver/`（本体）与 `fnos/`（应用包）是同一产品的两部分；核心脚本以 `RAWArchiver/scripts/raw_archiver.py` 为准，`fnos/rawarchiver/app/scripts/raw_archiver.py` 为其在 fnOS 包内的拷贝。
