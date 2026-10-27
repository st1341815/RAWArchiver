# RAW 归档（RAW Archiver）

> **RAW Archiver** — a self-hosted **photo / video organizer for NAS**. It scans camera cards or folders, reads **EXIF capture dates**, and archives **RAW / JPG / video** into date-based folders (`YYYYMMDD/`, optionally `Brand/YYYYMMDD/`). Built as a **fnOS (飞牛) fnpack app**; the core script also runs as a plain **Python CLI**.
>
> - **Search keywords**: photo organizer · RAW workflow · EXIF date sorting · digital asset management (DAM) · NAS photo backup · camera card offload · 飞牛 fnOS 相册整理 · RAW 归档
> - **Formats**: NEF/NRW/CR2/CR3/CRW/ARW/SRF/SR2/RAF/ORF/RW2/DNG/PEF · JPG/JPEG · MP4/MOV/MTS/M2TS/AVI/MKV/3GP/MPG/MPEG/WMV/FLV/M4V/TS/MOD/MXF
> - **Brands**: Canon · Nikon · Sony · Fujifilm · Hasselblad · Leica · Olympus · Panasonic · Pentax/Ricoh · Sigma · Phase One · Samsung · Apple · Huawei · Xiaomi · DJI · GoPro
> - **Safety**: source is **read-only** · **already-archived files are skipped automatically**（重复归档防护）· photos without EXIF date are **skipped** · resumable · optional source cleanup after verified copy · machine-readable JSON report
> - **维护状态**：**fnOS `.fpk`（v1.0.22）为当前主线**，桌面原生版（macOS/Windows，v1.1.1）随同发布；`RAWArchiver/` 本体（DSM 套件 / 源码包，v1.0.0）**已冻结存档，不再维护、不再发布**
> - **Download**: [Releases](https://github.com/st1341815/RAWArchiver/releases)
> - **产物按版本线发布**：fnOS 应用包走 `v1.0.x`（如 `v1.0.20`，只含 `.fpk`）；桌面原生版走 `v1.1.x`（如 `v1.1.1`，只含 `.dmg` / `.exe`）。按平台选对应版本下载
> - **macOS 版**（MacBook / Apple Silicon M 系列，**原生 SwiftUI**）：下载 `RawArchiver-macOS-<版本>-arm64.dmg` → 双击挂载 → 把 `RawArchiver.app` 拖进「应用程序」→ **首次打开右键 → 打开**（未做 Apple 公证）
> - **Windows 版**（Win10/11 x64，**原生 WPF**）：下载 `RawArchiver-windows-<版本>-x64.exe` → **双击即用**（单文件免安装，无需解压、无需安装 .NET/Python）

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

## 重复归档防护（Dup Guard）

> 场景：卡上的照片不能删（或忘记删），下次插卡再归档 → 同一批照片被再处理一遍，目标目录里长出 `_1/_2/_3` 副本。

现在系统**记得「处理过」这件事**：每次归档成功写入一份台账（`<应用数据目录>/.rawarchiver/ledger.sqlite3`），
下次预览就会把它们标出来并**默认跳过**；要重处理必须显式确认。

**三级证据（成本递增，命中即停）**

| 级别 | 判据 | 额外读盘 |
| --- | --- | --- |
| L1 元数据 | 文件名 + 大小 + mtime 命中台账，且归档文件仍在 | 无（只 stat） |
| L2 内容 | 同名同大小 → 与归档文件比对内容（默认头尾各 256KB） | 512 KB |
| L3 现场 | 当前选项算出的目标路径已存在 → 比对内容（台账丢失时的兜底） | 1 MB |

**行为约定**

- 默认**跳过已归档**；预览里显示「已归档 N 个（约 X GB）」并可展开清单（原归档位置 / 时间 / 判定依据）。
- 勾选「重新处理已归档文件」后才会重做，且**二次确认**；GUI/API 侧还要求预览签发的 `dupGuard`（30 分钟有效，绑定源/输出/选项），直接调 API 绕不过去。
- **跨输出目录不算重复**：同一张卡归档到另一个目录视为新文件（允许有意做第二份）。
- `size` 相同不等于同一张照片：所有「靠大小判等」的路径都做**内容复核**，判不准一律按新文件处理（宁可重复，不可丢失）。
- 内容复核强度可切：默认 `sampled`（头尾各 256KB），可开「全文件校验」（`--dup-hash full`）。
- 回滚过的任务，其台账记录自动失效，下次会重新归档。
- 台账为空/丢失时，自动从 `<输出目录>/log/_report_*.json` 回填，升级后第一次运行也不会重新堆副本。

## 目录结构

```
RAWArchiver/          项目本体（v1.0.0 存档线：DSM 套件 / 源码包 / 更正资料）
├── scripts/raw_archiver.py   核心脚本（仅标准库；ExifTool 随包）
├── app/rawarchiver/          DSM（群晖）Web 面板 + CGI 入口（存档，已冻结）
├── agent/agent.py            本机 FastAPI 版（8765）
├── pkg/                      DSM SPK 打包源（存档；fnOS 包见 fnos/）
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
  cd desktop/windows && bash build.sh  # 产出单文件 RawArchiver-windows-<版本>-x64.exe
  ```
  或由 GitHub Actions（`build-windows.yml`，windows-latest runner）自动构建/发布。
- **fnOS 应用包（.fpk）—— 唯一在维护的 NAS 发行物**
  ```
  cd fnos && bash build.sh            # 产出 fnos/dist/rawarchiver.fpk，并打印本次 Release 附件名
  ```
- ~~**本体：DSM 套件（SPK）/ 源码包**~~ —— **已冻结存档，不再维护**；`RAWArchiver/build_all.sh` 仅作历史参考，产物不再更新、不再发布。

## 日常维护（fnOS `.fpk` 线）

> `RAWArchiver/`（DSM/源码包）已冻结；**以后只维护 `fnos/`**。改一处走完这四步：

1. **改代码** —— 全在 `fnos/rawarchiver/app/`：
   | 文件 | 职责 |
   | --- | --- |
   | `scripts/raw_archiver.py` | 核心（扫描 / EXIF / 去重台账 / 归档 / 清源 / 报告），只依赖标准库 |
   | `server.py` | 飞牛统一网关微应用的后端（unix socket，静态 www + `/api`） |
   | `api/index.cgi` | 传统 CGI 通道（与 server.py 的动作保持一致） |
   | `www/index.html` | 单页界面（预览 / 进度 / 目录选择 / 确认门） |

2. **自检**（必须过再往下走）
   ```
   PYTHONPATH= python3 fnos/selftest_dupguard.py     # → SELFTEST_DUPGUARD_OK checks=32
   python3 -m py_compile fnos/rawarchiver/app/server.py
   python3 -c "import ast;ast.parse(open('fnos/rawarchiver/app/api/index.cgi',encoding='utf-8').read())"
   bash -n fnos/build.sh
   ```
   改了界面想先看效果：`PYTHONPATH= python3 fnos/_mock_server.py 8777` 然后开 `http://127.0.0.1:8777/app/rawarchiver/`
   （mock 服务直连真实 core，不需要装到 NAS）。

3. **打包** —— 先 bump 五处版本号（`manifest` / `server.py` VERSION / `api` version / `www` 的 `<small>vX.Y.Z` /
   `raw_archiver.py` 的 `APP_VER`），再 `cd fnos && bash build.sh`，产出 `fnos/dist/rawarchiver.fpk`。
   真机验证可用 `fnos/_dgcheck.py`（临时容器直连网关 socket，13 项冒烟，结果用文件名回写）。

4. **发版** —— `git tag vX.Y.Z` 并推送；Release 附件名固定 `rawarchiver-X.Y.Z.fpk`；
   `fnpack.json` 在 `releases` 下**新增**节点（`download_url` / `sha256` / `size`），旧节点保留。

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
   > 这一步是 **fnOS 系统侧授权**（给包用户打 ACL），应用自己不维护授权白名单 —— 应用侧只要系统放行就能读写。
   > 读外接存储（SD/TF/U 盘，`/vol00`，FAT 挂载）另需：「文件管理 → 设置 → 外接存储权限 → 所有账户可见」。
3. 打开应用 → 选择源/输出目录 → **预览**（文件清单可折叠）→ 确认并开始。

## 盘面约定（v1.0.14 起）

| 位置 | 内容 |
| --- | --- |
| 源目录 | **只读**，归档过程不产生任何文件或文件夹 |
| `<输出目录>/` | 只落归档照片/视频（按 `YYYYMMDD` 或 `品牌/YYYYMMDD`） |
| `<输出目录>/log/` | 运行日志 `rawarchiver_<任务ID>.log` + 下游报告 `_report_<任务ID>.json` |
| 应用数据目录 `$TRIM_PKGVAR/.rawarchiver/` | 任务态 `tasks/<任务ID>/{state.json,cancel,stage/}`（断点续跑、取消、内部暂存）+ **处理台账 `ledger.sqlite3`**（重复归档防护） |

> 「内部暂存」放在应用数据目录，所以暂存会占用**应用所在存储卷**的空间（临时占用 ≈ 卡容量，跑完自动清理）。
> 卡容量大于该卷可用空间时，请取消勾选「内部暂存」。

## 版本

- `1.0.22`（**修复「内置 ExifTool 其实跑不起来」**：此前 `vendor/exiftool/` 只打进了 `exiftool` 脚本，**没带它依赖的 `Image/ExifTool/*.pm`** —— 实际是靠宿主已装的 perl 模块才跑得起来；在没有该模块的机器上（典型：`wizard_pip_index=none` 的默认安装、没建 venv）会直接 `Can't locate Image/ExifTool.pm`，后果是**所有读不到拍摄日期的照片被跳过**（视频仍可用文件时间兜底）。现随包附带 ExifTool 模块树（`vendor/exiftool/lib/`，v12.92，含 `File::RandomAccess`）并用 `perl -I` 指向它，与宿主模块彻底解耦；安装回调增加 ExifTool 自检，跑不起来时在安装日志里写清后果与处理办法。代价：包体积从约 287 KB 增到约 5 MB。
- `1.0.21`（**安全与稳健性 11 项**：① 前端预览清单/提示条的文件名统一做 HTML 转义（源目录里构造的文件名不再能注入脚本）；② 任务ID 加白名单校验，状态目录与 `<输出目录>/log/` 的日志/报告不能再被 `../` 穿越；③ 网关改多线程，预览期间进度轮询与「取消」不再被单线程堵死；④ 核心脚本的真实报错（路径/权限/凭据）原样返回前端，不再只剩 `returned non-zero exit status 1`；⑤ 开始前先校验源/输出（互相包含、输出不可写）并抓「起来就失败」，不再出现「显示已开始、实际没有任何进度」；⑥ 状态文件写入节流 + 去掉多余缩进，1 万文件的写放大从约 2 万次全量写降到按时间节流；⑦ 未装 exifread/Pillow 时照片日期改走 exiftool 批量（不再每张照片起进程，照片依然「无 EXIF 跳过」）；⑧ 清源改为「源大小 + 目标存在且大小一致」双重校验，移除从未生效过的 `--verify-hash`；⑨ 内部暂存遵循「处理 JPG/视频」勾选；⑩ 台账清理 `days` 加范围校验（防 `-1` 清空台账）；⑪ 安装/升级回调补执行位、删掉无人读取的 `authorized_paths` 死代码、停止脚本去掉非法 `local`）。
- `1.0.20`（**修 bug + 提速**：预览的 `limit` 只限制「清单展示条数」，**不再截断统计** —— 之前源目录超过 500 个文件时，界面上的总数/已归档数会被错误地显示成 500；同时把拍摄日期解析改成**批量 exiftool**（视频每 100 个一次调用），600 个视频的预览从 ~31s 降到 ~1s、归档从 ~2min 降到 ~5s）。
- `1.0.19`（**重复归档防护**：新增处理台账 `$TRIM_PKGVAR/.rawarchiver/ledger.sqlite3`，跨任务/跨天记住「哪些文件归档过」；预览显示「已归档 N 个」并默认跳过，要重处理必须勾选 + 二次确认（GUI 还要求预览签发的 `dupGuard`）；跨输出目录视为新文件；内容复核默认头尾各 256KB，可切全文件哈希；回滚联动失效；台账丢失由历史报告自动回填。自检 `fnos/selftest_dupguard.py` 32 项全过）。
- `1.1.0`（**桌面 GUI 重构为原生窗口**：macOS 改用 SwiftUI、Windows 改用 WPF，弃用 pywebview/内嵌 WebView；功能与 1.0.18 等价。核心引擎经新增的 `desktop/core-ipc`（NDJSON）被原生 GUI 调用，`raw_archiver.py` 逻辑不变）。
- `1.0.18`（**小修**：飞牛外接存储 `/vol00` 正确识别为可移动介质；move 模式清源失败时日志说明原因并给出「手动删除或改用复制模式」的指引）。
- **同版本新增 macOS 平台**：`RawArchiver.app`（Apple Silicon / M 系列，pywebview 原生窗口 + 同一份核心/前端），Release 附件 `RawArchiver-macOS-1.0.18-arm64.dmg`。核心引擎零改动，仅新增平台壳（`macos/`）。
- **同版本新增 Windows 平台**：`RawArchiver.exe`（Win10/11 x64，pywebview EdgeChromium 窗口 + 同一份核心/前端），Release 附件 `RawArchiver-windows-1.0.18-x64.zip`；core 的 `is_removable` 增加 Windows 盘符（GetDriveTypeW）识别，纯增量、POSIX 无影响。
- `1.0.17`（**修复移动模式误报 + 日志增强**：move 模式源目录不可删时不再「文件已复制却报全部失败」，归档统一 copy2、清源失败仅告警；运行日志逐文件记录源→目标映射并输出成功/失败/跳过总数与完成时间）。
- `1.0.16`（**软件介绍补全**：已支持相机/运动相机品牌 + 支持格式清单 + 手机照片说明；应用中心 desc、应用内页头、README 三处同步）。
- `1.0.15`（软件介绍补充「已支持设备」品牌清单）。
- `1.0.14`（**盘面整理**：任务态从输出目录迁到应用数据目录 `$TRIM_PKGVAR/.rawarchiver/`，日志与报告统一落 `<输出目录>/log/`，源目录与输出目录根部零残留；目录选择按钮文案改为「选择源目录」/「选择目标目录」）。
- `1.0.13`：改造成飞牛统一网关微应用，目录选择走飞牛 JS SDK 系统内部弹窗（`pickSharedFile`）。
- 核心与 fnOS 包的最新改动见本 README 的「版本」段（`RAWArchiver/CHANGELOG.md` 只记录本体 v1.0.0 存档线）。

---

> **两条分发线，核心脚本自 v1.0.14 起分叉**（改代码前先看清是哪一条）：
>
> | 线 | 核心脚本 | 任务态位置 | 说明 |
> | --- | --- | --- | --- |
> | **fnOS 应用包 / 桌面版**（在维护，当前 v1.0.22） | `fnos/rawarchiver/app/scripts/raw_archiver.py` | `$TRIM_PKGVAR/.rawarchiver/`（无该变量时回落应用根目录） | fnOS `.fpk` + macOS/Windows 原生版的**唯一真源**，`desktop/core-ipc` 也调它 |
> | **本体**（v1.0.0 存档线，冻结） | `RAWArchiver/scripts/raw_archiver.py` | `<输出目录>/.rawarchiver/`（自包含） | 供 DSM 套件与「源码包」使用；**不跟随** v1.0.14+ 的演进（重复归档防护、批量解析等） |
>
> 需要最新能力（重复归档防护 / 批量 EXIF / 500+ 统计修复）时请用 `fnos/` 那份 —— 它只依赖标准库，可直接当 CLI 跑。
