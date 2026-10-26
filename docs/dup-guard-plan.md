# RAW 归档 · 重复归档防护方案（Dup Guard）

> 目标读者：13叔 / 后续实现者
> 状态：**已实现（v1.0.19）**；三条口径已按 13叔 2026-10-26 的确认落地
> 适用版本：fnOS 1.0.18 / 原生 GUI 核心引擎 1.1.1（共用 `app/scripts/raw_archiver.py`）

---

## 1. 问题与现状根因（代码级）

**现象**：卡上的照片不能删（或忘记删），下次插卡再归档 → 同一批照片被再处理一遍，输出目录里出现
`IMG_0001_20260101.nef`、`IMG_0001_20260101_1.nef`、`IMG_0001_20260101_2.nef`… 每插一次卡多一份。

**根因（`raw_archiver.py`）**：

| # | 位置 | 现状 | 后果 |
|---|------|------|------|
| 1 | `run_task()` `done_key = {(rel, size)}` | 只比对**当前任务**的 state.json | 只解决断点续跑，跨任务完全无记忆 |
| 2 | `build_target()` | 目标已存在 → 自动追加 `_1/_2` | 冲突被**静默吞掉**，重复文件正常落盘，看起来"成功" |
| 3 | `do_preview(source, opts)` | 签名里**没有 output**，`build_target(..., source)` 拿源目录当输出目录算目标名 | 预览里的 `conflicts` 恒为 0 → UI 从来不提示"目标已存在"（既有 bug） |
| 4 | 无任何持久化的"已归档"记录 | — | 换任务、换进程、换天，一律从零开始 |

一句话：**系统从来没定义过"处理过"这件事，只定义了"这个文件名字没被占用"**。

---

## 2. 设计目标与硬约束

必须守住的不变量（顺序即优先级）：

1. **宁可重复，不可丢失**：任何"跳过"必须有可复核的证据，判不准就按新文件处理。
2. **源目录零写入**：不往 SD/TF/U 盘写任何标记文件（延续 v1.0.14 约定）。
3. **跳过可审计**：每一次 SKIP 都要能回答"哪天、哪个任务、归档到哪、凭什么判的"。
4. **跨平台一份实现**：逻辑放 core（`raw_archiver.py`），fnOS / macOS / Windows 三个前端共享。
5. **台账丢失不致命**：去掉台账也能靠"目标文件存在性 + 内容复核"兜住。
6. **明确确认才重处理**：默认跳过；要重处理必须在 UI 勾选 + 二次确认，CLI 必须显式旗标。

---

## 3. 如何认定"已经处理过"——三级证据

单靠文件名不可靠（两张卡都可能有 `IMG_0001.CR2`），单靠哈希太贵（每次插卡重算 30 GB）。
采用**分级的、成本递增的**证据链：

| 级别 | 判据 | 额外 I/O | 置信度 | 使用场景 |
|------|------|----------|--------|----------|
| **L1 元数据** | `basename + size + mtime` 三元组命中台账，且台账里记录的 `dst` 文件仍存在 | 0（只有 `stat`） | 高 | 常规复插卡（FAT/exFAT 保留原 mtime，几乎必中） |
| **L2 内容** | `size + 首 256KB + 末 256KB` 的 SHA1 命中台账 | 读 512KB | 极高 | mtime 变了（经 PC 中转/换卡）、跨设备 |
| **L3 现场** | 按当前选项算出的**目标路径已存在且 size 相同**，再比对两侧内容指纹一致 | 读 1MB（源+目标） | 极高 | 台账为空（首次升级）、台账丢失、手工拷过归档文件 |

判定顺序（每个源文件走一次）：

```
L1 命中 且 dst 存在        → DUP（跳过）           证据: l1
L1 命中 但 dst 不存在      → MISSING（默认重归档）  证据: l1+missing
L2 / name+size 候选命中    → 内容指纹比对一致 → DUP  证据: l2
                           不一致           → NEW
L3 目标存在 & size 相同    → 两侧内容一致 → DUP(补录台账)
                           不一致          → CONFLICT（走 _1 后缀，属真冲突）
目标存在 & size 不同       → CONFLICT
其余                       → NEW
```

**关键安全规则（写死）**：`size` 相同**不等于**同一张照片（连拍 JPG、同机型可能字节数巧合相同）。
凡"靠 size 判等"的路径（L3、以及 L2 的 name+size 候选）**必须做内容复核**，否则会静默丢照片。
反过来，L1 命中（mtime+size+name 同时一致）可以不做内容复核——能同时满足这三项的"不同文件"现实中不存在，
且即便存在，也意味着该内容此前确实已归档过一份。

**内容指纹定义**（够快、够稳、无依赖）：

```python
def fp_content(path, chunk=256 * 1024):
    size = os.path.getsize(path)
    h = hashlib.sha1(str(size).encode())
    with open(path, 'rb') as f:
        h.update(f.read(chunk))                       # 头部（含 EXIF/文件头，命中率最高）
        if size > chunk * 2:
            f.seek(-chunk, os.SEEK_END)
            h.update(f.read(chunk))                   # 尾部
    return 'sz:%d|%s' % (size, h.hexdigest()[:24])
```

> 为什么不用全文件哈希：一张 25 MB 的 NEF，1000 张 = 25 GB，插卡预览阶段不可接受。
> 头 256KB 已包含 EXIF + 图像起始数据，配合 size + 尾块，实际碰撞概率可忽略。
> 需要极致严谨时给 `--dup-hash full` 走全文件。

---

## 4. 台账（Ledger）

### 4.1 位置与形态

`$TRIM_PKGVAR/.rawarchiver/ledger.sqlite3`（= `state_root()/ledger.sqlite3`，与 `tasks/` 同级）。
跟随现有约定：**不写用户输出目录、不写源目录**。macOS/Windows 由 GUI 注入 `TRIM_PKGVAR`，天然共享同一份逻辑。

用 SQLite 而非 JSON 的理由：几万条仍有索引级查询、写入原子、支持并发读；`sqlite3` 是标准库，三个平台都在。

### 4.2 Schema

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS archived (
  fp          TEXT PRIMARY KEY,      -- 内容指纹（可能为 NULL，等首次复核时回填）
  k1          TEXT,                  -- sha1(basename|size|mtime)，可能为 NULL（历史回填无 mtime）
  name        TEXT NOT NULL,         -- basename 含扩展名
  size        INTEGER NOT NULL,
  mtime       INTEGER,
  shot_date   TEXT,                  -- YYYY-MM-DD
  dst_rel     TEXT,                  -- 相对 output
  output      TEXT,                  -- 归档时的输出目录（绝对路径）
  task_id     TEXT,
  brand       INTEGER DEFAULT 0,
  archived_at TEXT,
  state       TEXT DEFAULT 'ok'      -- ok | rolled_back
);
CREATE INDEX IF NOT EXISTS ix_k1        ON archived(k1);
CREATE INDEX IF NOT EXISTS ix_name_size ON archived(name, size);
CREATE INDEX IF NOT EXISTS ix_output    ON archived(output);

CREATE TABLE IF NOT EXISTS volumes (      -- 仅用于"这张卡上次处理过"的提示
  volkey     TEXT PRIMARY KEY,
  last_task  TEXT, last_at TEXT, last_count INTEGER, last_output TEXT
);
```

### 4.3 写入时机

- **归档成功**（`shutil.copy2` 返回且目标存在）后写一条，`INSERT OR REPLACE`。
- **批量提交**：每 50 条 commit 一次，末尾 commit；异常中断最多丢 50 条（这 50 条下次会判成 NEW 重复一次，可接受）。
- **回滚联动（必须做）**：`do_rollback()` 把归档文件移到 `_restored/` 时，把对应 `fp` 的 `state` 置 `rolled_back`
  （或直接删除记录）。否则下次插卡会误判"已归档"而跳过，用户实际手里没文件了。
- **手动删除归档文件**：不做实时监听，靠 L1 判定时校验 `os.path.exists(output/dst_rel)` → 判 MISSING → 重归档。

### 4.4 历史回填（首次升级必备）

升级后台账是空的，若只靠存量判定，用户第一次仍会重复一遍（虽然靠 L3 能拦，但要读盘复核）。
用**历史报告回填**零成本解决：

```python
def rebuild_from_reports(output):
    """扫描 <output>/log/_report_*.json，把 items 灌进台账（fp/k1 留 NULL）。"""
```

报告里已有 `src / size / dst / date / task_id`，足够支撑"name+size 候选 → 内容复核"的判定路径。
之后再补两步自愈：
- 某条记录首次被 L2/L3 命中 → **回填它的 `fp` 和 `k1`**（源 mtime + 现场算的内容指纹），下次就是零成本 L1。
- 用户也可手动 `--rebuild-ledger <output>` 对任意历史目录重建。

### 4.5 查找接口

```python
def judge(fp_src, output, opts, led) -> (verdict, evidence)
# verdict: 'new' | 'dup' | 'missing' | 'conflict' | 'dup_other_output'
# evidence: {'level':'l1'|'l2'|'l3', 'archived_at':..., 'prev_dst':..., 'task':..., 'need_hash':bool}
```

---

## 5. 预览：从"只看文件"变成"看差异"

### 5.1 先修既有 bug

`do_preview` 必须接收真实 `output`（现在拿 `source` 顶替，导致 `conflicts` 恒 0）：

```python
def do_preview(source, opts, limit=500, output=None):
    ...
    dst, _md, kind = build_target(rel, dt, opts, reserved, output or source)
```

CLI / server / IPC 三处把 `--output` 透传进来。

### 5.2 返回结构扩展（向后兼容，只加字段）

```json
{
  "total": 908, "size": 27160000000,
  "counts": {"new": 93, "dup": 812, "dup_unverified": 45,
             "conflict": 2, "nodate": 1, "missing": 0},
  "dup": {
    "count": 812, "bytes": 24800000000,
    "by_level": {"l1": 800, "l2": 10, "l3": 2},
    "same_output": 800, "other_output": 12,
    "last_at": "2026-10-20 09:12:33",
    "sample": [{"src": "DCIM/100CANON/IMG_0001.CR2",
                "prev_dst": "20261020/IMG_0001_20261020.cr2",
                "archived_at": "2026-10-20 09:12", "task": "20261020_091245_1234",
                "level": "l1"}]
  },
  "volume": {"seen_before": true, "last_at": "2026-10-20 09:12", "last_count": 812},
  "dup_guard": "8f3c1d92a4b7e650"
}
```

**性能取舍（重要）**：预览阶段只做 **L1 + 目标存在性（stat 级）**；
需要读盘的内容复核（`dup_unverified`）**推迟到 run 阶段逐文件流式做**，日志里给逐条证据。
理由：1000 张卡插着读 800 MB 只为了"数个数"，体感是几十秒卡死；而 run 阶段反正要读全部字节。

> `dup_unverified > 0` 时，UI 明确写"另有 45 个需内容校验（可能已归档）"，不假装精确。

---

## 6. 确认门（用户要的"再次确认后才能处理"）

### 6.1 UI 层（fnOS / macOS / Windows 三个前端一致）

预览摘要行改为：

```
共 908 个 / 25.3 GB ｜ 新文件 93 ｜ ⚠ 已归档 812（跳过）｜ 待校验 45 ｜ 同名冲突 2 ｜ 无日期 1
```

警示区（黄色）：

```
⚠ 检测到 812 个文件此前已归档（最近 2026-10-20 09:12，约 23.1 GB），默认跳过以避免重复落盘。
   另有 45 个文件无法确定是否归档过，将在处理时逐个做内容校验；确认已归档的会跳过。
   若确实需要再处理一遍（例如上次归档到别处、需要重新组织目录），请勾选：
   ☐ 重新处理已归档文件（会在目标目录产生 _1/_2 副本）
```

点「开始归档」时：

- **未勾选**：`confirm("将跳过 812 个已归档文件（约 23.1 GB）。继续？")`
- **已勾选**：`confirm("⚠ 将重新归档 812 个已归档文件，目标目录会保留现有文件并产生 _1/_2 副本。确认执行？")`
  （二次确认只做一次，不做输入框，避免过度摩擦）

预览面板新增折叠表「已归档文件清单」，列：源路径 / 原归档位置 / 归档时间 / 判定依据（元数据/内容/现场）。
让用户能"眼见为实"地判断是不是误判——这是不肯盲目信任程序的用户唯一愿意接受的形式。

### 6.2 服务端强制（防前端绕过 / 防 API 直调）

`start` 请求新增 `dupPolicy`（`skip` | `force`，默认 `skip`）：

- `force` 必须携带 `dupGuard`，且服务端能校验通过，否则返回
  `{"ok": false, "code": "need_confirm", "error": "检测到 812 个已归档文件，请先在预览中确认"}`。

Guard 设计（无需重扫，成本 0）：

1. 预览时生成 `guard = sha1(secret + source + output + opts_hash + sorted(dup_fps))[:16]`；
2. 落盘 `state_root()/guards/<guard>.json` = `{source, output, opts_hash, dup_count, ts}`，TTL 30 分钟；
3. `start(force)` 校验该文件存在、未过期、`source/output/dup_count` 与请求一致；
4. `secret` 存 `state_root()/secret`（0600，首次 `secrets.token_hex(32)`）。

CLI 同样设门：`--dup-policy force` 还要求 `--confirm-dups N`（N 必须等于实测 dup 数），
不符则退出码 2 + 打印"检测到 N 个已归档文件，加 --confirm-dups N 以确认重处理"。

### 6.3 运行期行为

- 每个 DUP 记 `SKIP` 日志（含证据），计入 `st['skipped_dup']`；`nodate` 计入 `st['skipped_nodate']`。
  `st['skipped']` 保留为两者之和（不破坏现有 UI 文案）。
- 报告 `_report_*.json` 增加 `skipped_dup` / `skipped_nodate` / `dups` 明细，`items` 仍只放成功项（向后兼容）。
- 完成后摘要："成功 93 / 跳过 812（已归档） / 跳过 1（无日期） / 失败 2"。

---

## 7. `build_target` 的冲突消解要改

```
clean_dst 已存在 & size 相同 & 内容一致  → 判 DUP（不再 _1）
clean_dst 已存在 & (size 不同 | 内容不同) → CONFLICT，追加 _1
```

现状是"存在即 `_1`"，把"已归档"和"真冲突"混为一体。改造后 `conflicts` 计数只统计真冲突，
`_1` 后缀也只在真冲突时出现——用户一看到 `_1` 就知道是同名不同片，而不是自己又归档了一遍。

---

## 8. 边界与风险（逐条给结论）

| 场景 | 期望行为 | 依据 |
|------|----------|------|
| 同一张卡反复插 | 全部 DUP 跳过，第二次起近零成本 | L1（stat） |
| 卡经 PC 拷到另一张卡（mtime 变） | DUP 跳过 | name+size 候选 → 内容复核 |
| 相机重置文件名，同名同 size 不同片 | 不跳过，按 CONFLICT 落 `_1` | 内容复核 |
| 上次归档到 A 目录，这次输出 B 目录 | 默认跳过，标 `dup_other_output` + 显示 A 路径；可勾选强制 | 台账全局 |
| 用户手动删了归档文件 | MISSING → 重归档 | L1 + `os.path.exists` |
| 任务回滚过 | 记录失效 → 重归档 | `do_rollback` 置 `rolled_back` |
| 无拍摄日期的文件 | 每次仍跳过（不写台账，因为它从未被"处理"） | 现状不变 |
| 台账被删 / 换电脑 / 换 NAS | 靠 L3 现场判定 + 报告回填恢复 | 目标存在性 |
| 两个任务同时跑 | WAL + busy_timeout，最坏是某条 INSERT 重试 | SQLite |
| 中断后 `--task-id` 续跑 | `done_key` 逻辑保留，且 DUP 不重复记台账 | 幂等 `INSERT OR REPLACE` |

**唯一不可消除的残差**：两张不同的卡上有**同名、同 size、同 mtime** 的不同文件（几乎不可能，除非克隆卡）。
此时会被判 DUP 跳过——但"克隆卡里的那张照片"本来就已经归档过了，语义上仍成立。

---

## 9. 实施计划（分三档，可按预算取舍）

### M1 · 最小可用（≈0.5 天）：不加持久化，先把"重复"变成"可见可确认"

- 修 `do_preview` 的 `output` 参数（顺带修好 `conflicts` 恒 0 的老 bug）。
- `build_target` 改冲突语义：目标存在且 size 相同 + 内容一致 → DUP；否则 `_1`。
- 预览返回 `counts` / `dup` / `volume`（volume 无台账时不做）。
- UI：摘要行 + 黄色警示 + 折叠清单 + 「重新处理已归档」勾选 + 两次 confirm。
- `--dup-policy skip|force` + `--confirm-dups N`（M1 里 N 由本次扫描现算）。
- **能解决**：同一输出目录、文件名不变（≈ 用户当前 90% 的场景）。
- **不能解决**：换输出目录 / 换 brand 选项 / 用户删过归档文件。

### M2 · 台账（≈1~1.5 天）：跨任务、跨目录、跨设备

- `ledger.sqlite3` + `judge()` + `record()` + `rebuild_from_reports()`（首次启动自动回填当前 output）。
- run 阶段逐文件判定 + 证据日志 + 报告字段扩展。
- `do_rollback` 联动置 `rolled_back`；MISSING 检测。
- 预览 `dup_unverified` 计数（推迟复核）。
- 设置区：台账统计（N 条 / 最后写入时间 / 覆盖 N 个 output）、「重建台账」「清理 90 天前记录」。

### M3 · 加固（≈0.5 天）

- Guard token + 服务端 `need_confirm` 硬门（防 API 直调绕过）。
- 卷指纹提示（"这张卡 2026-10-20 处理过 812 个"）。
- 「只重处理勾选项」（从清单里挑选个别文件强制重归档）。
- 三端 UI 文案统一（fnOS `index.html`、SwiftUI、WPF）。

### 改动文件清单

| 文件 | 改动 |
|------|------|
| `app/scripts/raw_archiver.py` | 新增 `fp_content`/`judge`/`ledger`/`secret`/`guard`；`do_preview` 加 output；`build_target` 冲突语义；`run_task` dup 分支；`do_rollback` 联动；CLI 新旗标 |
| `app/server.py` | `optargs`/`handle_action`：preview 传 output；start 校验 `dupPolicy`+`dupGuard`；新增 `ledger` 动作（stats/rebuild/prune） |
| `app/www/index.html` | 预览摘要/警示/清单/勾选/confirm；API 传 `dupPolicy`、`dupGuard` |
| `app/api/index.cgi` | 同步 server 的动作（保持两条通道一致） |
| `desktop/core-ipc/ipc_main.py` + `PROTOCOL.md` | preview 返回字段、start 增加 `dupPolicy/dupGuard`（协议向后兼容：新字段可选） |
| `desktop/macos/...`、`desktop/windows/...` | 预览差异展示 + 勾选 + 确认对话框 |
| `manifest` / `README.md` / `docs/` | 版本号与功能说明 |

### 自检清单（沿用项目 `SELFTEST_*` 风格）

```
SELFTEST_DUPGUARD_OK
  1  全新源 + 空台账              → 全部 new
  2  归档一次后原样再跑            → 全部 dup，success=0，skipped_dup=N
  3  改 mtime 后再跑               → 仍判 dup（name+size+内容）
  4  同名同 size 不同内容          → conflict，落 _1，不误判 dup
  5  同名同 size 同内容不同 mtime  → dup
  6  归档文件被手动删掉            → missing → 重归档
  7  rollback 之后再跑             → 重归档（记录已失效）
  8  换输出目录再跑                → dup_other_output，默认跳过
  9  force + 有效 guard            → 全部重处理，落 _1
 10  force + 无 guard / guard 过期 → need_confirm，任务不启动
 11  报告回填后首次判定            → 回填记录能被 L2/L3 命中并自愈出 fp+k1
 12  预览 conflicts 计数          → 只在真冲突时非 0（老 bug 回归）
 13  源目录前后 tree 一致         → 源零写入（回归）
 14  中断续跑                     → 台账无重复行（INSERT OR REPLACE 幂等）
```

---

## 10. 待 13叔拍板的三个点

1. **默认动作**：检出已归档 → **直接跳过（推荐）** 还是先弹框问？我建议跳过 + 执行前一次 confirm，避免每次插卡都要点一次弹窗。
2. **跨输出目录**：上次归档到 A、这次选 B → 默认跳过（推荐，防重复占空间）还是当新文件（因为用户可能确实要一份到 B）？
3. **内容复核强度**：默认头尾各 256KB（推荐，千张级秒级）；要不要提供 `全文件哈希` 选项给"强迫症模式"？

---

## 11. 一句话总结

> 把"处理过"变成**一份持久台账 + 三级证据**，默认跳过已归档、跳过即写日志留证；
> 要重处理必须在 UI 勾选并在服务端出示 guard，CLI 必须显式 `--confirm-dups N`；
> 台账丢了也不怕——目标文件存在性 + 内容复核是最后一道网，且历史报告能一键回填。
