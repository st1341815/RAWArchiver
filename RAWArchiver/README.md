> ## ⚠️ 已冻结存档（ARCHIVED）
>
> 本目录是 **v1.0.0 存档线**（DSM 套件 / 源码包），**自 2026-10 起不再维护、不再发布**：
>
> - 它**不包含**后续能力：重复归档防护（台账）、批量 EXIF 解析、500+ 文件统计修复、飞牛统一网关微应用改造等；
> - 它**不是**当前发布的安装包来源 —— fnOS `.fpk` 在 `../fnos/`，macOS/Windows 原生版在 `../desktop/`；
> - `scripts/raw_archiver.py` 的任务态写在 `<输出目录>/.rawarchiver/`（自包含），与 fnos 线（`$TRIM_PKGVAR/.rawarchiver/`）**不同**，别混用。
>
> 只做两件事：保留历史实现 + 存放当年核对用的更正版 PDF（`corrections/`）。新功能一律改 `../fnos/rawarchiver/app/`。

# RAW 归档 v1.0.0

相机照片按拍摄日期整理归档工具。直接从 SD/TF/U 盘读取拍摄日期，按 `YYYYMMDD` 归档 RAW/JPG/视频到任意 NAS 目录。

## 特性

- **源自由指定**：`/volumeUSB*/usbshare`（卡、U 盘）或任意本地目录，界面下拉选设备 + 手填路径兜底
- **输出自由指定**：任意 NAS 路径，不存在自动创建；禁止输出落在源内部
- **日期四级兜底**：exifread → Pillow → ExifTool（视频主力）→ 文件修改时间（仅视频，照片无日期则跳过）
- **内部暂存**：卡源自动先顺序整卷拷到 NAS（保 mtime），再同卷归档，比在卡上随机小读快数倍
- **复制 / 移动双模式**：移动模式在归档全部成功后按清单清源，只多不少不丢片；断电可续跑
- **自包含断点**：任务态写 `<输出目录>/.rawarchiver/tasks/<taskId>/state.json`，换机也能续
- **报告即接口**：`_report_<taskId>.json` 是下游程序唯一消费入口（含源路径、大小、目标路径、日期来源）
- **零联网安装**：ExifTool 与 Python 依赖随包分发（vendor/）

## 目录结构

```
RAWArchiver/
├── build_all.sh                    # 统一打包 → dist/*.spk *.fpk *-src.tar.gz + SHA256SUMS
├── requirements.txt
├── scripts/
│   ├── raw_archiver.py             # 核心（CLI：--preview/--info/--doctor/--cleanup/--rollback）
│   ├── setup.py                    # 依赖安装（离线 wheels 优先）
│   ├── fetch_exiftool.sh           # 获取 ExifTool → vendor/exiftool/
│   ├── pipeline.sh                 # 一键流水线（可挂任务计划，root 执行）
│   └── hooks/post_done.sh          # 完成后钩子
├── app/rawarchiver/
│   ├── www/index.html              # Web 面板（源/输出/预览/进度/清源/回滚）
│   └── api/index.cgi               # DSM CGI 入口
├── agent/agent.py                  # 本机版 Agent（FastAPI，8765 端口）
├── vendor/
│   ├── exiftool/                   # 打包前用 fetch_exiftool.sh 填充
│   └── wheels/                     # 可选：离线 pip wheels
├── pkg/spk/                        # DSM 套件：INFO / conf / package-scripts.d/install.sh
├── pkg/fpk/                        # fnOS 包：package.conf / cmd_script/*
└── docs/INSTALL.md                 # 部署与权限详解
```

## 三步上手

```bash
sh scripts/fetch_exiftool.sh          # 1) 取 ExifTool 进 vendor/exiftool/
python3 scripts/setup.py              # 2) 装依赖（有网在线，无网放 wheels 到 vendor/wheels/）
python3 scripts/raw_archiver.py --doctor   # 3) 自检

# 预览 → 干跑 → 正式跑
python3 scripts/raw_archiver.py /volumeUSB1/usbshare -o /volume1/photos/Camera --preview
python3 scripts/raw_archiver.py /volumeUSB1/usbshare -o /volume1/photos/Camera --month --brand
python3 scripts/raw_archiver.py /volumeUSB1/usbshare -o /volume1/photos/Camera --mode move --month
```

Web 界面：`http://<NAS>/app/rawarchiver/`；本机版：`python3 agent/agent.py` → `http://127.0.0.1:8765/`

## 打包

```bash
sh build_all.sh
ls dist/    # RAWArchiver-1.0.0.spk / .fpk / -src.tar.gz / SHA256SUMS.txt
```

详见 [docs/INSTALL.md](docs/INSTALL.md)（含 ExifTool 打包、CGI 权限、清卡需 root 的原因）。
