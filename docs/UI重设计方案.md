# RAW 归档 · 三端 UI 重设计方案

> 基线：fnOS 面板 v1.0.22（`fnos/rawarchiver/app/www/index.html`，562 行）、macOS v1.1.1（`desktop/macos/Sources/RawArchiver/ContentView.swift`，211 行）、Windows v1.1.1（`desktop/windows/RawArchiver/MainWindow.xaml`，99 行）。
> 本文件 = 设计定稿 v1.1（经后端 API 逐条核对）。§2.8 CSS 为全量可直接粘贴；§2.9/§2.10 给令牌与关键样式骨架，实施时按同名字符串补齐剩余样式。

---

## 0. 事实基座（先核对的 12 条，决定后面所有设计）

| # | 事实（源码依据） | 对设计的强制约束 |
|---|---|---|
| F1 | 后端动作全集只有 `info / doctor / devices / browse / mkdir / preview / start / status / cancel / cleanup / rollback / ledger`（`app/server.py` `handle_action`） | 界面不得出现这套动作之外的承诺 |
| F2 | `preview` 是**同步阻塞**调用（Web 走 `POST /api`，桌面走 IPC NDJSON），无中间进度事件 | 扫描段无法给真实百分比。要么「不确定进度 + 已用时 + 可解释文案」，要么改后端（P1-3） |
| F3 | `state.json` **没有 `phase` 字段**，只有 `status: pending/resuming/running/done/cancelled/error/rolled_back`（已 grep 确认 `phase` 全文不存在） | 「暂存→归档→清源」三段进度必须**派生**：依据日志前缀 `[暂存] 开始` / `[暂存] 完成` |
| F4 | `date_from` 写入的是变量 `tag`（`raw_archiver.py:602` `'date_from': tag`），可能取值不止一种 | 四态徽标必须做**容错映射 + 未知值原样显示**，不许静默归到某一档 |
| F5 | `ledger_stats()` 只返回 `total / rolled_back / outputs[{output,count}] / last_archived_at / db`（已读源码确认） | 「上月归档多少张」今天答不出；需 P1-6 加 `op=monthly`。**P0 不许给假图表** |
| F6 | 桌面 IPC（`desktop/core-ipc/ipc_main.py`）命令仅 `doctor / preview / start / cancel / cleanup / rollback / shutdown`，**无 `status` / `devices` / `ledger` / `tasks`**；但运行期会 `emit({"evt":"progress"…})` 与 `evt:"done"` | 桌面端**执行中进度可用**（靠 progress 事件流）；做不出的是「设备枚举 / 任务历史 / 台账」，需 P1-4/5 |
| F7 | `status` 只能按 `taskId` 查单个任务，`state.json` 落在 `<输出目录>/.rawarchiver/tasks/<tid>/`，无枚举接口 | 任务中心列表 P0 只能靠本地记忆（localStorage / UserDefaults / settings.json）+ 手输 taskId |
| F8 | `browse` 一次只列一级目录，返回 `{path, parent, writable, dirs[]}` | 目录选择器 = 面包屑 + 一级列表 + 跳转，不做文件夹树 |
| F9 | `devices` 枚举 `/vol00/*`、`volumeUSB*/usbshare*`、`media/*/*`、`run/media/*/*`、`mnt/usb*`，每项带 `{path,label,files}` | 空状态能真实显示「识别到 1 个设备 · 248 个文件」——最划算的一处「露能力」 |
| F10 | `optargs()` 已支持 `monthDir → --month`，还支持 `--dup-hash`（已读源码确认）；三端 UI 一个都没露 | 选项区应把「按月份分层」「全文件校验」露出来 |
| F11 | `dupGuard` 凭据 30 分钟有效、绑定 source+output+opts；`start` 带 `dupPolicy=force` 而凭据失效时返回 `code:"need_confirm"` | 「凭据失效」必须设计成**可自愈态**：原地把「重新扫描」提到主位，不弹错误框 |
| F12 | `preview` 期间没有 taskId | 扫描段**不提供取消**，用「源目录只读，关掉窗口也不会有损失」这句确定性背书替代 |

---

## 1. 设计定位与三条原则

### 1.1 定位
**「一张卡过站」的归档控制台**：不是文件管理器，不是照片浏览器。用户拿着卡进来，只做一件事——把卡上的东西**正确**落到 NAS，然后安全地把卡腾空。三个时间段决定形态：**决策段 30 秒**、**等待段 3~20 分钟**、**回查段 3 个月**；时间尺度差两个数量级，所以不能挤在同一屏。

### 1.2 三条原则（可当场检验）

**① 一屏一个主行动。** 任一时刻只有一个 `brand` 实心按钮，其余全是 ghost / outline / text。
*检验*：截任意屏，数 `background == brand` 的按钮，必须恰好 1 个。（今天首屏 5 个同级按钮 → 失败）

**② 等待必可解释。** 任何 >2 秒的等待，屏幕必须同时给出：正在做什么、到哪一步（可观察进度或诚实的「不确定」）、能不能停（不能停就说为什么）。
*检验*：录一次 300 张卡全流程，任意截图三要素缺一即失败。

**③ 危险动作长得不像家常动作。** 不可逆动作在**位置**（不在主流程卡里）、**颜色**（danger 而非 brand）、**动词**（「清空」而非「确认」）同时区别，并加一道门。
*检验*：灰度截图后危险按钮仍能与主按钮区分（靠位置与文案，不靠颜色）。

---

## 2. 设计语言 / Design Token

命名三端同名：CSS `--ra-*`，SwiftUI `RA.C/RA.F/RA.Sp/RA.R`，WPF `Ra*`。

### 2.1 颜色

不取纯白：暖灰画布 + 白卡，质感来自「1px 描边 + 极轻阴影」。

| Token | 亮色 | 暗色 | 用途 | 对比度 |
|---|---|---|---|---|
| `bg` | `#F5F6F4` | `#121614` | 应用画布 | 15.40 / 15.97 |
| `surface` | `#FFFFFF` | `#1A1F1C` | 卡片 | 16.70 / 14.62 |
| `surface2` | `#FAFBFA` | `#212723` | 表头、日志底、只读回显 | 16.10 |
| `line` | `#E2E5E1` | `#2C342F` | 1px 描边 | — |
| `lineStrong` | `#CBD2CC` | `#3A443E` | 输入框描边 | — |
| `ink` | `#16201C` | `#ECF1ED` | 正文标题 | 16.70 / 14.62 |
| `ink2` | `#4B554F` | `#B4BDB7` | 次要 | 7.74 / 8.68 |
| `ink3` | `#656F69` | `#8B958F` | 三级（时间戳/单位） | 5.21 / 5.41 |
| `brand` | `#1F7A5F` | `#45C09A` | 主色（沿用墨绿家族压深一档） | 白字 5.24 / 暗字 7.38 |
| `brandHover` | `#1A6B53` | `#5AD4AE` | 主按钮悬停 | — |
| `brandActive` | `#14563F` | `#3AAE8B` | 按下 | — |
| `brandText` | `#175C46` | `#8FE0C2` | 主色文字动作 | 7.91 / 9.90 |
| `brandSoft` | `#E7F3EE` | `#0F2A22` | 主色浅底 | — |
| `ok` | `#1E6B3C` | `#62C88A` | 成功 | 5.79 / 8.08 |
| `okSoft` | `#EAF4EE` | `#10241A` | 成功浅底 | — |
| `warn` | `#8A5A00` | `#E7B34B` | 警告（跳过/无日期） | 5.44 / 8.71 |
| `warnSoft` | `#FFF4E0` | `#241C0C` | 警告浅底 | — |
| `danger` | `#B3261E` | `#F2716B` | 危险（清源/回滚/失败） | 白字 6.54 / 5.85 |
| `dangerText` | `#7A2E14` | `#F0A587` | 低置信徽标字 | 8.24 / 8.44 |
| `dangerSoft` | `#FBEDE7` | `#2A1810` | 危险浅底 | — |
| `info` | `#1D5FA8` | `#6FB3F2` | 信息 | 5.62 / 7.48 |
| `infoSoft` | `#E8F0FA` | `#0F1E2E` | 信息浅底 | — |
| `logInk` | `#2A2F2C` | `#D7E3DB` | 日志正文 | 11.36 / 11.53 |
| `logBg` | `#E9EBE8` | `#212723` | 日志底 | — |
| `neutralSoft` | `#F0F2EF` | `#2C342F` | 中性徽标底 | — |

### 2.2 日期来源四态徽标（本方案最关键的一组语义色）

用户唯一能判断「归档位置对不对」的依据。

| 状态 | 徽标 | 说明 | 亮（字/底） | 暗（字/底） | 对比度 |
|---|---|---|---|---|---|
| A 高置信 | `EXIF` | 相机元数据（`exifread`/`pillow`/`exififd`） | `#175C46`/`#E7F3EE` | `#8FE0C2`/`#0F2A22` | 6.95 / 9.90 |
| B 中置信 | `ExifTool` | 容器元数据（`quicktime`/旧值 `exiftool`） | `#8A5A00`/`#FFF4E0` | `#E7B34B`/`#241C0C` | 5.44 / 8.78 |
| C 低置信 | `文件时间` | 兜底（`file_mtime`/`system`） | `#7A2E14`/`#FBEDE7` | `#F0A587`/`#2A1810` | 8.24 / 8.44 |
| — 跳过 | `跳过` | `unknown`：读不到日期，不拷贝 | `#4B554F`/`#F0F2EF` | `#B4BDB7`/`#2C342F` | 6.88 |

> 全部用「浅底 + 深字」而非实心块：4 个实心色块并排会抢走主按钮注意力。B 级不用 ok 绿——中置信是提醒，不是好消息。

### 2.3 字体与字号阶梯

```
UI  ：-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei",
      "Source Han Sans SC", "Noto Sans CJK SC", "Segoe UI", system-ui, sans-serif
等宽：ui-monospace, "SF Mono", "Microsoft YaHei Mono", Consolas, "Liberation Mono", monospace
```

`"Microsoft YaHei Mono"` 实际很少装，会落到 Consolas——**这是预期行为**；Windows 上没有中文等宽字体，别为它改字体名。

| Token | 字号 | 行高 | 字重 | 用途 |
|---|---|---|---|---|
| `fs-11` | 11 | 1.45 | 500 | 徽标、单位、表头（**仅限**这两处） |
| `fs-12` | 12 | 1.55 | 400 | 辅助说明、日志、时间戳 |
| `fs-13` | 13 | 1.6 | 400 | 次要正文、表格单元（macOS/WPF 正文） |
| `fs-14` | 14 | 1.65 | 400/600 | **Web/WPF 正文基准**，字段 label 600 |
| `fs-16` | 16 | 1.5 | 600 | 卡片标题 |
| `fs-20` | 20 | 1.35 | 600 | 页面标题 |
| `fs-30` | 30 | 1.25 | 600 | 结果页主数字 |

中文不用 15/17/18 这类奇数阶梯（非整数像素在中文上易出半像素抽搐）。所有计数/体积/时间码加 `font-variant-numeric: tabular-nums`。

### 2.4 间距（4 点制）

`sp-1 4` / `sp-2 8` / `sp-3 12` / `sp-4 16` / `sp-5 24` / `sp-6 32` / `sp-7 48` / `sp-8 64`。
页面左右内边距：宿主 900px 时取 `sp-4`，≥1080 取 `sp-5`。

### 2.5 圆角 / 描边 / 阴影 / 层级

`r-chip 999` / `r-1 6`（输入框、按钮、日志块）/ `r-2 10`（卡片）/ `r-3 14`（弹层、抽屉、对话框）；描边一律 1px（2px 在中文旁显脏）。
阴影：`sh-0 none`（卡片默认只有 1px line）/ `sh-1 0 1px 2px rgba(18,22,20,.06)`（悬停）/ `sh-2 0 6px 18px -6px …`（抽屉）/ `sh-3 0 18px 48px -12px …`（对话框）。
层级：`base 0 → sticky 10（吸顶进度）→ drawer 30 → modal 50`（沿用今天 `.modal{z-index:50}`，不新增层级）。

### 2.6 动效（克制）

`t-fast 120ms`（悬停/焦点）、`t-base 180ms`（展开/tab/徽标）、`t-slow 240ms`（抽屉/对话框）、`t-progress 400ms linear`（进度条，比今天 `.3s` 略慢以减噪），统一 `ease = cubic-bezier(.2,0,0,1)`，**无回弹无弹簧**。
克制条款：不做骨架屏闪光（等待是读卡不是加载网络）；不做数字滚动；`prefers-reduced-motion: reduce` 下全部 0ms。

### 2.7 暗色映射原则

暗色不是反相，是**重新配光**：底比卡片暗一档让卡片浮起；主色提亮；主按钮反过来用深色字压亮色底（`#08221A on #45C09A = 7.38`）。

### 2.8 CSS 令牌（全量，可直接粘贴）

```css
:root{
  --ra-font-ui: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei UI",
    "Microsoft YaHei", "Source Han Sans SC", "Noto Sans CJK SC", "Segoe UI", system-ui, sans-serif;
  --ra-font-mono: ui-monospace, "SF Mono", "Microsoft YaHei Mono", Consolas,
    "Liberation Mono", "DejaVu Sans Mono", monospace;

  --ra-fs-11:11px; --ra-lh-11:1.45;  --ra-fs-12:12px; --ra-lh-12:1.55;
  --ra-fs-13:13px; --ra-lh-13:1.6;   --ra-fs-14:14px; --ra-lh-14:1.65;
  --ra-fs-16:16px; --ra-lh-16:1.5;   --ra-fs-20:20px; --ra-lh-20:1.35;
  --ra-fs-30:30px; --ra-lh-30:1.25;

  --ra-sp-1:4px;  --ra-sp-2:8px;  --ra-sp-3:12px; --ra-sp-4:16px;
  --ra-sp-5:24px; --ra-sp-6:32px; --ra-sp-7:48px; --ra-sp-8:64px;

  --ra-r-chip:999px; --ra-r-1:6px; --ra-r-2:10px; --ra-r-3:14px; --ra-bw:1px;

  --ra-sh-0:none;
  --ra-sh-1:0 1px 2px rgba(18,22,20,.06);
  --ra-sh-2:0 6px 18px -6px rgba(18,22,20,.18);
  --ra-sh-3:0 18px 48px -12px rgba(18,22,20,.28);

  --ra-t-fast:120ms; --ra-t-base:180ms; --ra-t-slow:240ms; --ra-t-progress:400ms;
  --ra-ease:cubic-bezier(.2,0,0,1);

  --ra-bg:#F5F6F4;          --ra-surface:#FFFFFF;      --ra-surface2:#FAFBFA;
  --ra-line:#E2E5E1;        --ra-line-strong:#CBD2CC;
  --ra-ink:#16201C;         --ra-ink-2:#4B554F;        --ra-ink-3:#656F69;
  --ra-brand:#1F7A5F;       --ra-brand-hover:#1A6B53;  --ra-brand-active:#14563F;
  --ra-brand-text:#175C46;  --ra-brand-soft:#E7F3EE;   --ra-brand-ink:#FFFFFF;
  --ra-ok:#1E6B3C;          --ra-ok-soft:#EAF4EE;
  --ra-warn:#8A5A00;        --ra-warn-soft:#FFF4E0;
  --ra-danger:#B3261E;      --ra-danger-soft:#FBEDE7;  --ra-danger-text:#7A2E14;
  --ra-info:#1D5FA8;        --ra-info-soft:#E8F0FA;
  --ra-log-ink:#2A2F2C;     --ra-log-bg:#E9EBE8;       --ra-neutral-soft:#F0F2EF;

  --ra-conf-a-ink:#175C46;  --ra-conf-a-bg:#E7F3EE;
  --ra-conf-b-ink:#8A5A00;  --ra-conf-b-bg:#FFF4E0;
  --ra-conf-c-ink:#7A2E14;  --ra-conf-c-bg:#FBEDE7;
  --ra-conf-skip-ink:#4B554F; --ra-conf-skip-bg:#F0F2EF;
}
[data-theme="dark"]{
  --ra-bg:#121614;          --ra-surface:#1A1F1C;      --ra-surface2:#212723;
  --ra-line:#2C342F;        --ra-line-strong:#3A443E;
  --ra-ink:#ECF1ED;         --ra-ink-2:#B4BDB7;        --ra-ink-3:#8B958F;
  --ra-brand:#45C09A;       --ra-brand-hover:#5AD4AE;  --ra-brand-active:#3AAE8B;
  --ra-brand-text:#8FE0C2;  --ra-brand-soft:#0F2A22;   --ra-brand-ink:#08221A;
  --ra-ok:#62C88A;          --ra-ok-soft:#10241A;
  --ra-warn:#E7B34B;        --ra-warn-soft:#241C0C;
  --ra-danger:#F2716B;      --ra-danger-soft:#2A1810;  --ra-danger-text:#F0A587;
  --ra-info:#6FB3F2;        --ra-info-soft:#0F1E2E;
  --ra-log-ink:#D7E3DB;     --ra-log-bg:#212723;       --ra-neutral-soft:#2C342F;
  --ra-conf-a-ink:#8FE0C2;  --ra-conf-a-bg:#0F2A22;
  --ra-conf-b-ink:#E7B34B;  --ra-conf-b-bg:#241C0C;
  --ra-conf-c-ink:#F0A587;  --ra-conf-c-bg:#2A1810;
  --ra-conf-skip-ink:#B4BDB7; --ra-conf-skip-bg:#2C342F;
  --ra-sh-1:0 1px 2px rgba(0,0,0,.4);
  --ra-sh-2:0 6px 18px -6px rgba(0,0,0,.55);
  --ra-sh-3:0 18px 48px -12px rgba(0,0,0,.7);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]):not([data-theme="dark"]){ /* 与上面 [data-theme="dark"] 同值 */ }
}

*{ box-sizing: border-box; }
html,body{ margin:0; background:var(--ra-bg); color:var(--ra-ink);
  font-family:var(--ra-font-ui); font-size:var(--ra-fs-14); line-height:var(--ra-lh-14); }
:focus-visible{ outline:2px solid var(--ra-brand); outline-offset:2px; }

.ra-card{ background:var(--ra-surface); border:var(--ra-bw) solid var(--ra-line);
  border-radius:var(--ra-r-2); padding:var(--ra-sp-4); }
.ra-card__title{ font-size:var(--ra-fs-16); line-height:var(--ra-lh-16); font-weight:600;
  margin:0 0 var(--ra-sp-3); white-space:nowrap; }

.ra-btn{ display:inline-flex; align-items:center; justify-content:center; gap:var(--ra-sp-2);
  min-height:36px; padding:0 var(--ra-sp-4); border-radius:var(--ra-r-1);
  border:var(--ra-bw) solid transparent; font:600 var(--ra-fs-14)/1 var(--ra-font-ui);
  white-space:nowrap; cursor:pointer;
  transition:background var(--ra-t-fast) var(--ra-ease), border-color var(--ra-t-fast) var(--ra-ease); }
.ra-btn:active:not(:disabled){ transform:translateY(1px); }
.ra-btn:disabled{ opacity:.5; cursor:not-allowed; }
.ra-btn--primary{ background:var(--ra-brand); color:var(--ra-brand-ink); min-height:40px; padding:0 var(--ra-sp-5); }
.ra-btn--primary:hover:not(:disabled){ background:var(--ra-brand-hover); }
.ra-btn--primary:active:not(:disabled){ background:var(--ra-brand-active); }
.ra-btn--ghost{ background:transparent; color:var(--ra-ink-2); border-color:var(--ra-line-strong); }
.ra-btn--ghost:hover:not(:disabled){ background:var(--ra-surface2); color:var(--ra-ink); }
.ra-btn--outline-danger{ background:transparent; color:var(--ra-danger); border-color:var(--ra-danger); }
.ra-btn--outline-danger:hover:not(:disabled){ background:var(--ra-danger-soft); }
.ra-btn--text{ background:transparent; color:var(--ra-brand-text); min-height:32px; padding:0 var(--ra-sp-2); }

.ra-field{ display:flex; align-items:center; gap:var(--ra-sp-2); }
.ra-field__label{ flex:0 0 auto; white-space:nowrap; font-weight:600; min-width:5.5em; }
.ra-field__input{ flex:1 1 auto; min-width:0; height:36px; padding:0 var(--ra-sp-3);
  background:var(--ra-surface); color:var(--ra-ink); border:1px solid var(--ra-line-strong);
  border-radius:var(--ra-r-1); font:400 var(--ra-fs-13)/1.4 var(--ra-font-mono); }
.ra-field__input:focus{ border-color:var(--ra-brand); outline:2px solid var(--ra-brand-soft); outline-offset:0; }

.ra-badge{ display:inline-flex; align-items:center; height:22px; padding:0 var(--ra-sp-2);
  border-radius:var(--ra-r-chip); font-size:var(--ra-fs-11); line-height:1; font-weight:500;
  white-space:nowrap; }
.ra-badge--a{ color:var(--ra-conf-a-ink); background:var(--ra-conf-a-bg); }
.ra-badge--b{ color:var(--ra-conf-b-ink); background:var(--ra-conf-b-bg); }
.ra-badge--c{ color:var(--ra-conf-c-ink); background:var(--ra-conf-c-bg); }
.ra-badge--skip{ color:var(--ra-conf-skip-ink); background:var(--ra-conf-skip-bg); }

.ra-num{ font-variant-numeric:tabular-nums; }
@media (prefers-reduced-motion: reduce){ *{ transition-duration:0ms!important; animation-duration:0ms!important; } }
```

### 2.9 SwiftUI 令牌骨架（macOS 13+，纯 SwiftUI）

```swift
enum RA {
  enum C {  // 全部走动态色，自动跟随系统外观
    static let bg = Color.ra("#F5F6F4", "#121614")
    static let surface = Color.ra("#FFFFFF", "#1A1F1C")
    static let surface2 = Color.ra("#FAFBFA", "#212723")
    static let line = Color.ra("#E2E5E1", "#2C342F")
    static let lineStrong = Color.ra("#CBD2CC", "#3A443E")
    static let ink = Color.ra("#16201C", "#ECF1ED")
    static let ink2 = Color.ra("#4B554F", "#B4BDB7")
    static let ink3 = Color.ra("#656F69", "#8B958F")
    static let brand = Color.ra("#1F7A5F", "#45C09A")
    static let brandHover = Color.ra("#1A6B53", "#5AD4AE")
    static let brandText = Color.ra("#175C46", "#8FE0C2")
    static let brandSoft = Color.ra("#E7F3EE", "#0F2A22")
    static let brandInk = Color.ra("#FFFFFF", "#08221A")
    static let ok = Color.ra("#1E6B3C", "#62C88A")
    static let okSoft = Color.ra("#EAF4EE", "#10241A")
    static let warn = Color.ra("#8A5A00", "#E7B34B")
    static let warnSoft = Color.ra("#FFF4E0", "#241C0C")
    static let danger = Color.ra("#B3261E", "#F2716B")
    static let dangerText = Color.ra("#7A2E14", "#F0A587")
    static let dangerSoft = Color.ra("#FBEDE7", "#2A1810")
    static let info = Color.ra("#1D5FA8", "#6FB3F2")
    static let infoSoft = Color.ra("#E8F0FA", "#0F1E2E")
    static let logInk = Color.ra("#2A2F2C", "#D7E3DB")
    static let logBg = Color.ra("#E9EBE8", "#212723")
    static let confAInk = Color.ra("#175C46", "#8FE0C2"); static let confABg = Color.ra("#E7F3EE", "#0F2A22")
    static let confBInk = Color.ra("#8A5A00", "#E7B34B"); static let confBBg = Color.ra("#FFF4E0", "#241C0C")
    static let confCInk = Color.ra("#7A2E14", "#F0A587"); static let confCBg = Color.ra("#FBEDE7", "#2A1810")
    static let confSkipInk = Color.ra("#4B554F", "#B4BDB7"); static let confSkipBg = Color.ra("#F0F2EF", "#2C342F")
  }
  enum F {
    static let caption = Font.system(size: 11, weight: .medium)
    static let small = Font.system(size: 12); static let body = Font.system(size: 13)
    static let base = Font.system(size: 14); static let label = Font.system(size: 14, weight: .semibold)
    static let h2 = Font.system(size: 16, weight: .semibold); static let h1 = Font.system(size: 20, weight: .semibold)
    static let display = Font.system(size: 30, weight: .semibold)
    static let mono = Font.system(size: 12, design: .monospaced)
  }
  enum Sp { static let s1:CGFloat=4; static let s2:CGFloat=8; static let s3:CGFloat=12
            static let s4:CGFloat=16; static let s5:CGFloat=24; static let s6:CGFloat=32
            static let s7:CGFloat=48; static let s8:CGFloat=64 }
  enum R { static let r1:CGFloat=6; static let r2:CGFloat=10; static let r3:CGFloat=14 }
  enum T { static let fast=0.12; static let base=0.18; static let slow=0.24
           static let ease = Animation.timingCurve(0.2, 0, 0, 1) }
}

extension Color {
  static func ra(_ light: String, _ dark: String) -> Color {
    Color(nsColor: NSColor(name: nil) { ap in
      let isDark = ap.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
      return NSColor(raHex: isDark ? dark : light) })
  }
}
extension NSColor {
  convenience init(raHex hex: String) {
    var s = hex; if s.hasPrefix("#") { s.removeFirst() }
    var v: UInt64 = 0; Scanner(string: s).scanHexInt64(&v)
    self.init(srgbRed: CGFloat((v >> 16) & 0xFF)/255, green: CGFloat((v >> 8) & 0xFF)/255,
              blue: CGFloat(v & 0xFF)/255, alpha: 1)
  }
}
extension View {
  func raCard(padding: CGFloat = RA.Sp.s4) -> some View {
    self.padding(padding).frame(maxWidth: .infinity, alignment: .leading)
      .background(RA.C.surface)
      .clipShape(RoundedRectangle(cornerRadius: RA.R.r2, style: .continuous))
      .overlay(RoundedRectangle(cornerRadius: RA.R.r2, style: .continuous).stroke(RA.C.line, lineWidth: 1))
  }
}
struct RAPrimaryButtonStyle: ButtonStyle {
  func makeBody(configuration: Configuration) -> some View {
    configuration.label.font(RA.F.label).foregroundStyle(RA.C.brandInk)
      .padding(.horizontal, RA.Sp.s5).frame(minHeight: 40)
      .background(configuration.isPressed ? RA.C.brandHover : RA.C.brand)
      .clipShape(RoundedRectangle(cornerRadius: RA.R.r1, style: .continuous))
  }
}
struct RAGhostButtonStyle: ButtonStyle { /* 同上，stroke lineStrong + ink2，minHeight 36 */ }
```

### 2.10 WPF 令牌骨架（`Themes/Light.xaml` / `Themes/Dark.xaml` 同名同结构）

```xml
<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
                    xmlns:sys="clr-namespace:System;assembly=mscorlib">
  <SolidColorBrush x:Key="RaBg" Color="#F5F6F4"/>
  <SolidColorBrush x:Key="RaSurface" Color="#FFFFFF"/>
  <SolidColorBrush x:Key="RaSurface2" Color="#FAFBFA"/>
  <SolidColorBrush x:Key="RaLine" Color="#E2E5E1"/>
  <SolidColorBrush x:Key="RaLineStrong" Color="#CBD2CC"/>
  <SolidColorBrush x:Key="RaInk" Color="#16201C"/>
  <SolidColorBrush x:Key="RaInk2" Color="#4B554F"/>
  <SolidColorBrush x:Key="RaInk3" Color="#656F69"/>
  <SolidColorBrush x:Key="RaBrand" Color="#1F7A5F"/>
  <SolidColorBrush x:Key="RaBrandHover" Color="#1A6B53"/>
  <SolidColorBrush x:Key="RaBrandText" Color="#175C46"/>
  <SolidColorBrush x:Key="RaBrandSoft" Color="#E7F3EE"/>
  <SolidColorBrush x:Key="RaBrandInk" Color="#FFFFFF"/>
  <SolidColorBrush x:Key="RaOk" Color="#1E6B3C"/>       <SolidColorBrush x:Key="RaOkSoft" Color="#EAF4EE"/>
  <SolidColorBrush x:Key="RaWarn" Color="#8A5A00"/>     <SolidColorBrush x:Key="RaWarnSoft" Color="#FFF4E0"/>
  <SolidColorBrush x:Key="RaDanger" Color="#B3261E"/>   <SolidColorBrush x:Key="RaDangerText" Color="#7A2E14"/>
  <SolidColorBrush x:Key="RaDangerSoft" Color="#FBEDE7"/>
  <SolidColorBrush x:Key="RaInfo" Color="#1D5FA8"/>     <SolidColorBrush x:Key="RaInfoSoft" Color="#E8F0FA"/>
  <SolidColorBrush x:Key="RaLogInk" Color="#2A2F2C"/>   <SolidColorBrush x:Key="RaLogBg" Color="#E9EBE8"/>
  <SolidColorBrush x:Key="RaNeutralSoft" Color="#F0F2EF"/>
  <SolidColorBrush x:Key="RaConfAInk" Color="#175C46"/> <SolidColorBrush x:Key="RaConfABg" Color="#E7F3EE"/>
  <SolidColorBrush x:Key="RaConfBInk" Color="#8A5A00"/> <SolidColorBrush x:Key="RaConfBBg" Color="#FFF4E0"/>
  <SolidColorBrush x:Key="RaConfCInk" Color="#7A2E14"/> <SolidColorBrush x:Key="RaConfCBg" Color="#FBEDE7"/>
  <SolidColorBrush x:Key="RaConfSkipInk" Color="#4B554F"/><SolidColorBrush x:Key="RaConfSkipBg" Color="#F0F2EF"/>

  <FontFamily x:Key="RaFontUI">Microsoft YaHei UI, Microsoft YaHei, Segoe UI</FontFamily>
  <FontFamily x:Key="RaFontMono">Consolas, Microsoft YaHei, monospace</FontFamily>
  <sys:Double x:Key="RaFsCaption">11</sys:Double> <sys:Double x:Key="RaFsSmall">12</sys:Double>
  <sys:Double x:Key="RaFsBody">13</sys:Double>    <sys:Double x:Key="RaFsBase">14</sys:Double>
  <sys:Double x:Key="RaFsH2">16</sys:Double>      <sys:Double x:Key="RaFsH1">20</sys:Double>
  <sys:Double x:Key="RaFsDisplay">30</sys:Double>
  <sys:Double x:Key="RaSpace1">4</sys:Double>  <sys:Double x:Key="RaSpace2">8</sys:Double>
  <sys:Double x:Key="RaSpace3">12</sys:Double> <sys:Double x:Key="RaSpace4">16</sys:Double>
  <sys:Double x:Key="RaSpace5">24</sys:Double> <sys:Double x:Key="RaSpace6">32</sys:Double>
  <sys:Double x:Key="RaSpace7">48</sys:Double>
  <CornerRadius x:Key="RaR1">6</CornerRadius> <CornerRadius x:Key="RaR2">10</CornerRadius>
  <CornerRadius x:Key="RaR3">14</CornerRadius>

  <Style x:Key="RaCard" TargetType="Border">
    <Setter Property="Background" Value="{DynamicResource RaSurface}"/>
    <Setter Property="BorderBrush" Value="{DynamicResource RaLine}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="CornerRadius" Value="{StaticResource RaR2}"/>
    <Setter Property="Padding" Value="{StaticResource RaSpace4}"/>
  </Style>
  <Style x:Key="RaText" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{StaticResource RaFontUI}"/>
    <Setter Property="FontSize" Value="{StaticResource RaFsBase}"/>
    <Setter Property="Foreground" Value="{DynamicResource RaInk}"/>
    <Setter Property="TextWrapping" Value="Wrap"/><Setter Property="LineHeight" Value="23"/>
  </Style>
  <Style x:Key="RaTextH1" TargetType="TextBlock" BasedOn="{StaticResource RaText}">
    <Setter Property="FontSize" Value="{StaticResource RaFsH1}"/>
    <Setter Property="FontWeight" Value="SemiBold"/><Setter Property="LineHeight" Value="27"/>
  </Style>
  <Style x:Key="RaTextLabel" TargetType="TextBlock" BasedOn="{StaticResource RaText}">
    <Setter Property="FontWeight" Value="SemiBold"/>
  </Style>
  <Style x:Key="RaTextCaption" TargetType="TextBlock" BasedOn="{StaticResource RaText}">
    <Setter Property="FontSize" Value="{StaticResource RaFsCaption}"/>
    <Setter Property="Foreground" Value="{DynamicResource RaInk3}"/><Setter Property="LineHeight" Value="16"/>
  </Style>
  <Style x:Key="RaTextMono" TargetType="TextBlock" BasedOn="{StaticResource RaText}">
    <Setter Property="FontFamily" Value="{StaticResource RaFontMono}"/>
    <Setter Property="FontSize" Value="{StaticResource RaFsSmall}"/>
    <Setter Property="TextWrapping" Value="NoWrap"/><Setter Property="LineHeight" Value="19"/>
  </Style>

  <!-- 主按钮：必须换 Template，否则系统高光与设计不符 -->
  <Style x:Key="RaBtnPrimary" TargetType="Button">
    <Setter Property="FontFamily" Value="{StaticResource RaFontUI}"/>
    <Setter Property="FontSize" Value="{StaticResource RaFsBase}"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Foreground" Value="{DynamicResource RaBrandInk}"/>
    <Setter Property="Background" Value="{DynamicResource RaBrand}"/>
    <Setter Property="MinHeight" Value="40"/><Setter Property="Cursor" Value="Hand"/>
    <Setter Property="Template"><Setter.Value>
      <ControlTemplate TargetType="Button">
        <Border x:Name="bd" Background="{TemplateBinding Background}"
                CornerRadius="{StaticResource RaR1}" Padding="20,0">
          <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
        <ControlTemplate.Triggers>
          <Trigger Property="IsMouseOver" Value="True">
            <Setter TargetName="bd" Property="Background" Value="{DynamicResource RaBrandHover}"/></Trigger>
          <Trigger Property="IsEnabled" Value="False">
            <Setter TargetName="bd" Property="Opacity" Value="0.5"/></Trigger>
        </ControlTemplate.Triggers>
      </ControlTemplate>
    </Setter.Value></Setter>
  </Style>
  <!-- RaBtnGhost / RaBtnDangerOutline 结构相同，只换笔刷 -->
</ResourceDictionary>
```

暗色主题：同名同结构，仅换 `Color` 值（`RaBg #121614`、`RaSurface #1A1F1C`、`RaSurface2 #212723`、`RaLine #2C342F`、`RaLineStrong #3A443E`、`RaInk #ECF1ED`、`RaInk2 #B4BDB7`、`RaInk3 #8B958F`、`RaBrand #45C09A`、`RaBrandHover #5AD4AE`、`RaBrandText #8FE0C2`、`RaBrandSoft #0F2A22`、`RaBrandInk #08221A`、`RaOk #62C88A`、`RaWarn #E7B34B`、`RaDanger #F2716B`、`RaDangerText #F0A587`、`RaInfo #6FB3F2`、`RaLogInk #D7E3DB`、`RaLogBg #212723`、置信度四组对应暗值）。

```csharp
public static class RaTheme {
  /// 约定：Themes/Tokens.xaml 常驻 index 0，主题字典常驻 index 1
  public static void Apply(bool? dark = null) {
    var want = dark ?? IsSystemDark();
    var uri = new Uri(want ? "Themes/Dark.xaml" : "Themes/Light.xaml", UriKind.Relative);
    var merged = Application.Current.Resources.MergedDictionaries;
    if (merged.Count > 1) merged.RemoveAt(1);
    merged.Insert(1, new ResourceDictionary { Source = uri });
  }
  public static bool IsSystemDark() {
    using var k = Registry.CurrentUser.OpenSubKey(
      @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
    return k?.GetValue("AppsUseLightTheme") is int i && i == 0;
  }
  public static void FollowSystem() {
    Apply(null);
    SystemEvents.UserPreferenceChanged += (_, _) =>
      Application.Current.Dispatcher.Invoke(() => Apply(null));
  }
}
```

> **诚实退化**：WPF 的 `DataGrid`/`ScrollBar`/`ComboBox` 默认模板有硬编码色，换字典只能覆盖约 70%。P0 的做法是**表格改用自绘 `ItemsControl`**（同时解决徽标列与断行控制）；`ScrollBar`/`ComboBox` 模板留 P1-8，否则暗色会出「白底表格」破窗。

---

## 3. 信息架构重构

```
┌ 工作台 WORKBENCH ── 30 秒决策 + 3~20 分钟等待 + 立刻看结果
│  认卡(devices) → 定目标(browse) → 选项 → 扫描(preview) → 确认门 → 执行(start/status/cancel) → 结果卡
│  顶部一条「最近一次」轻量回填，不另开页
├ 任务中心 TASKS ── 分钟~月（回查、续跑、台账、危险区）
│  任务列表 → 详情抽屉 → 续跑 / 台账统计 / 报告入口 / 危险区
├ 维护 MAINTENANCE ── 月~年（低频）
│  自检 doctor / 台账维护(rebuild,prune) / 品牌与格式说明（原 intro 搬这里） / 版本与目录
```

**为什么这样切（三条可检验理由）**

1. **注意力预算**。今天 intro 那段（品牌表 + 格式表 + HEIC 说明）占首屏约 1/3，是**一年看一次**的信息；「开始归档」是**每张卡必点**。按频次排序，低频信息必须移出决策屏。
2. **危险动作物理隔离**。「回滚」「补清源」今天与「预览」同排同色，本质是被放在**决策路径上**。移到详情抽屉后，误触路径从 1 步变 3 步。
3. **长等待需要专属屏幕**。执行中不是表单的第 7 区块，而是一个页面状态（SwiftUI 里 `progressSection` 与 `previewSection` 堆在同一 VStack，滚动一变就分不清）。

### 3.1 三端导航形态

| 端 | 呈现 | 尺寸 | 理由 |
|---|---|---|---|
| fnOS Web | 顶部 3 段 segmented tabs，内容单列 `max-width:860px`，随宿主流式 | 900px 宿主 → 内容 828 可用；<900 内边距降 16；≥1080 才允许「源/目标」两列 | 面板嵌在宿主 iframe 内，宿主已有左侧导航；再加侧栏 = 导航里的导航，且 900px 下 180px 侧栏会挤掉路径列 |
| macOS | `NavigationSplitView` 侧栏（190–220px）+ 详情，侧栏底部固定「自检状态」小行 | 最小 900×620，默认 1040×700 | macOS 13 原生控件；桌面有空间，层级可常驻 |
| Windows | 左 180px 竖向 `ListBox` 导航（图标 + 标签 + 选中 3px brand 竖条）+ 右内容 | 默认 1120×760，最小 960×640 | 不引第三方 UI 库；自绘 30 行即 NavigationView 等价物；固定 1020×840 在高 DPI 多屏下会被裁 |

三端一致锚点：三个 tab 的名字/顺序/图标语义一致（工作台=进站、任务=记录、维护=检修）。图标：SF Symbols `square.stack.3d.up` / `clock.arrow.circlepath` / `wrench.and.screwdriver`；Segoe Fluent `\uE7C3` / `\uE81C` / `\uE90F`；Web 内联 SVG 24×24、1.5px 描边。

### 3.2 工作台状态机

```
EMPTY ──插卡/选源──▶ READY ──扫描──▶ SCANNING ──完成──▶ REVIEWED
  ▲                    │                 │(只读,不可取消)    │确认门①②
  └────清空选择────────┘                 ▼                  ▼
                                   SCAN_FAILED        RUNNING ─▶ DONE / CANCELLED / ERROR
```

`REVIEWED` 是**易失态**：源、目标、任一选项变化即回 `READY`（等价 `dupGuard` 绑定 source+output+opts 的语义）。凭据失效 → 选项区顶部一条 `warn` 提示 + 「重新扫描」升为主位，**不弹错误框**。

---

## 4. 核心界面线框（以 900px 宿主宽度为准，1 汉字 ≈ 2 列）

### 4.1 (a) 首次使用空状态

```
┌──────────────────────────────────────────────────────────────────────┐ 900
│  RAW 归档                              工作台│任务│维护      ⚙ 自检● │ 56
├──────────────────────────────────────────────────────────────────────┤
│                          ┌────────────┐                              │
│                          │   ▢  ▢  ▢   │  ← 内联 SVG：卡 + NAS，120×120│ 64
│                          └────────────┘                              │
│                       把卡插上，我来归档                              │ 20/600
│     我会按照片里记录的拍摄日期，把它们整理进 NAS 的「年/月/日」目录。   │ 14/ink2
│     源目录只读，我不会在卡上留下任何文件。                             │ 14/ink2
│                          [ 选择源目录 ]     ← 唯一主行动，40 高        │
│                          [ 手动输入路径 ]   ← 文本按钮，见不到卡时    │
│  ─────────────────────────────────────────────────────────────────   │
│  已识别到 1 个可移动设备                                             │ 13/ink2
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ MassStorageClass      /vol00/MassStorageClass     248 个文件    │  │ 44
│  │                                        [ 就用这张卡 ]          │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  还没有设置归档落点  →  [ 现在设置 ]                                  │ 13/text
└──────────────────────────────────────────────────────────────────────┘
```

「已识别到 N 个设备 · 248 个文件」来自 `devices` 真实计数（F9）。空状态三段文案 = **能做什么 / 会怎么处理 / 不会做什么**，最后那句是安全承诺。

### 4.2 (b) 主工作台（含最近一次回填）

```
┌──────────────────────────────────────────────────────────────────────┐
│ ┌ 最近一次 ────────────────────────────────────────────── ghost ────┐│
│ │ 10-20 09:12 · 124 张 / 3.4 GB → /volume1/photos/Camera · 完成     ││ 40
│ │ 这张卡现在已清空                     [ 查看记录 ]  [ 再来一次 ]   ││
│ └────────────────────────────────────────────────────────────────────┘│
│ ┌ ① 源 ─────────────────────────────────────────────────────────────┐│
│ │ 源目录*  [/vol00/MassStorageClass/DCIM              ]  [选择…]    ││ 36
│ │          已识别为可移动设备 · 248 个可归档文件                     ││ 20/ink3
│ └────────────────────────────────────────────────────────────────────┘│
│ ┌ ② 目标 ────────────────────────────────────────────────────────────┐│
│ │ 归档到*  [/volume1/photos/Camera                    ]  [浏览…]    ││ 36
│ │          可写 · 上次用过 · 剩余 214 GB                             ││ 20/ink3
│ └────────────────────────────────────────────────────────────────────┘│
│ ┌ ③ 整理方式 ────────────────────────────────────────────────────────┐│
│ │ 目录结构  (•) 按日期 YYYYMMDD/     ( ) 按日期 + 月份               ││ 36
│ │           [✓] 再按相机品牌分层                                     ││ 28
│ │ ────────────────────────────────────────────────────────────────── ││
│ │ 包含      [✓] RAW   [✓] JPG   [✓] 视频                            ││ 28
│ │ 重复处理  (•) 跳过已归档的（推荐）  ( ) 重新处理并生成副本          ││ 36
│ │ 高级      [✓] 先拷到 NAS 暂存再归档（读卡更稳，占 NAS 空间）        ││ 28
│ │           [ ] 全文件校验（极慢，只在怀疑重复时用）                  ││ 28
│ └────────────────────────────────────────────────────────────────────┘│
│ ┌ ④ 扫描结论 ────────────────────────────────────────────────────────┐│
│ │ (空状态) 还没有扫描。点「扫描这张卡」先看一眼会发生什么。            ││
│ └────────────────────────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────────────┤
│                                   [ 重新扫描 ]   [ 扫描这张卡 → ]    │ 64 sticky
└──────────────────────────────────────────────────────────────────────┘
```

要点：唯一的 brand 实心按钮在 sticky 底栏；选项从「6 checkbox 平铺 + 1 下拉」改为 **4 组语义分块**（结构 / 包含 / 重复处理 / 高级），每组 ≤3 项；「按品牌分层」不再与「处理 JPG」同权重（前者改落点结构，后者是内容筛选）；`--month`、`--dup-hash full` 在这里露出（F10）。

### 4.3 (c) 预览确认页

```
┌ ┌ 扫描结论 ─────────────────────────────────────────────────────────┐
│ │ 248 个文件 · 12.4 GB · 日期 2024-05-01 ~ 2026-10-18               │ 24/600
│ │ ┌──────────┬──────────┬──────────┬──────────┬──────────┐          │
│ │ │ 新文件   │ 已归档   │ 待校验   │ 同名冲突 │ 无日期   │          │ 56
│ │ │  121     │  124     │   3      │    0     │    0     │          │
│ │ │ 将归档   │ 会跳过   │ 逐张核对 │ 会加 _1  │ 会跳过   │          │
│ │ └──────────┴──────────┴──────────┴──────────┴──────────┘          │
│ │ 日期来源  ██████████████████████░░░░  高置信 228 · 中 17 · 低 0   │ 32
│ ├──────────────────────────────────────────────────────────────────┤
│ │ ⚠ 这张卡处理过：2026-10-20 09:12，124 个文件已归档（3.4 GB）       │ warn
│ │   默认跳过它们，只处理新的 121 个。想重建结构？改「重复处理」。     │
│ ├──────────────────────────────────────────────────────────────────┤
│ │ 文件清单（共 248，显示前 500）                        [ 展开 ⌄ ]    │ 36
│ │ ┌──────────────────┬──────────┬────────────┬────────────────────┐ │
│ │ │ 源文件           │ 拍摄日期 │ 日期来源   │ 归档到             │ │
│ │ │ IMG_0001.CR3     │2024-05-06│ [EXIF]     │20240506/IMG_000…   │ │
│ │ │ VID_0002.MP4     │2024-05-07│ [ExifTool] │20240507/VID_000…   │ │
│ │ │ IMG_0003.JPG     │2024-05-07│ [文件时间] │20240507/IMG_000…   │ │
│ │ │ IMG_0004.CR3     │    —     │ [跳过]     │不归档              │ │
│ │ └──────────────────┴──────────┴────────────┴────────────────────┘ │
│ └──────────────────────────────────────────────────────────────────┘
│ ┌ 确认门 ────────────────────────────────────────────────────────────┐
│ │ 模式：移动（归档后清空这张卡）  ← 来自 ③ 的只读回显                │
│ │ ☐ 我知道：归档完成后，这张卡上的 248 个文件会被删除，无法撤销。      │ 36
│ └────────────────────────────────────────────────────────────────────┘
├──────────────────────────────────────────────────────────────────────┤
│                      [ 改选项 ]    [ 归档并清空这张卡 → ]            │ 64
│                            ↑ 危险模式下主按钮由 brand 变 danger 实心
```

**两道门（是「条件」不是「两个弹窗」）**
- **门①（型号门，常驻）**：`REVIEWED` 才启用主按钮；源/目标/选项任一变化立即回 `READY`。
- **门②（后果门，条件性）**：`removable && move` → 主按钮变 danger 实心、文案含「清空」，且**必须勾选**后果复选框（比弹窗更难误过）；`dupPolicy=force` → 必须勾选「我知道会产生 _1/_2 副本」。两者同时成立则两个框都要勾。

置信度分布条替代今天那句「ExifTool: 可用/未找到」——用户不关心工具名，关心「有多少张靠猜」。

### 4.4 (d) 执行中

```
┌ ┌ 正在归档 ────────────────────────────────────────  [ 停止归档 ] ──┐
│ │ ① 暂存 ──── ② 归档 ──── ③ 清源                                  │ 40
│ │ ●完成        ●进行中      ○未开始                                │
│ │ ████████████████████████████░░░░░░░░░░  62%                     │ 12
│ │ 121 / 194 个文件    已用 4 分 12 秒    约剩 2 分 40 秒           │ 20
│ │ 成功 118    失败 1    跳过 2                                     │ 20/ink2
│ │ ┌ 当前 ────────────────────────────────────────────────────────┐ │
│ │ │ DCIM/100CANON/IMG_1866.CR3                                   │ │ 28/mono
│ │ │ → 20261018/IMG_1866_20261018.CR3                             │ │ 28/mono/ink3
│ │ └──────────────────────────────────────────────────────────────┘ │
│ ├ 日志 ──────────────────────────────────────────────── [展开 ⌄] ─┤
│ │ 15:32:07 ✓ IMG_1864.CR3 → 20261018/…                          │ 3 行折叠
│ │ 15:32:08 ⚠ IMG_1865.NEF 无拍摄日期，跳过                       │
│ │ 15:32:09 ✗ IMG_1866.CR3 写入失败：磁盘配额不足（详见报告）      │
└──────────────────────────────────────────────────────────────────────┘
```

- **阶段条派生**（F3）：`status=="resuming"` → 整条换成「续跑中：已处理 N 个」；日志见 `[暂存] 开始` 未见 `[暂存] 完成` → 亮①；见 `[暂存] 完成` 或无暂存 → 亮②；点 `cleanup` 期间 → 亮③。复制模式 + 不可移动源只显示两段（不造假的第三段）。
- **ETA**：无字节进度，用「个/秒」+ EMA（近 30 秒）算；`current < 10` 或运行 < 8 秒显示「剩余时间计算中」，绝不显示 0 秒或负数。
- **日志折叠**：默认最近 3 行；**失败行永远钉住**（即使不在最近 3 行），防止「跑完才发现有失败」。
- **停止按钮**：`outline-danger` 放卡片右上（不争底部空间）；点了不弹确认（停止是安全操作），立刻变「正在停止…」并禁用（防连点写第二个 cancel 标记）。

### 4.5 (e) 完成 / 结果卡

```
┌ ┌ 归档完成 ──────────────────────────────────────────────────────────┐
│ │    121          2          1           124        4 分 38 秒       │ 30/600
│ │    已归档       跳过       失败        已存在     总用时           │
│ │    12.4 GB →  /volume1/photos/Camera                              │ 13/mono
│ │    报告：/volume1/photos/Camera/log/_report_20261023_153000.json  │ 12/mono/ink3
│ ├────────────────────────────────────────────────────────────────────┤
│ │ 下一步   [ 打开目标目录 ]   [ 查看报告 ]   [ 再来一张卡 ]          │ 40
│ ├ 危险区（这张卡还在，否则整块隐藏） ───────────────────────────────┤
│ │ ⚠ 这 121 个文件的源文件还在卡上，可以清空。                         │ 13/warn
│ │   清空前会逐个校验「目标存在且大小一致」，不一致的会保留。          │ 12/ink3
│ │   [ 清空源文件 ]                        ← outline-danger           │ 36
│ │   ☐ 我确认清空这 121 个源文件，跳过 2 个与失败 1 个会保留          │ 32
│ └────────────────────────────────────────────────────────────────────┘
│ ┌ 出错怎么办 ────────────────────────────────────────────────────────┐
│ │ [ 撤回归档 ]  ← 仅「复制」模式渲染；移动模式整块不渲染             │ 36
│ └────────────────────────────────────────────────────────────────────┘
```

- 结果**不用 alert**（今天 Web 用 `alert('RAW 归档完成…')`）。结果是一个页面区块，因为用户接下来要在这里核对、清卡、看报告。
- 「清空源文件」是**条件显隐**：仅 `copy && removable && 有 to_delete`；move 模式下整块替换为 ok 色文案「这张卡已在归档过程中清空」——消灭今天「补清源」在 move 后必然报错的尴尬。
- 「撤回归档」在 move 模式**不渲染**（不渲染灰按钮 + 不弹「无法回滚」的死路 alert）。

### 4.6 (f) 任务历史 + 台账

```
│ 任务                                                               │
│ ┌ 台账 ────────────────────────────────────────────────────────────┐
│ │ 累计已归档 3 842 个   已回滚 12 个   最近 2026-10-20 09:12        │ 20
│ │ 落点 /volume1/photos/Camera 3 718 · /volume2/backup 124          │ 13/ink2
│ │ (月度明细需后端补 ledger op=monthly，见 P1-6)                     │ 11/ink3
│ └──────────────────────────────────────────────────────────────────┘
│ ┌ 任务列表 ────────────────────────────────────────────────────────┐
│ │ 时间          源                张数  体积   结果                  │
│ │ 10-20 09:12  MassStorageClass/… 124  3.4 GB ● 完成      [详情]   │ 44
│ │ 10-18 20:31  SanDisk/DCIM       194  5.1 GB ● 完成      [详情]   │ 44
│ │ 10-12 14:02  MassStorageClass/…  88  2.2 GB ◐ 已停止    [续跑]   │ 44/高亮
│ │ 只显示本地记录的任务。完整列表需后端补 tasks 动作（P1-5）。        │ 11/ink3
│ └──────────────────────────────────────────────────────────────────┘
│  ┌ 详情抽屉（右侧滑入，宽 420，遮罩 sh-3）───────────────────────┐ │
│  │ 任务 20261012_140211_7742                            [×]     │ │
│  │ 状态 已停止（第 88 个文件处）                                 │ │
│  │ 源 /vol00/MassStorageClass/DCIM   目标 /volume1/photos/Camera │ │
│  │ 选项 复制 · 按日期 · RAW+JPG · 暂存                           │ │
│  │ 结果 成功 71 · 跳过 15 · 失败 2 · 未处理 106                  │ │
│  │ 记录 …/log/rawarchiver_20261012_140211_7742.log              │ │
│  │ [ 继续未完成的任务 ]   ← primary，唯一实心                    │ │
│  │ ── 危险区 ──────────────────────────────────────────────────  │ │
│  │ 这两个操作会动 NAS 上的真实文件，且不可撤销。                  │ │
│  │ [ 清空源文件 ]   [ 撤回归档 ]                                 │ │
│  └──────────────────────────────────────────────────────────────┘ │
```

「已停止/出错」行**行内直接给 `[续跑]`**（少一次点击）；台账块只写 `ledger stats` 能给的字段（F5），并明写缺什么，不给假图。

---

## 5. 组件规范

### 5.1 字段行

```
┌ 标签（14/600，nowrap，min-width:5.5em）
│ ┌ 输入（36 高，mono 13，flex:1，min-width:0）                ┐ [选择…] ghost 36
└ 辅助行（恒定 20 高占位，13/ink3，错误转 danger + 前置 ✗ SVG）
```

| 状态 | 描边 | 辅助行 |
|---|---|---|
| 默认 | 1px `lineStrong` | 灰说明（可写性 / 上次用过 / 剩余空间，来自 `browse.writable`） |
| 聚焦 | 1px `brand` + 2px `brandSoft` 外环（**不用 box-shadow**，暗色会脏） | 不变 |
| 错误 | 1px `danger` | `danger` 色，文案直接用后端 `check_source_readable()` 原话（含「文件管理 → 设置 → 外接存储权限」） |
| 只读回显 | 无描边，`surface2` 底 | 说明（预览页「模式：移动」） |
| 禁用 | 描边 `line`，字 `ink3` | **说明保留**，用户要知道为什么不能点 |

硬规则：辅助行高度恒定，错误出现不许把下方内容顶下去（避免点击位移导致误点）。

### 5.2 卡片
内边距 16 / 间距 16 / 圆角 10 / 1px line / 默认无阴影（可点卡片悬停起 `sh-1`）。标题行右侧只放**与本卡直接相关**的动作；跨区块动作一律出卡片到底部 sticky 条。**不做嵌套卡片**（暗色下三层灰会糊边界），分组用 12px 缩进 + 左侧 2px line 竖线。

### 5.3 危险区（四要件缺一不可）

```
▌ 危险区                                              ← 左侧 3px danger 竖条
▌ 这两个操作会动 NAS 上的真实文件，做完不能撤销。      ← 13/ink2，先说后果
▌ [ 清空源文件 ]   [ 撤回归档 ]                        ← outline-danger，36 高
▌ 清空前会逐个校验「目标存在且大小一致」；不过的保留。 ← 12/ink3
```

1. 位置：只在任务详情抽屉底部 / 结果卡底部，**永不出现在工作台选项区**。
2. 颜色：`danger` 描边 + `danger` 字，悬停才 `dangerSoft` 底；**永不做 danger 实心**（实心红最容易被当成主行动）。
3. 动词：`清空` / `撤回`，不用 `确认` / `执行` / `提交`。
4. 第二道门：点击后走 §5.8 三段式确认框，主按钮仍 outline-danger 且重复对象与数量。

### 5.4 日期来源徽标（四态）

高度 22 / 圆角 chip / 11px 500 / `padding 0 8` / 不描边。映射必须**容错**：命中组名显示对应档；未命中 → 显示原名（截断 8 字符）+ `neutralSoft` 底 + tooltip「未知来源」，**禁止静默归到某档**（会误导落点判断）。表格里该列固定 92px + nowrap。

| 徽标 | tooltip |
|---|---|
| `EXIF` | 相机写入的拍摄日期 |
| `ExifTool` | 视频容器里的时间，通常等于拍摄时间 |
| `文件时间` | 文件被修改的时间，可能不是拍摄时间 |
| `跳过` | 读不到拍摄日期，不会拷贝；照片不猜日期 |

### 5.5 进度条与阶段条

| 阶段 | 判定 | 副标题 |
|---|---|---|
| ① 暂存 | 日志含 `[暂存] 开始` 且未含 `[暂存] 完成` | 先把文件安全读进 NAS，卡这时不能拔 |
| ② 归档 | 见 `[暂存] 完成`，或无暂存且 `status=running` | 正在按日期落位 |
| ③ 清源 | 用户点了 cleanup（前端态） | 正在校验后删除源文件 |
| 续跑 | `status=="resuming"` | 续跑中：已处理 N 个，从断点继续 |
| 不确定 | `status=="pending"` 且 `total==0` | 30% 宽 brand 段 1.6s 循环平移（reduced-motion 下静态） |

三条硬约束：① 进度条**必须有数字**（用户要的是「还剩几个」）；② 不造假阶段（不可移动源只有两段）；③ 失败计数实时可见。

### 5.6 日志控制台

| 属性 | 规范 |
|---|---|
| 字体 | mono 栈 / 12px / 行高 1.5（中文落到 PingFang/YaHei，宽度略不均，可接受；别为「全中文等宽」找字体） |
| 折叠 | 执行中 3 行（失败行钉住）；完成后 1 行摘要「共 194 行 · 失败 1」 |
| 展开 | 200px（≈10 行），不超过视口 40% |
| 跟随 | 默认滚底；距底 > 24px 即暂停并浮出「↓ 回到最新」 |
| 复制 | 复制全部（含折叠），末尾附 `任务 <taskId> · <输出目录>/log/rawarchiver_<taskId>.log` |
| 级别 | 只用色点（ok/warn/danger/ink2），**不整行染色**（暗色下对比度会崩） |
| 行格式 | `[时间] 级别点 源相对路径 → 目标相对路径`，路径允许 `/` 后断行，`_`/`-` 处禁止断 |

⚠️ 三端唯一必须不同的实现细节：**Web 的 `status` 每次回最近 80 条 → 整块替换；桌面 IPC 是增量 `evt:"progress"` → 追加**。写进代码注释。

### 5.7 目录选择器

| 端 | 首选 | 回落 1 | 回落 2 | 绝对不做 |
|---|---|---|---|---|
| fnOS Web | 飞牛 SDK `sdk.pickSharedFile({sidebarGroup:[…], disabledPaths:[], creatable:false})` 180s 超时 | `window.open('/app-auth/pick-shared-file…')` + `postMessage`（120s） | 内置目录浏览器 modal（`browse`：面包屑 + 一级列表 + 跳转 + 上级） | `<input webkitdirectory>`；拖拽 |
| macOS | `NSOpenPanel`（`DirectoryPicker.swift` 已有） | — | — | AppKit 重活 |
| Windows | `FolderBrowserDialog` / `IFileDialog` | 手输路径 | — | 自绘树 |

**fnOS 为什么不能用原生目录框**（写进注释，防止以后被「优化」掉）：① `<input webkitdirectory>` 只给文件相对路径，拿不到服务端绝对路径；② 面板跑在宿主 iframe 里，被授权的目录只有宿主 SDK 知道（`disabledPaths` 不传空数组会让已选目录变灰——代码注释已写明）；③ 所以必须有三级回落，回落到内置浏览器时标题栏要注明「当前目录由应用自行浏览，未经过宿主授权」。

内置 modal：面包屑（`/volume1 ▸ photos ▸ Camera`）+ 跳转输入 + 一级列表（单层，最多 200 项）+ 「可写 · 23 个子目录」+「新建文件夹」（`mkdir` 后端已有，UI 没露）+ [取消][选这里]。

### 5.8 确认对话框（三段式，顺序不许换）

```
标题：<动词> + <对象> + <数量>
段1 发生了什么：只陈述事实，不评价
段2 为什么不可逆：说清物理原因与唯一补救路径
段3 怎么办（逃生门）：给出「先别做」的替代动作
主按钮：<动词> + 数量（保持 outline-danger）
副按钮：<缓一步的动作>（默认焦点在此，回车落在副按钮）
```

**T1 · 清空源文件**
> 标题：清空这张卡上的 121 个文件
> 段1：这 121 个文件已归档到 /volume1/photos/Camera。另有 2 个跳过、1 个失败，这 3 个不会被删除。
> 段2：删除后无法通过「撤回归档」恢复，只能从 NAS 手动拷回卡里。
> 段3：想先核对？点「先打开目标目录看一眼」。
> 主：[ 清空这 121 个文件 ]　副：[ 先打开目标目录看一眼 ]

**T2 · 撤回归档**
> 标题：把 121 个文件从归档目录撤回
> 段1：文件会移到 /volume1/photos/Camera/_restored/<taskId>/，按日期建好的目录会留下空文件夹。
> 段2：移动模式的任务无法撤回（源已删除）；本任务为复制模式，可以撤回。
> 段3：撤回常用于「重跑一次以重建结构」，重跑前请确认选项已改对。
> 主：[ 撤回这 121 个文件 ]　副：[ 先看看报告 ]

**T3 · 重新归档（force）**
> 标题：重新归档 124 个已归档文件
> 段1：重新处理不会覆盖原文件，而是在旁边新增 124 个带 `_1`/`_2` 的副本，NAS 多占约 3.4 GB。
> 段2：副本无法批量区分新旧，事后清理只能靠后缀人工辨认。
> 段3：如果只想确认「它们真的在」，不用重跑——任务页台账就能看。
> 主：[ 重新归档并生成副本 ]　副：[ 不重跑 ]

技术规范：遮罩 `rgba(0,0,0,.45)`，宽 `min(480px,92vw)`，圆角 14，`sh-3`，`Esc` 关闭，焦点默认副按钮，Tab 循环锁在框内，关闭后焦点回触发按钮。

---

## 6. 关键流程：插卡 → 拔卡

| 步 | 屏幕状态 | 用户可见反馈 | 允许的操作 | 门 |
|---|---|---|---|---|
| 1 插卡 | `EMPTY` | 3 秒内出现「已识别到 1 个可移动设备 · MassStorageClass · 248 个文件」（`devices` 6s 轮询） | 就用这张卡 / 选择源目录 / 手输 | — |
| 2 定目标 | `READY` | 「可写 · 上次用过 · 剩余 214 GB」；不可写立刻转 danger 并给飞牛改权限原话 | 浏览 / 手输 / 新建文件夹 | 目标不可写 → 主按钮禁用（门①的一部分） |
| 3 选项 | `READY` | 每组选择即时改摘要句（如选「按日期+月份」→「落点形如 2024/20240506/」） | 改结构/包含/重复/暂存 | 改任一项清空上次扫描结论并提示「需重新扫描」（门①重置） |
| 4 扫描 | `SCANNING`（长等待） | 不确定进度 + 已用时（每秒）+ 轮换安抚文案 + 「源只读，关窗无损失」 | 无取消（无 taskId）；可切任务页；可关窗 | — |
| 5 预览确认 | `REVIEWED` | 摘要条 + 五格统计 + 置信分布 + 冲突提示 + 前 500 条清单 | 改选项 / 展开 / 勾选后果 | **门①**（有效 dupGuard）；**门②**（move+可移动 或 force 的勾选） |
| 6 执行 | `RUNNING` | 阶段条 + `current/total` + 成功率 + 失败数 + 当前文件 + ETA + 折叠日志 | 停止归档（不弹确认，点后禁用以防连点） | — |
| 7 结果 | `DONE/CANCELLED/ERROR` | 四数字 + 总用时 + 目标 + 报告路径 | 打开目录 / 看报告 / 再来一张 /（条件）清空 /（条件）撤回 | **门③**：清源需勾选；撤回走 T2 |
| 8 拔卡 | 回 `EMPTY`（卡已清空则文案变「这张卡现在是空的，可以安全拔出」） | 顶部 ok 提示 3 秒淡出 | 直接拔（**产品不检测拔出，不弹任何东西**） | — |

步 4 的轮换文案（每 20 秒切，纯前端不假进度）：
- 0–20s：「正在读卡上的文件信息…」
- 20–60s：「文件多时要读几分钟，读完先给你清单，不会直接开始拷」
- 60s+：「还在读。卡在转，别拔。想看进度可去『任务』页看上次记录。」
- 240s+：「超过 4 分钟了，上千文件的卡这是正常的。如果像卡住了，关掉面板再打开，不会留下任何东西。」

---

## 7. 文案规范

### 7.1 按钮动词表（禁复合词）

| 场景 | 用 | 禁用 |
|---|---|---|
| 扫描 | 扫描这张卡 / 重新扫描 | 预览（用户不知道预览什么）、开始扫描预览 |
| 启动归档 | 开始归档 | **确认并开始**（一钮两动词，用户不知在确认什么）、一键归档、立即执行 |
| 危险启动 | 归档并清空这张卡 | 确认（不带对象与数量） |
| 停止 | 停止归档 | 取消（取消任务还是取消对话框？）、中止 |
| 清源 | 清空源文件 / 清空这 121 个文件 | 补清源（内部术语）、清理 |
| 回滚 | 撤回归档 | 回滚（技术词）、还原 |
| 打开 | 打开目标目录 | 打开文件夹 |
| 续跑 | 继续未完成的任务 | 断点续传、恢复 |
| 重处理 | 重新归档并生成副本 | 强制覆盖（并不覆盖） |
| 报告 | 查看报告 | 下载 JSON |

### 7.2 错误消息三段式（事实 / 原因 / 怎么办，每段一句，总长 ≤60 字）

| 场景 | 文案 |
|---|---|
| 源不可读 | **读不到这个目录。**「/vol00/MassStorageClass」对当前账户没有读权限，飞牛默认只让 root 看外接盘。**去「文件管理 → 设置 → 外接存储权限」改成「所有账户可见」，回来重试。** |
| 源不存在 | **这个路径下没有目录。**卡可能已拔，或路径打错。**点「选择源目录」重挑一次。** |
| 输出不可写 | **归档目录不能写。**「/volume1/photos」缺写权限或磁盘已满。**换个目录，或去飞牛给它加写权限。** |
| 源与输出互相包含 | **源和目标是同一个地方。**归档目录不能在卡里，卡也不能在归档目录里，否则无限套娃。**把归档目录换到卡以外。** |
| 凭据失效 | **这次确认过期了。**预览结果 30 分钟内有效，改选项或放太久都会失效。**点「重新扫描」再确认一次。** |
| 任务不存在 | **找不到这个任务。**任务记录只在本机应用数据里，换机或清过数据就没了。**从「任务」页本机记录里挑一个。** |
| 清源时源不可访问 | **卡不在了。**「/vol00/…」当前访问不到。**插回去再清空；文件已在 NAS 上，不插卡也不会丢。** |

排版：事实段 `danger` 600 / 原因段 `ink2` / 动作段 `brandText` + 内联箭头。放在字段辅助行或卡片顶部提示条，**不用 alert**（除真正的模态确认）。

### 7.3 空状态文案（能做什么 / 会怎么处理 / 不会做什么）

| 位置 | 文案 |
|---|---|
| 工作台首屏 | 把卡插上，我来归档。／我会按照片里的拍摄日期，整理进 NAS 的「年/月/日」目录。／源目录只读，我不会在卡上留下任何文件。 |
| 未设目标 | 还没有设置归档落点。／归档会落到你指定的 NAS 目录，不存在会自动建。／现在设置 → |
| 无设备 | 没看到可移动设备。／卡插上了但没显示，通常是外接存储权限没开。／手动输入路径 → |
| 未扫描 | 还没有扫描。／先看一眼会发生什么，再决定要不要归档。／[扫描这张卡] |
| 任务为空 | 还没有任务记录。／每归档一张卡，这里会留一条。／去工作台 → |
| 台账为空 | 台账还是空的。／第一次成功归档后就会有统计。／（不给假图表） |
| 日志为空 | 还没有日志。／开始归档后，这里会实时显示每个文件的去向。 |

### 7.4 破坏性措辞五条
① 动词优先于形容词（「清空」> 「危险」）；② 必带数量与对象（「清空 121 个文件」）；③ 必须说保留什么（「跳过 2 个与失败 1 个会保留」）；④ 不单独写「不可恢复」吓人，要写**为什么**（「只能从 NAS 手动拷回」）；⑤ 不用感叹号、不用「⚠️ 警告」大标题。

### 7.5 标点与单位
全角中文标点 / 中英数字间加半角空格（「按 EXIF 拍摄日期」「共 248 个文件」）/ 数字与英文单位间加空格（`12.4 GB`）、中文单位不加（「248 个」「121 张」）/ 千分位用 U+2009（`3 842`）/ 体积两位小数（<1 GB 一位）/ 计数单位：照片「张」、文件「个」、任务「次」/ 日期 `YYYY-MM-DD`、时间 `HH:MM`、时长「4 分 38 秒」/ 进度写 `121 / 194` / 统一「你」不用「您」/ 用单省略号 `…`。

---

## 8. 中文排版硬规则（可直接当 review checklist）

### 8.1 flex 三规则
```css
.ra-field__label, .ra-btn, .ra-tab, .ra-badge { flex:0 0 auto; white-space:nowrap; }
.ra-field__input, .ra-field__hint, .ra-cell       { flex:1 1 auto; min-width:0; }
.ra-prose                                         { flex:1 1 auto; min-width:12em; overflow-wrap:break-word; }
```
**一个 flex 容器里最多一个「可换行」子项。** 今天 `.row>*{flex:1}` 把输入框和按钮都变成可伸缩（中文按钮会被压到 1 字宽后逐字换行）——必须删掉。

### 8.2 必须 nowrap
按钮 / tab / 徽标 / 表头 / 字段 label / 日期 / 时间 / 数字+单位 / 进度数字 / 状态短语（已归档·跳过）/ `121 / 194` / `4 分 38 秒` / `[EXIF]` / `12.4 GB`。

### 8.3 允许断行白名单

| 类型 | 允许断 | 禁止断 |
|---|---|---|
| 路径 | `/`、`\`、`_` 之后 | `-` 处、`.` 处、扩展名中间 |
| 日期 | **永不断** | 全部 |
| 文件名 | 扩展名前 | 数字序列中间 |
| 中文长句 | 任意字间 | 数字与单位之间 |

实现：Web 在 `/` 后插 `<wbr>`；SwiftUI/WPF 注入零宽空格 `\u{200B}`。**不要**对普通单元格用 `word-break: break-all`（会把中文和数字切碎），只对路径/文件名单元格用 + `<wbr>` 兜底。

### 8.4 表格列宽（900px 下总 828 可用，`table-layout: fixed` 必须）

| 列 | 宽 |
|---|---|
| 源文件 | 34%（mono，可在 `/` 后断） |
| 拍摄日期 | 96px（nowrap + tabular-nums） |
| 日期来源 | 92px（徽标） |
| 归档到 | 38%（mono，可断） |
| 判定 | 72px |

溢出用 ellipsis + `title` 给全文；**禁止**单元格内水平滚动条。

### 8.5 暗色对比度实测（13 组全过）

正文/卡片 14.62 · 正文/画布 15.97 · 次要 8.68 · 三级 5.41 · 三级/画布 5.90 · 日志 11.53 · 主按钮字 7.38 · 危险字 5.85 · 警告字 8.78 · 成功字 7.87 · 置信 A 9.90 / B 8.78 / C 8.44（门槛：正文 ≥7，其余 ≥4.5）
亮色：正文 16.70 · 次要 7.74 · 三级 5.21（在 bg 上 4.81，**刚过线 → 三级文字只用于非关键信息**）· 白字压主按钮 5.24 · 危险 6.54 · 警告 5.44 · 成功 5.79 · 信息 5.62。

### 8.6 其他
中文正文行高 1.65 / 标题 1.35；**禁止 `text-align: justify`**；`letter-spacing: 0`；可点元素最小 44×44 命中区（视觉可 36，用 padding 补）；200% 缩放不崩（表格允许横向滚动，这是唯一允许处）；`:focus-visible` 2px brand 外环，**任何情况不 `outline:none`**（今天 `.form-input:focus{outline:none}` 违反）。

---

## 9. 三端落地差异与能力退化

| 组件 | SwiftUI | WPF | HTML | 退化/注意 |
|---|---|---|---|---|
| 卡片 | `VStack` + `.raCard()` | `Border Style=RaCard` | `.ra-card` | — |
| 字段行 | `HStack` + `Text(minWidth:)` + `TextField` | `DockPanel` + `Button Dock=Right` + `TextBox` | `.ra-field` + `min-width:0` | WPF label 必须设 `MinWidth`，否则中文逐字换行 |
| 主/幽灵/危险按钮 | 3 个 `ButtonStyle` | 3 个自绘 `ControlTemplate` | `.ra-btn--*` | WPF 必须换 Template，否则系统高光与设计不符 |
| 徽标 | `Text` + `Capsule` | `Border CornerRadius=11` | `.ra-badge` | — |
| 分段控件 | `Picker(.segmented)` | 自绘 `ListBox` 横向 | `role="tablist"` | WPF 无原生 segmented，自绘 20 行 |
| 单选组 | `Picker(.radioGroup)` | `RadioButton GroupName` | `input[type=radio]` | — |
| 勾选门 | `Toggle(.checkbox)` | `CheckBox` | `input[type=checkbox]` | **不许用弹窗代替勾选** |
| 进度条 | 自绘 `Capsule` 层叠 | 自绘 `Border`+`Rectangle`（**别用系统 ProgressBar**） | 自绘两层 div | 自绘为一致性与暗色 |
| 表格 | **`LazyVGrid` 自绘行**（macOS 13 的 `Table` 不能自定义行高与徽标列） | **自绘 `ItemsControl`**（P0 不用 DataGrid） | `.ra-table` | 换来徽标列与断行控制 |
| 抽屉 | `.overlay` + `transition(.move(edge:.trailing))`（`.sheet` 在 macOS 是居中卡片，形态不符） | 自绘 + `TranslateTransform` | fixed + `transform` | — |
| 对话框 | 自绘 overlay（`.confirmationDialog` 放不下三段） | `Window.ShowDialog` 自绘 | 自绘 modal | 三端都自绘，保证三段式排版 |
| 暗色来源 | `Color.ra()` 动态色自动跟随，无需代码 | 注册表 `AppsUseLightTheme` + `SystemEvents` | `prefers-color-scheme` + `data-theme` + localStorage | WPF 暗色下 DataGrid/ScrollBar/ComboBox 需手写模板（P1-8） |
| 图标 | SF Symbols | Segoe Fluent（Win10 1809 前退化 MDL2） | 内联 SVG（**今天 `📁`/`⬆` 的 emoji 必须换掉**） | — |
| 本地记忆 | `UserDefaults` | `%APPDATA%\RawArchiver\settings.json` | `localStorage` | 内容一致：`{source, output, opts, lastTask}` |

**能力退化表（必须承认，不许假装实现）**

| 能力 | Web | macOS | Windows | 说明 |
|---|---|---|---|---|
| 设备枚举 `devices` | ✅ | ❌ | ❌ | 桌面 P0 用系统目录框让用户自己选；P1-4 扩 IPC |
| 任务历史列表 | ⚠️ 仅本机记忆 | ⚠️ 仅本次会话 | ⚠️ 仅本次会话 | 需 `tasks`（P1-5） |
| 台账 `ledger` | ✅ | ❌ | ❌ | 桌面 P0 任务页顶部无台账块 |
| 自检 `doctor` | ⚠️ 有动作 UI 没露 | ⚠️ 塞在「关于」 | ⚠️ 塞在「关于」 | P0 三端都搬「维护」页 |
| 清源/回滚 | ✅ | ✅ IPC 有、UI 没露 | ✅ IPC 有、UI 没露 | **桌面「有能力没入口」，P0 就补（成本极低）** |
| 扫描进度 | ❌ 同步 | ❌ 同步 | ❌ 同步 | P0 只能不确定进度 + 已用时（P1-3 补事件） |
| 执行中进度 | ✅ `status` 轮询 | ✅ `evt:progress` 增量 | ✅ 同 | 三端可用 |

---

## 10. 分批实施

### P0 · 必做（解决「主次不分 / 等待无感 / 危险动作」）

| # | 端 | 文件 | 要点 | 量 | 验收 |
|---|---|---|---|---|---|
| P0-1 | Web | `app/www/assets/ra.css`（新建） | §2.8 全量令牌 + 原子 + 暗色双轨 | +260 | 抽查 20 处颜色全走变量；`grep '#4a9\|#c00\|#080'` 为空 |
| P0-2 | Web | `app/www/index.html` | ① intro 删掉搬维护页 ② 5 按钮 → sticky 底栏「重新扫描 / 扫描这张卡」+ 执行态「停止归档」 ③ 结论区改摘要条 + 五格 + 置信分布 + 表格 ④ 门①（保留 `dataset.ready`）+ 门②（勾选） ⑤ 空状态 + `devices` 识别条 ⑥ CSS 外链到 `ra.css` | +430/−180 | 验收 1–8 |
| P0-3 | macOS | `Sources/RawArchiver/Theme.swift`（新建） | §2.9 全量 | +230 | 编译过；切系统外观全跟随 |
| P0-4 | macOS | `ContentView.swift` → `WorkbenchView/TasksView/MaintenanceView/Components.swift` | ① `NavigationSplitView` 侧栏 3 项 ② 选项改纵向 3 组 ③ 预览摘要 + 统计 + 徽标 + 自绘行 ④ **补「清空源文件 / 撤回归档」入口**（IPC 已支持） ⑤ 错误从 ⚠ 按钮改字段辅助行 + 提示条 ⑥ doctor 搬维护页 | +520/−211 | 验收 1–11 |
| P0-5 | macOS | `AppModel.swift` | ① `lastTask` 记忆、`elapsed` 1s 计时、阶段派生（读 `[暂存]` 前缀） ② `cleanup()`/`rollback()` ③ `previewResult` 补 counts/dup/volume/dupGuard ④ `errorKind` 分类 | +180/改40 | 续跑态与暂存阶段能正确识别 |
| P0-6 | macOS | `Models.swift` | `PreviewResult` 增字段；新增 `DateConfidence` 枚举 + 容错映射 | +90 | 用真实 preview JSON 跑解析，四态正确 |
| P0-7 | Win | `Themes/Light.xaml`、`Dark.xaml`、`App.xaml(.cs)` | §2.10 + `RaTheme.FollowSystem()` | +420 | 亮暗切换无白底破窗（TextBox 至少跟色） |
| P0-8 | Win | `MainWindow.xaml(.cs)` | ① 固定尺寸 → 1120×760 可缩放 ② 7 行 Grid → 左 180 导航 + 右内容 ③ 底部 sticky 主行动 ④ DataGrid → 自绘表格（含徽标列） ⑤ 自绘进度条 ⑥ 日志换自绘等宽列表 + 复制/暂停 | +450/+260 | 验收 1–9 |

> **P0 明确不做**：任务列表真实枚举、台账月度维度、`preview` 进度事件——都要动后端，放 P1，避免 P0 变「前端等后端」。

### P1 · 值得做（把藏着的能力全部露出来）
- **P1-1** Web 任务页：本机记忆列表 + 详情抽屉 + 续跑 + `ledger stats` 台账块 + 危险区（+240）
- **P1-2** Web 维护页：`doctor` 结果表（逐项绿/黄点 + 「影响什么」一句话）+ 品牌格式说明（原 intro）+ 版本目录（+150）
- **P1-3** 后端 `preview` 进度事件：`scan_images` 是生成器，加 `log_cb` 计数；Web 改 SSE 或 `previewProgress` 轮询，IPC 加 `evt:"preview_progress"`（+120）
- **P1-4** IPC 补 `devices` / `ledger` / `status`（+90）
- **P1-5** IPC 补 `tasks`：枚举 `tasks/*/state.json` 返回 `[{taskId, source, output, status, total, success, failed, skipped, created_at, finished_at}]`，倒序 50 条（+70）
- **P1-6** `ledger_stats` 加 `op=monthly`（`archived_at` 列已存在，<20 行 SQL）（+25）
- **P1-7** 桌面任务页接 P1-4/5（+220 各）
- **P1-8** WPF `ScrollBar/ComboBox` 模板（+180）

### P2 · 以后
失败重试（需 core 支持白名单）/ 缩略图（RAW 首帧只在极便宜时做，且只做 JPG+视频）/ 台账月度柱图 / 归档规则预设 / 多语言（不做）。

### 10.4 可复用验收清单（发版前逐条打勾，不接受「我觉得没问题」）

**A 主次与危险**
1. 任一屏 brand 实心按钮数 = 1（空状态/就绪/预览/执行/结果各查一次）〔v1.0.22 首屏 5 个 → 失败〕
2. 「撤回归档」不出现在工作台
3. move 模式下撤回**不渲染**（非灰显）；Web 不再弹「移动模式无法回滚」alert
4. 清源/回滚都有三段式对话框且主按钮含数量〔今天 `confirm('确认把…移回…？')` 一句话 → 失败〕
5. 灰度截图下危险按钮仍可区分

**B 等待可解释**
6. 扫描段同时可见：动作名 / 已用时（每秒）/ 只读安全背书
7. 扫描段**无假百分比**
8. 执行段同时可见：阶段条（2 或 3 段）/ `current/total` / 成功失败跳过 / 当前文件 / ETA / 停止
9. `total==0` 进不确定态，不显示 0%
10. 停止点后立即「正在停止…」并禁用；连点 5 次只产生一个 `cancel` 文件

**C 能力暴露**
11. `doctor` 在三端界面可见（不藏「关于」）〔macOS/WPF 今天藏在 about → 失败〕
12. 台账 `ledger stats` 在 Web 任务页可见
13. 桌面两端都有「清空源文件/撤回归档」入口
14. 续跑一键发起；`state.json` 经历 `resuming → running`
15. 报告路径在结果卡可点（`_report_<taskId>.json`）
16. 无设备时空状态给 `devices` 真实结果或权限提示

**D 排版与可访问**
17. 900px 无横向滚动（表格除外）；900/760/640 三档缩窗无中文竖排
18. 日期、`121 / 194`、`12.4 GB` 任何宽度都不换行
19. Tab 可达全部元素；焦点环可见；危险框焦点在副按钮
20. 暗色 13 组对比度实测达标
21. 无 emoji 功能图标
22. 无 CDN/网络字体；断网刷新正常；源码无外链
23. reduced-motion 下无动效

**E 语义准确（最容易糊过去）**
24. 构造 4 个 `date_from`（`exififd`/`quicktime`/`file_mtime`/`unknown`）分别显示 EXIF/ExifTool/文件时间/跳过
25. 未知 `date_from` 不静默归档某档（显示原名 + 中性底）
26. 「跳过」的照片执行后确实没拷贝（核对 `state.json` 的 `done` 里 `status:"skip", reason:"no_date"`）

---

## 11. 风险与取舍

### 11.1 主动砍掉
1. **拖拽归档**：宿主 iframe 会吞 `dragstart/dragover`；语义冲突（本产品承诺「按 EXIF 自动落位」，拖拽是手工指定落位）；误拖直接对 NAS 动手且无预览可拦。替代：结果卡给「打开目标目录」。
2. **全屏文件夹树**：`DCIM/100CANON/…` 这种「目录少、每目录上千文件」的结构下收益为零；还要为 900px 宽度牺牲表格路径列。替代：面包屑 + 一级列表 + 等宽路径串。
3. **照片缩略图网格**：RAW/长视频取首帧要读整段文件，会把「扫描 3 分钟」变成「30 分钟」，直接违反原则二；用户要判断的是日期与落点，不是画面。替代：置信分布 + 四态徽标 + 文本清单。
（另砍：插入即自动归档（无确认门）、自定义主题色（破坏「三端一张脸」）、步骤向导（用户会跳着改））

### 11.2 五个真实风险
| 风险 | 影响 | 应对 |
|---|---|---|
| R1 扫描无进度（F2） | 原则二在最长等待段只能部分成立 | P0 诚实表达；P1-3 补事件 |
| R2 桌面 IPC 缺 status/tasks/ledger/devices（F6） | 桌面任务中心 P0 是空壳 | P0 只显示本次会话任务并明写「完整列表待 P1」；不假装有台账 |
| R3 台账无月度（F5） | 「上月多少张」答不出 | 明写缺什么；P1-6 补 20 行 SQL；不给假图 |
| R4 CJK 塌字回潮 | 每次改样式都可能重犯 | §8.1 写进 `ra.css` 顶部注释；「600/760/900 三档无竖排」列为发布前必检 |
| R5 WPF 暗色破窗 | 半成品感反而拉低质感 | P0 保证 TextBox/Border/Button/自绘进度条；表格改自绘；其余模板 P1-8 |

### 11.3 下一步
先 **P0-1（ra.css 令牌）** 再 **P0-2（index.html 重排）**：Web 是最受限也最常用的一端，把「一屏一个主行动 + 阶段进度 + 双重确认门」跑通后，macOS/WPF 只是把同结构换成 `NavigationSplitView` 与 `ListBox`，返工最小。

---

**文档版本** v1.1（技术核对版）｜**基线** fnOS v1.0.22 / macOS v1.1.1 / Windows v1.1.1
**核对过的源码**：`fnos/rawarchiver/app/www/index.html`、`app/server.py`（`handle_action`/`optargs`）、`app/scripts/raw_archiver.py`（`ledger_stats`/`date_from`）、`desktop/core-ipc/ipc_main.py`（命令分发与 `evt:progress`）、`desktop/macos/Sources/RawArchiver/{ContentView,AppModel,Models,IpcClient}.swift`、`desktop/windows/RawArchiver/MainWindow.xaml(.cs)`。
