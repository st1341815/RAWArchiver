# 变更日志

## v1.0.0
- 更名 RAW 归档（rawarchiver），版本重新从 1.0.0 起算
- 源改为可移动介质/任意目录自由指定；输出目录自由指定并自包含任务态 `.rawarchiver/`
- 新增预览、内部暂存、移动模式清源（归档全部成功后）、补清源、回滚
- 新增统一打包：SPK/FPK/源码包 + SHA256SUMS；ExifTool 与离线 wheels 随包分发
- 新增 `--doctor` 自检、`_report_<taskId>.json` 下游报告
