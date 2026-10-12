# RAW 归档 · fnOS 应用包（.fpk）

把 RAWArchiver 的核心脚本 + 随包 ExifTool + Web 面板封装成 fnOS 应用：
CGI 入口按需执行，无常驻进程；相机照片/视频按拍摄日期（EXIF）归档到指定 NAS 目录。

- 应用包名（appname）：`rawarchiver`（显示名 `RAW 归档`，版本 `1.0.0`）
- 产物：`dist/rawarchiver.fpk`
- 打包工具：系统 `fnpack`（`/usr/local/bin/fnpack`，v1.2.4）

## 一、为什么重做（原工程的 `pkg/fpk` 不可安装）

RAWArchiver 原 `pkg/fpk/`（`package.conf`(JSON) + `cmd_script/`）是**示意性结构**，
与飞牛官方 `fnpack` 格式对不上，直接照抄打不出可安装的包。本工程按官方规范重做：

| 原工程（示意性） | 官方格式（本工程） | 原因 |
| --- | --- | --- |
| `package.conf`(JSON) | `manifest`(INI) | fnpack 校验 appname/version/display_name/platform… |
| `cmd_script/` | `cmd/`（main/install_init/install_callback/…） | 官方生命周期脚本契约 |
| 无 `config/` | `config/{privilege, resource}` | `privilege` 定 run-as=package，`resource` 必检 |
| 无 `wizard/` | `wizard/{install, config}` | 安装/设置向导 |
| `app/rawarchiver/{www,api}` | `app/{www,api,scripts,ui,vendor}` | fnpack 只打包 `app/` |
| 端口 8765 / `start-stop` | CGI：`/cgi/ThirdParty/rawarchiver/index.cgi/` | fnOS 原生 CGI，无需常驻进程与端口 |

## 二、目录结构

```
rawarchiver/
├── manifest                     # 元数据（INI，ctl_stop=true）
├── ICON.PNG / ICON_256.PNG      # 图标（gen_icons.py 生成）
├── config/{privilege, resource}
├── cmd/                         # 生命周期（main/install_*/uninstall_*/upgrade_*/config_*）
├── wizard/{install, config}     # 向导（提示授权目录 + pip 镜像）
└── app/                         # → $TRIM_APPDEST
    ├── ui/{config, index.cgi, images/}   # 桌面入口 + CGI：静态服务 + /api 路由
    ├── api/index.cgi            # JSON API（调用核心脚本）
    ├── scripts/                 # raw_archiver.py（含更正）+ fetch_exiftool.sh + setup.py
    ├── vendor/exiftool/exiftool # 随包 ExifTool（perl 脚本）
    └── www/index.html           # Web 面板（与核心脚本同源的 JSON 协议）
```

## 三、安装 / 测试（本机 fnOS）

```bash
bash build.sh                                                   # 产出 dist/rawarchiver.fpk
printf 'wizard_pip_index=https://pypi.tuna.tsinghua.edu.cn/simple\n' > /tmp/raenv
sudo appcenter-cli install-fpk "$PWD/dist/rawarchiver.fpk" -e /tmp/raenv -v 1
sudo appcenter-cli status rawarchiver
```

验证（CGI 需 fnOS 登录 token，直接以包用户调用可自测）：
```bash
API=/vol1/@appcenter/rawarchiver/api/index.cgi
B='{"action":"doctor"}'
echo -n "$B" | sudo -u rawarchiver env TRIM_APPDEST=/vol1/@appcenter/rawarchiver \
  TRIM_PKGVAR=/vol1/@appdata/rawarchiver CONTENT_LENGTH=${#B} \
  CONTENT_TYPE=application/json REQUEST_METHOD=POST "$API"
```

## 四、踩坑（与 D90 同源，务必保持）

1. `manifest` 的 **`ctl_stop=true`**（用户可见应用必须；纯 CGI 应用也设 true，`cmd/main` start/stop 空操作、status 恒 0）。
2. `app/ui/config` **不要写 `port`**：`type=iframe` + `url=/cgi/ThirdParty/rawarchiver/index.cgi/`，fnOS 存成 `{"path":…}`。
3. 桌面图标默认不自动出现（`autoCreateDesktopIcon` 未启）。必要时往 `trim_sac.user_desktop_entry`（uid=1000）补一条。
4. 卸载重装会清掉「授权目录」，需重新添加。
5. 沙箱/宿主有全局 `PYTHONPATH` 注入（PIL 假版本、缺 `_imaging`）——跑 python 一律 `PYTHONPATH=`；图标生成用带真 Pillow 的 venv。
