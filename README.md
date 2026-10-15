# RAW 归档（RAW Archiver）

相机照片/视频按**拍摄日期（EXIF）**归档到 NAS 的工具。设计准则：**源只读、目标可写、可断点续跑、可清源**。
照片读不到 EXIF 一律视为未知并**跳过**；视频可用文件时间兜底。支持 RAW（NEF/CR2/ARW…）/ JPG / 视频。

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
```

## 构建

- **fnOS 应用包（.fpk）**
  ```
  cd fnos && bash build.sh          # 产出 fnos/dist/rawarchiver.fpk
  ```
- **本体：DSM 套件（SPK）/ fnOS 包（FPK）/ 源码包**
  ```
  cd RAWArchiver
  sh scripts/fetch_exiftool.sh
  sh build_all.sh
  ```

## 安装与使用（fnOS）

1. 应用中心 → 手动安装 → 选 `fnos/dist/rawarchiver.fpk`。
2. 安装后到「应用中心 → RAW 归档 → 设置 → **授权目录**」授权**源目录（读）**与**归档目录（读+写）**；
   否则以包用户运行时读写共享目录会 `Permission denied`。
3. 打开应用 → 选择源/输出目录 → **预览**（文件清单可折叠）→ 确认并开始。

## 版本

- 当前 `1.0.9`（输出目录「选取文件夹」走飞牛宿主 `/app-auth` 原生目录选择器，参考 file.dedupe；不可用时回落内置目录浏览器）。核心与 fnOS 包的最新改动见 `RAWArchiver/CHANGELOG.md`。

---

> 说明：`RAWArchiver/`（本体）与 `fnos/`（应用包）是同一产品的两部分；核心脚本以 `RAWArchiver/scripts/raw_archiver.py` 为准，`fnos/rawarchiver/app/scripts/raw_archiver.py` 为其在 fnOS 包内的拷贝。
