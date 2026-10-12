# RAW 归档 v1.0.0 部署说明

## 0. 打包前必做：ExifTool 就位

`build_all.sh` 会硬校验 `vendor/exiftool/exiftool`，缺了直接报错退出。

```bash
sh scripts/fetch_exiftool.sh              # 本机已有 exiftool 则复制，否则下载官方 13.00
EXIFTOOL_VER=12.90 sh scripts/fetch_exiftool.sh   # 锁版本
ALLOW_NO_EXIFTOOL=1 sh build_all.sh       # 强行不含（视频日期退化为文件时间）
```

Windows 环境：把官方 `exiftool(-13.00)_FULL Perl port for Windows.tar.gz` 解出的
`exiftool_files/` 与 `exiftool.exe` 放到 `vendor/exiftool/`（脚本会自动找 `.exe`）。

## 1. 离线依赖（可选但推荐）

在有网机器上：

```bash
mkdir -p vendor/wheels
pip download -d vendor/wheels exifread Pillow
sh build_all.sh
```

装包时 installer 会用 `--no-index --find-links vendor/wheels` 安装，全程不联网。

## 2. DSM 安装

```bash
# 开发自测：直接铺到 Web 根
sudo mkdir -p /volume1/web/rawarchiver
sudo cp -a app/rawarchiver/. scripts vendor agent /volume1/web/rawarchiver/
sudo chown -R http:users /volume1/web/rawarchiver/data
sudo chmod 755 /volume1/web/rawarchiver/api/index.cgi
echo /volume1/web/rawarchiver > /volume1/web/rawarchiver/etc/env   # CGI 读它定位自身

# 正式：套件中心手动安装 dist/RAWArchiver-1.0.0.spk
```

Web Station 需给 `/app/rawarchiver` 建虚拟主机或别名，指向 `/volume1/web/rawarchiver`。

## 3. 权限：三件事必须确认

```bash
# (a) CGI 的 http 身份能否读卡
sudo -u http ls /volumeUSB1/usbshare

# (b) CGI 能否写输出目录（归档会失败于第一批 mkdir）
sudo -u http touch /volume1/photos/Camera/.t && sudo rm /volume1/photos/Camera/.t

# (c) 移动模式删卡上文件（vfat/exfat 常挂成 root:root，http 删不动）
sudo -u http rm -f /volumeUSB1/usbshare/DCIM/test.jpg
```

(c) 不通时，**不要**改用 copy 绕过去，而是把执行身份提到 root，二选一：

- **任务计划程序**：新增「触发的任务 → 用户定义的脚本」，root 执行
  `SOURCE=/volumeUSB1/usbshare OUTPUT=/volume1/photos/Camera MODE=move sh /volume1/web/rawarchiver/scripts/pipeline.sh`
- **本机 Agent**：`python3 agent/agent.py`（root 或 sudo 跑），走 8765 端口的同一套界面

清源失败不会丢数据：文件已安全归档，清单留在 `state.json`，之后 root 补一刀即可

```bash
sudo python3 scripts/raw_archiver.py -o /volume1/photos/Camera --task-id <ID> --cleanup
```

## 4. fnOS 安装

上传 `RAWArchiver-1.0.0.fpk` → 应用中心手动安装。装完在应用里启动，访问 `http://<NAS>:8765/`。
fnOS 默认以包用户运行；需要 root 清卡时同样用计划任务跑 `scripts/pipeline.sh`。

## 5. 运行时产物

```
<输出目录>/
├── .rawarchiver/tasks/<taskId>/{state.json,cancel,run.log,stage/}
├── 20261005/IMG_0001_20261005.CR2
├── Nikon/DSC_0002_20261005.NEF        # 品牌分层开启时
├── 10/IMG_0003_20261005.JPG           # 月份平铺（仅 JPG/视频）
├── _restored/<taskId>/...             # 回滚落点（仅 copy 模式）
└── _report_<taskId>.json              # 下游唯一凭证
```

## 6. 已知边界

1. 跨卷没有真正的 move，「移动」= 顺序拷到 NAS 暂存 → 同卷 rename → 按清单删源；任一步失败只多不少。
2. 断点续跑要求源挂载点不变；换口时清理会拒绝执行，靠 `_report_*.json` 的 src+size 人工核对。
3. 卡上文件同名不同内容会被判为已归档而跳过；需要严格判重加 `--verify-hash`（清源阶段做 MD5）。
4. 照片读不到 EXIF 一律跳过不拷（避免 `_NoDate` 垃圾堆积），视频才用文件时间兜底，日志与预览都会标注。
