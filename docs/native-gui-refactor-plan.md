# RAW 归档 · macOS / Windows 原生 GUI 重构方案

| 项 | 内容 |
| --- | --- |
| 文档状态 | **草案 v0.1 — 待确认**（确认后开始开发） |
| 日期 | 2026-10-23 |
| 影响范围 | `macos/`、`windows/` 两个平台壳（GUI 层）；核心引擎、fnOS 版不动 |
| 目标版本 | `1.1.0`（重大 UI 变更） |

---

## 1. 背景与目标

### 1.1 现状（为什么不符合要求）

当前 macOS / Windows 版的分层是：

```
pywebview 窗口（内嵌 WKWebView / EdgeChromium）
        ↑ 加载 HTTP
本地服务 server_mac.py / server_win.py（127.0.0.1 + token）
        ↑ import
核心引擎 raw_archiver.py
```

窗口里实际渲染的是 `www/index.html`（HTML + CSS + JS）——**本质是浏览器页面**，不符合「单独的窗口、不调用 web 页面」的要求。

### 1.2 重构目标

1. **界面改为桌面原生控件**：无 WebView、无 HTML/JS 渲染、无本地 HTTP 服务
2. **功能与现版本 1:1 保持不变**（逐条对照见 §5）
3. 核心引擎 `raw_archiver.py` 继续复用（**零漂移**，与 fnOS 版共享同一份逻辑）
4. 打包 / 签名 / CI / Release 流程沿用现有体系

### 1.3 非目标

- 不改归档算法、目录规则、EXIF 解析、日志与报告格式
- 不动 fnOS 版（仍是网关微应用 + web 前端）
- 不引入云端依赖、不联网

---

## 2. 硬约束

| # | 约束 |
| --- | --- |
| C1 | 界面不得包含 WebView / HTML / JS 渲染 |
| C2 | 覆盖 macOS（Apple Silicon）与 Windows（x64） |
| C3 | 现有功能逐项保留（§5 对照表全部打勾） |
| C4 | 源目录只读、日志与报告落 `<输出目录>/log/`、任务态落应用数据目录 |
| C5 | 分发形态：macOS `.dmg`（内含 .app）、Windows 免安装 `.zip`（内含 exe） |
| C6 | GitHub Actions 自动构建 + Release 发布继续可用 |

---

## 3. 方案选型

### 3.1 候选方案

| 方案 | 说明 |
| --- | --- |
| **A. Qt（PySide6）单代码库** | 一套 Python GUI 代码跑两个平台；直接 `import` 核心引擎 |
| **B. 双平台原生 + Python 内核进程** | macOS SwiftUI（Swift）+ Windows WPF（C#），通过 stdin/stdout 与打包好的 Python CLI 通信 |
| C. 双平台原生 + 逻辑重写 | 把归档引擎分别用 Swift / C# 重写 — **不推荐**（双倍逻辑、EXIF 解析各做一遍、必然漂移） |

### 3.2 对比

| 维度 | A. PySide6 | B. SwiftUI + WPF |
| --- | --- | --- |
| 是否 web 页面 | **否**（原生桌面控件） | 否 |
| 核心引擎复用 | 100%（同进程 import） | 100%（子进程 JSON） |
| GUI 代码量 | 1 套 ≈1500 行 Python | 2 套 ≈2500 行 Swift + 2500 行 C# + 2 个 IPC 层 |
| 观感 | Qt 的 macOS 风格（QMacStyle）/ Windows 原生风格，**接近但不是 100% 系统原生 API** | **100% 系统原生** |
| 安装包体积 | ≈ 80–110 MB（Qt 运行时；可裁剪） | ≈ 15 MB + Python 运行时（内嵌后 ≈60 MB） |
| 我方的验证能力 | **全量**：本地/CI 可 offscreen 跑自动化测试 | 受限：无法本地编译 Swift/C#，只能靠 CI 迭代，轮次多、风险高 |
| 工期 | **2–3 天** | 1–2 周 |
| 风险 | 低 | 中高（打包、签名、IPC 边界情况） |

### 3.3 推荐：方案 A（PySide6）

理由：

1. **直接满足 C1**：Qt Widgets 是原生桌面控件（`QMainWindow`、`QTableView`、`QProgressBar`、`QFileDialog`），整个工程不含任何 WebView / HTML
2. 一份代码两平台，功能一致性有保证，后续维护成本最低
3. 同进程 `import raw_archiver`，核心零改动、零漂移
4. 可做无头自动化测试（`QT_QPA_PLATFORM=offscreen`），回归成本低
5. 源码级可控，出问题定位快

**已知差异（需要您确认能否接受）**：

- 观感是 Qt 的 macOS 风格（按钮/输入框/表格由系统风格绘制），**不是** SwiftUI 那种「100% 苹果原生 API」；Windows 上则是原生 Win32 控件风格
- 安装包体积明显增大（Qt 运行时）
- 若您要求 100% 苹果/微软原生观感 → 只能选方案 B，工期与风险显著上升（§12）

---

## 4. 总体架构（方案 A）

```
┌───────────────────────────────────────────────────────────┐
│ GUI 层（PySide6 / Qt Widgets）          ← 全新，桌面/desktop  │
│  MainWindow / PreviewModel / Dialogs                      │
│  · 主线程只负责界面渲染与事件                                │
│  · 进度：QTimer 每 500ms 轮询 state.json（与现 server 同源）  │
└──────────────────────┬────────────────────────────────────┘
                       │ 直接函数调用（同进程）
┌──────────────────────▼────────────────────────────────────┐
│ 应用服务层（desktop/rawarchiver_gui/，新写）                 │
│  task_runner.py   QThread 执行 core.run_task（取消=写 cancel）│
│  preview_service.py  后台线程执行 core.do_preview            │
│  settings.py      QSettings 持久化上次设置                   │
│  platform_utils.py  可移动介质 / 打开目录 / 应用数据目录      │
└──────────────────────┬────────────────────────────────────┘
                       │ import（core 一行不改）
┌──────────────────────▼────────────────────────────────────┐
│ 核心引擎 raw_archiver.py（不变，796 行）                     │
│  scan_images / resolve_date / build_target / run_task      │
│  do_preview / do_cleanup / do_rollback / load_state        │
└───────────────────────────────────────────────────────────┘
```

**被删除的东西**：

| 文件 | 处理 |
| --- | --- |
| `macos/app/server_mac.py`（404 行） | 删除（不再需要本地 HTTP 服务） |
| `windows/app/server_win.py`（413 行） | 删除 |
| `macos/app/main_mac.py`（155 行，pywebview 入口） | 改为 GUI 入口（薄壳） |
| `windows/app/main_win.py`（149 行） | 同上 |
| `www/index.html`（468 行） | macOS/Windows 打包不再包含（fnOS 版继续用） |
| token 鉴权、127.0.0.1 端口 | 全部移除（无网络接口） |

> 安全收益：不再监听任何端口，不存在本机其他进程调用 API 的可能。

---

## 5. 功能对照表（必须 1:1 保留）

> 逐条来自当前 web 界面（`www/index.html`）与 API（`server_*.py` 的 `handle_action`），重构后逐项验收。

| # | 原功能 | 新 GUI 实现 | 控件 |
| --- | --- | --- | --- |
| 1 | 源目录输入 | 路径输入框 | `QLineEdit` |
| 2 | 源目录选择（原生对话框） | 浏览按钮 → 系统目录选择框 | `QPushButton` + `QFileDialog.getExistingDirectory` |
| 3 | 输出目录输入 + 选择 | 同上 | 同上 |
| 4 | 「已选择：xxx」提示 | 输入框下方状态标签 | `QLabel` |
| 5 | 按品牌分层 | 复选框 | `QCheckBox` |
| 6 | 处理 JPG / 处理视频 | 复选框 ×2（默认勾选） | `QCheckBox` ×2 |
| 7 | 内部暂存（含平台说明） | 复选框 + 提示文字（mac：「暂存会先拷到启动盘」/ win：「拷到系统盘」） | `QCheckBox` + `QLabel` |
| 8 | 模式：复制 / 移动 | 下拉框 | `QComboBox` |
| 9 | 预览（扫描源 + 生成目标路径） | 「预览」按钮 → 后台线程 → 结果表格 | `QPushButton` + `QTableView` |
| 10 | 预览表 4 列：源文件 / 拍摄日期 / 日期来源 / 目标路径 | 表格模型（等宽字体、可排序） | `QTableView` + `QAbstractTableModel` |
| 11 | 汇总：N 个文件 / GB / 日期范围 / ExifTool 状态 | 汇总栏 | `QLabel` |
| 12 | 警告：无日期数 / 将跳过数 / 重名冲突数 / 移动清源警示 | 提示区（黄/红） | `QLabel`（富文本） |
| 13 | 「确认并开始」（预览后才可用） | 开始按钮（禁用逻辑一致） | `QPushButton` |
| 14 | 进度条 + `current/total` + 成功/失败/跳过 | 进度条 + 计数标签 | `QProgressBar` + `QLabel` |
| 15 | 实时日志滚动 | 只读日志面板，自动滚到底 | `QPlainTextEdit`（readOnly） |
| 16 | 取消任务 | 取消按钮 → 写 `cancel` 文件 | `QPushButton` |
| 17 | 完成提示（成功 N 个） | 完成对话框 + 「打开输出目录」按钮 | `QMessageBox` |
| 18 | 补清源（cleanup，需任务 ID） | 菜单 → 输入/选择任务 ID → 执行 | `QInputDialog` |
| 19 | 回滚（rollback，仅复制模式） | 同上，移动模式给出同样提示 | `QInputDialog` + `QMessageBox` |
| 20 | 记忆上次源/输出/模式 | `QSettings` 自动持久化（含所有选项） | `QSettings` |
| 21 | 移动模式 + 可移动介质二次确认 | 确认对话框（文案同 web） | `QMessageBox.question` |
| 22 | 源不可读明确报错（含平台指引） | 错误对话框 | `QMessageBox.critical` |
| 23 | 必填校验、输出不能位于源内（core 内校验） | 按钮禁用 + 提交前校验 + core 返回错误提示 | — |
| 24 | 环境自检（doctor：exifread/Pillow/ExifTool/perl） | 菜单「工具 → 环境自检」→ 结果对话框 | `QDialog` |
| 25 | 打开输出目录 | 完成对话框/菜单 | `QDesktopServices.openUrl` |
| 26 | 版本号显示 | 窗口标题 + 关于对话框 | `QMainWindow` / `QMessageBox.about` |
| 27 | 任务态/日志/报告路径约定 | 完全沿用：`TRIM_PKGVAR` 注入 + `<输出>/log/` | — |
| 28 | 源目录只读、零新增文件 | core 保证，GUI 不额外写源目录 | — |

---

## 6. 界面设计

### 6.1 主窗口（默认 1020×840，最小 760×620）

```
┌─ RAW 归档 v1.1.0 ────────────────────────────────────────────┐
│ 文件(F)  工具(T)  帮助(H)                                     │
├──────────────────────────────────────────────────────────────┤
│ 源（SD/TF/U 盘或本地目录）                                     │
│ ┌──────────────────────────────────────────┐ ┌────────────┐ │
│ │ /Volumes/SD卡/DCIM                       │ │ 选择目录…  │ │
│ └──────────────────────────────────────────┘ └────────────┘ │
│ 已选择：/Volumes/SD卡/DCIM                                   │
│                                                              │
│ 输出目录（归档落点，不存在会自动创建）                          │
│ ┌──────────────────────────────────────────┐ ┌────────────┐ │
│ │ /Users/xxx/Pictures/归档                  │ │ 选择目录…  │ │
│ └──────────────────────────────────────────┘ └────────────┘ │
│                                                              │
│ 选项  ☐ 按品牌分层   ☑ 处理 JPG   ☑ 处理视频   ☑ 内部暂存      │
│ 模式  [ 复制（保留源文件）        ▼ ]                         │
│                                                              │
│ [ 预览 ]  [ 开始归档 ]  [ 取消 ]                              │
├──────────────────────────────────────────────────────────────┤
│ 汇总：128 个文件 / 3.42 GB ｜ 2024-05-01 ~ 2024-07-12 ｜       │
│       ExifTool：可用                                          │
│ ⚠ 3 个文件读不到拍摄日期，执行时将被跳过                        │
│ ⚠ 2 个目标已存在同名文件，将自动追加 _1/_2                      │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 源文件          │ 拍摄日期   │ 日期来源 │ 目标路径        │ │
│ │ DCIM/100CANON/… │ 2024-05-06 │ exiftool │ 20240506/IMG…  │ │
│ │ DCIM/100CANON/… │ 2024-05-06 │ exifread │ 20240506/IMG…  │ │
│ │ …（可拖动列宽、点击排序）                                  │ │
│ └──────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░  62%                                  │
│ 运行中  124/200 ｜ 成功 122 失败 0 跳过 2                      │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ [2026-10-23 15:03:19] 待处理 200 个文件                    │ │
│ │ [15:03:20] 20240506/IMG_0001.CR3                          │ │
│ │ …（自动滚动）                                              │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 菜单

| 菜单 | 项 |
| --- | --- |
| 文件 | 选择源目录… / 选择输出目录… / 打开输出目录 / 退出 |
| 工具 | 环境自检 / 补清源… / 回滚… |
| 帮助 | 关于（版本、数据目录、日志位置） |

### 6.3 交互流程

```
启动 → 恢复 QSettings → 主窗口
  ↓
选源/输出（QFileDialog，默认打开上次目录）
  ↓
[预览] → 按钮置灰、状态「正在扫描…」→ 后台线程 core.do_preview
       → 填充表格 + 汇总 + 警告 → 启用 [开始归档]
  ↓
[开始归档] → 若「移动模式 + 可移动介质」→ 确认框
          → QThread 执行 core.run_task（stdout 重定向到 <输出>/log/rawarchiver_<tid>.log）
          → QTimer 500ms 轮询 state.json → 进度条/计数/日志刷新
  ↓
done → 停止轮询 → 完成对话框（成功/失败/跳过 + 打开输出目录）
cancelled → 状态「已取消」，已归档文件保留
error → 错误对话框 + 日志面板定位
  ↓
[取消] → 写 cancel 文件 → core 在文件边界停止（断点可续跑）
关闭窗口 → 若有任务运行 → 确认「归档进行中，退出将中止（已完成的文件保留，可下次续跑）」
```

### 6.4 外观

- 默认跟随系统深浅色（Qt 6 自动适配 macOS 外观；Windows 跟随系统主题）
- 表格用等宽字体显示路径
- 不使用自定义皮肤，保持系统观感

---

## 7. 代码结构（新增 `desktop/`）

```
desktop/                            ← 新增：跨平台 GUI 源码（mac/win 共用）
├── rawarchiver_gui/
│   ├── __init__.py                 # VERSION
│   ├── __main__.py                 # 入口：python -m rawarchiver_gui [--selftest|--cli …]
│   ├── app.py                      # QApplication 初始化、平台设置、异常兜底
│   ├── main_window.py              # QMainWindow：布局、信号连接、状态机
│   ├── preview_model.py            # QAbstractTableModel（4 列 + 排序）
│   ├── task_runner.py              # QThread 包 core.run_task + 轮询 state.json
│   ├── preview_service.py          # 后台预览线程
│   ├── settings.py                 # QSettings（源/输出/选项/模式/窗口尺寸）
│   ├── platform_utils.py           # 可移动介质、打开目录、应用数据目录、默认路径
│   ├── dialogs.py                  # 关于 / 环境自检 / 补清源 / 回滚
│   └── style.py                    # 少量样式（等宽字体、警告色）
├── tests/
│   ├── test_preview_model.py       # 表格模型单测（无 GUI 依赖）
│   ├── test_gui_offscreen.py       # QT_QPA_PLATFORM=offscreen 冒烟：建窗口、填字段、断言
│   └── test_core_bridge.py         # 预览/归档/task 目录 端到端（临时目录 + 合成 EXIF 图）
└── requirements.txt                # PySide6
```

**macOS / Windows 平台目录的变化**：

```
macos/
├── app/main_mac.py      → 改为薄壳：设置 TRIM_PKGVAR → 调 desktop/rawarchiver_gui
├── app/scripts/         （同步 core，不变）
├── app/vendor/exiftool/ （不变）
├── RawArchiver.spec     → 入口改为 desktop、hiddenimports 改 PySide6
└── build.sh             → 增加「同步 desktop/ → app/gui」
windows/ 同理（server_win.py 删除）
```

**入口薄壳**（`main_mac.py` / `main_win.py` 约 30 行）：

```python
def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--cli":        # 调试/脚本用途，转发 core CLI
        return cli(argv[1:])
    os.environ.setdefault("TRIM_PKGVAR", app_data_dir())   # 任务态目录
    from rawarchiver_gui.app import run
    return run(argv)                       # 支持 --selftest
```

---

## 8. 与核心引擎的接口（core 不改）

GUI 只用 core 的公开函数：

| core 函数 | 用途 |
| --- | --- |
| `do_preview(source, opts, limit=500)` | 预览，返回 total/size/by_type/date_range/bad_count/conflicts/sample… |
| `run_task(source, output, opts, task_id)` | 执行归档（阻塞；内部写 state.json / 日志 / 报告） |
| `load_state(tid)` / `cancelled(tid)` | 轮询进度、取消 |
| `do_cleanup(output, tid, verify_hash=False)` | 补清源 |
| `do_rollback(output, tid)` | 回滚（复制模式） |
| `state_root()` / `task_dir()` / `log_path()` / `report_path()` | 路径统一（GUI 不自己拼路径） |
| `et_available()` / `is_removable(path)` | 汇总显示 / 移动模式确认 |
| `_exiftool_bin()` 或 doctor 逻辑 | 环境自检 |

**opts 结构**（与现 API 完全一致）：

```python
opts = {
    "brand_folder": bool,   # 按品牌分层
    "handle_jpg":   bool,   # 处理 JPG
    "handle_video": bool,   # 处理视频
    "staging":      bool,   # 内部暂存
    "mode":         "copy" | "move",
}
```

**日志行为保持一致**：`run_task` 用 `print` 写日志，现有实现靠把 stdout 重定向到 `<输出>/log/rawarchiver_<tid>.log`。GUI 里在 `task_runner` 中同样处理：

```python
with redirect_stdout_to(log_path(output, tid)):     # 打开 utf-8 文件、替换 sys.stdout/stderr
    core.run_task(source, output, opts, tid)
```

→ 日志文件内容与现在**逐字节一致**。

**线程模型**：

| 操作 | 线程 | 说明 |
| --- | --- | --- |
| 界面渲染 / 事件 | 主线程（Qt 事件循环） | 绝不阻塞 |
| 预览（`do_preview`） | `PreviewService`（QThread） | 只读扫描，完成后信号回主线程 |
| 归档（`run_task`） | `TaskRunner`（QThread） | 阻塞函数；取消靠 cancel 文件 |
| 进度刷新 | 主线程 QTimer 500ms | 读 `state.json`（core 每文件原子写） |

> **不引入本地 HTTP 服务**，进度用「轮询 state.json」——与现有 server 的 status 实现同源，core 零改动。

---

## 9. 打包与分发

| 项 | macOS | Windows |
| --- | --- | --- |
| 打包 | PyInstaller onedir → `RawArchiver.app`（BUNDLE） | PyInstaller onedir → `RawArchiver.exe` |
| 窗口模式 | `console=False` + NSHighResolutionCapable | `console=False`（无黑窗） |
| 关键打包点 | PySide6 的 `platforms/libqcocoa.dylib` 等插件必须随包（PyInstaller PySide6 hook 已覆盖，CI 里用 offscreen 冒烟验证） | PySide6 的 `platforms/qwindows.dll` 随包；无需双 exe（无子进程 worker） |
| 体积控制 | `excludes` 裁掉 `QtWebEngine*`、`QtQml`、`QtQuick`、`Qt3D*`、`QtCharts`、`QtMultimedia` 等 | 同上 |
| 图标 | `icon-source.png` → icns | `icon-source.png` → ico |
| 产物 | `RawArchiver-macOS-1.1.0-arm64.dmg`（hdiutil UDZO） | `RawArchiver-windows-1.1.0-x64.zip` |
| 签名 | ad-hoc（未 Apple 公证，首次右键打开） | 无（SmartScreen 误报提示写进 README） |

估计体积：macOS ≈ 100–130 MB、Windows ≈ 80–110 MB（Qt 运行时；具体以 CI 实测为准）。

---

## 10. CI 改造

| 项 | 现在 | 改造后 |
| --- | --- | --- |
| 构建 | `bash macos/build.sh` / `windows/build.sh` | 增加「同步 `desktop/`」步骤；入口/spec 更新 |
| 冒烟 1 | HTTP API（info/token/preview） | **offscreen GUI 测试**：`QT_QPA_PLATFORM=offscreen python -m pytest desktop/tests` |
| 冒烟 2 | `--doctor` CLI 自测 | 保留（core 链路验证，exifread/Pillow/ExifTool） |
| 冒烟 3 | GUI 服务 + URL | **`RawArchiver --selftest`**：不开窗口，跑 doctor + 合成图预览，打印 JSON、退出码 0 |
| 打包验证 | 上传 artifact | 不变 |

`--selftest` 设计（供 CI 与排障）：

```json
{ "ok": true, "version": "1.1.0", "qt": "6.x", "exifread": true,
  "pillow": true, "exiftool": ".../vendor/exiftool/exiftool",
  "preview_total": 1 }
```

---

## 11. 版本与发布

- 版本 **1.1.0**（UI 架构变更，功能等价）
- 主 Release `v1.1.0` 内三平台产物共存：`.fpk`（fnOS）/ `.dmg`（macOS）/ `.zip`（Windows）
- 旧的 `1.0.18` 两个独立 Release（macos-/windows- 前缀）保留，链接不失效
- 发版流程沿用：push → CI 绿 → 打 tag → dispatch 带 `release_tag`

---

## 12. 备选方案 B（仅在要求 100% 原生时采用）

| 项 | 设计 |
| --- | --- |
| macOS | SwiftUI 窗口；`Process` 启动打包内的 `RawArchiver-cli`，stdin/stdout 走 NDJSON |
| Windows | WPF（.NET 8）同上 |
| IPC 协议 | 请求 `{"id":1,"cmd":"preview","payload":{…}}` → 响应 `{"id":1,"ok":true,"data":{…}}`；任务进度由 cli 侧每文件输出 `{"evt":"progress","current":n,"total":m}` |
| 代价 | 两套 GUI（≈5000 行）、两套打包/签名、两套 CI；我方无法本地编译，全靠 CI 迭代 |
| 工期 | 1–2 周 |

---

## 13. 里程碑（方案 A）

| 阶段 | 内容 | 预估 |
| --- | --- | --- |
| M1 | `desktop/` 骨架 + 主窗口布局 + QSettings + 目录选择 | 0.5 天 |
| M2 | 预览：后台线程 + 表格模型 + 汇总/警告 | 0.5 天 |
| M3 | 归档：TaskRunner + 进度轮询 + 日志面板 + 取消 + 关闭确认 | 0.5 天 |
| M4 | 补清源 / 回滚 / 环境自检 / 关于 / 打开输出目录 | 0.3 天 |
| M5 | 打包改造（mac .app+dmg / win exe+zip）+ CI（offscreen + `--selftest`） | 0.5 天 |
| M6 | 本地全链路测试（合成相机目录：RAW/JPG/视频/无日期/重名）+ 文档 | 0.2 天 |
| **合计** | | **≈2.5 人日**（含 CI 迭代） |

---

## 14. 风险与对策

| 风险 | 对策 |
| --- | --- |
| PySide6 打包到 .app 后缺 Cocoa 平台插件（黑屏/闪退） | PyInstaller 的 PySide6 hook + CI 里 `QT_QPA_PLATFORM=offscreen` 冒烟 + `--selftest`；必要时在 spec 手动补 `platforms/libqcocoa.dylib` |
| 体积增大、下载变慢 | excludes 裁剪 Qt 模块；dmg 用 UDZO；README 标注体积 |
| 观感非 100% 系统原生 | 若不可接受 → 方案 B（需确认，工期 1–2 周） |
| 关闭窗口时任务被中断 | 确认对话框 + core 断点续跑（同任务 ID 可续）；如需「后台继续」可改 QProcess（备选，+0.5 天） |
| 中文路径 / 编码 | Qt 原生 Unicode；日志与报告强制 utf-8；CI 加中文路径用例 |
| 无头 CI 验证不了真实渲染 | offscreen 冒烟 + 截图存档；最终在真机验收（您这边） |
| 重构引入功能回退 | §5 对照表逐条验收；core 不动，风险集中在 UI 层 |

---

## 15. 待确认问题（请逐条回复）

| # | 问题 | 建议 |
| --- | --- | --- |
| Q1 | GUI 框架：接受 **Qt（PySide6）单代码库**，还是要 **100% 系统原生**（方案 B，工期 1–2 周）？ | 建议 Qt：满足「无 web 页面」要求，工期 2–3 天，且我能完整自测 |
| Q2 | 关闭窗口时若有归档任务在跑：**A 提示后中止**（推荐）/ B 后台继续直到完成 / C 不允许关闭 | A（core 支持断点续跑，最安全） |
| Q3 | 「补清源 / 回滚」这两个高级功能是否保留在 GUI 菜单里？（现 web 版有） | 保留（放在「工具」菜单，不影响主界面简洁度） |
| Q4 | 界面风格：**跟随系统深浅色**（推荐）/ 固定浅色 | 跟随系统 |
| Q5 | 版本号定为 **1.1.0**，可以吗？ | 可以 |
| Q6 | Windows 继续**免安装 zip**，还是需要安装版（NSIS 安装向导）？ | 继续 zip（免安装更省事） |
| Q7 | 是否需要保留命令行模式（`RawArchiver --cli <源> --output …`）？ | 保留（隐藏功能，便于排障与脚本调用，成本≈0） |

---

## 附录 A：验收清单（重构完成后逐项打勾）

- [ ] 界面无任何 WebView / HTML 渲染（代码搜索无 `webview`、无 `index.html` 引用）
- [ ] 不再监听任何网络端口（`netstat` 验证）
- [ ] 预览：总数/大小/日期范围/ExifTool 状态/无日期数/重名冲突数 与旧版一致
- [ ] 归档：复制/移动模式、断点续跑（同 task id）、取消
- [ ] 日志文件与报告文件内容/路径与旧版一致
- [ ] 源目录零新增文件
- [ ] 移动模式 + 可移动介质二次确认
- [ ] 补清源 / 回滚 / 环境自检 / 打开输出目录
- [ ] 设置记忆（重启后恢复）
- [ ] macOS：`/Volumes/*` 识别、.dmg 安装、首次右键打开
- [ ] Windows：盘符识别、zip 解压即用
- [ ] CI 双平台绿 + Release 三平台产物齐全
