# RAW 归档 · 原生 GUI ↔ 核心引擎 IPC 协议（NDJSON）

> 本文是 macOS（SwiftUI）与 Windows（WPF）GUI 与 Python 核心 CLI 之间的**唯一通信契约**。
> GUI 侧严格按本文实现，不得依赖 CLI 的其他输出。

## 1. 传输

- **通道**：子进程标准输入 / 标准输出
- **格式**：NDJSON —— 每行一个 UTF-8 JSON 对象（`json.dumps(..., ensure_ascii=False)` + `\n`），无 BOM
- **启动**：GUI 启动子进程 `RawArchiver-cli --ipc`，并设置环境变量 `TRIM_PKGVAR`（任务态目录）
- **行序**：请求按序写入 stdin；响应与事件从 stdout 按序读出

## 2. 消息类型

三种消息（通过有无 `id` / `evt` 区分）：

| 类型 | 方向 | 判别 | 说明 |
| --- | --- | --- | --- |
| 请求 request | GUI → CLI | 有 `id` 无 `evt` | GUI 发起一个操作 |
| 响应 response | CLI → GUI | 有 `id` 无 `evt` | 每个请求**恰好一个**响应，`id` 相同 |
| 事件 event | CLI → GUI | 有 `evt` 无 `id` | CLI 异步推送（进度 / 完成 / 错误） |

## 3. 命令一览

| cmd | 请求字段 | 响应 `result` | 说明 |
| --- | --- | --- | --- |
| `doctor` | — | 依赖状态对象 | 环境自检 |
| `preview` | `source` `output` `opts` | core `do_preview` 返回值 | 扫描源（同步，GUI 端可等待） |
| `start` | `source` `output` `opts` `taskId?` | `{"taskId": "..."}` | 启动归档；进度通过事件推送 |
| `cancel` | `taskId` | `{}` | 写 cancel 文件 |
| `cleanup` | `taskId` `output` `verifyHash?` | `{"deleted":n,"kept":[],"fail":[]}` | 补清源 |
| `rollback` | `taskId` `output` | `{"restored":n,"to":"..."}` | 回滚（仅复制模式） |
| `shutdown` | — | `{}` | 退出 CLI |

`opts` 结构（所有带 opts 的命令共用）：

```json
{"brandFolder": false, "handleJpg": true, "handleVideo": true,
 "staging": true, "mode": "copy"}
```

`mode` 取 `"copy"` 或 `"move"`。

## 4. 消息示例

### 4.1 doctor

```
→ {"id":1,"cmd":"doctor"}
← {"id":1,"ok":true,"result":{"app":"RAW 归档","version":"1.1.0","python":"3.12.10","exifread":true,"pillow":true,"exiftool":".../vendor/exiftool/exiftool","perl":false}}
```

### 4.2 preview

```
→ {"id":2,"cmd":"preview","source":"/Volumes/SD/DCIM","output":"/Users/u/归档","opts":{"brandFolder":false,"handleJpg":true,"handleVideo":true,"staging":true,"mode":"copy"}}
← {"id":2,"ok":true,"result":{"source":"/Volumes/SD/DCIM","removable":true,"total":128,"size":3670016000,
    "by_type":{".cr3":80,".jpg":40,".mov":8},"date_range":["2024-05-01","2024-07-12"],
    "bad_count":3,"conflicts":2,"raw_skip_hint":1,
    "removable_note":"move 模式归档成功后将清空源设备","exiftool":true,
    "sample":[{"src":"DCIM/100CANON/IMG_0001.CR3","size":30123123,"date":"2024-05-06",
               "date_from":"exiftool","dst_rel":"20240506/IMG_0001_20240506.CR3","bad":false,"skip":false}, ...]}}
```

`sample` 最多 500 条（core `limit`）。

### 4.3 start + 事件流

```
→ {"id":3,"cmd":"start","source":"/Volumes/SD/DCIM","output":"/Users/u/归档",
   "opts":{"brandFolder":false,"handleJpg":true,"handleVideo":true,"staging":true,"mode":"copy"},
   "taskId":"20261023_153000_1234"}
← {"id":3,"ok":true,"taskId":"20261023_153000_1234"}          ← 立即返回，任务在后台
← {"evt":"progress","taskId":"20261023_153000_1234","status":"running","current":10,"total":128,
   "success":8,"failed":0,"skipped":2,
   "logs":[{"t":"2026-10-23 15:30:01","msg":"待处理 128 个文件"},
           {"t":"2026-10-23 15:30:02","status":"ok","src":"DCIM/100CANON/IMG_0001.CR3","dst":"20240506/IMG_0001_20240506.CR3"}, ...]}
← {"evt":"progress", ...}                                       ← 每 500ms 一条，logs 为增量
← {"evt":"done","taskId":"20261023_153000_1234","status":"done","success":125,"failed":0,"skipped":3,"error":""}
```

### 4.4 cancel / cleanup / rollback / shutdown

```
→ {"id":4,"cmd":"cancel","taskId":"20261023_153000_1234"}
← {"id":4,"ok":true}
```

```
→ {"id":5,"cmd":"cleanup","taskId":"20261023_153000_1234","output":"/Users/u/归档","verifyHash":false}
← {"id":5,"ok":true,"result":{"deleted":125,"kept":[],"fail":[]}}
```

```
→ {"id":6,"cmd":"rollback","taskId":"20261023_153000_1234","output":"/Users/u/归档"}
← {"id":6,"ok":true,"result":{"restored":125,"to":"/Users/u/归档/_restored/20261023_153000_1234"}}
```

```
→ {"id":7,"cmd":"shutdown"}
← {"id":7,"ok":true}     （CLI 随后退出）
```

## 5. 错误约定

- 业务错误：`{"id":N,"ok":false,"error":"<中文可读消息>"}`，`error` 直接展示给用户
- 事件错误（任务运行中异常）：`{"evt":"done","taskId":...,"status":"error","error":"..."}`
- 非法 JSON / 未知 cmd：`{"id":null,"ok":false,"error":"bad request"}`（id 无法解析时用 null）

## 6. 进度事件字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | `running`（进行中）；终态见 `done` 事件 |
| `current` / `total` | int | 当前处理到第几个 / 总数 |
| `success` / `failed` / `skipped` | int | 累计计数 |
| `logs` | array | **自上次 progress 起新增**的日志行（增量，GUI 追加即可） |

日志行元素两种形态（来自 core 的 `log_msg` / `log_file`）：

```json
{"t":"2026-10-23 15:30:01","msg":"待处理 128 个文件"}
{"t":"2026-10-23 15:30:02","status":"ok","src":"DCIM/…/IMG_0001.CR3","dst":"20240506/IMG_0001_20240506.CR3"}
{"t":"2026-10-23 15:30:03","status":"skip","src":"DCIM/…/x.jpg","msg":"无拍摄日期，跳过"}
{"t":"2026-10-23 15:30:04","status":"fail","src":"DCIM/…/y.jpg","msg":"<异常信息>"}
```

GUI 侧格式化建议：`[时间] 状态 | 源 -> 目标` 或 `[时间] 消息`。

## 7. done 事件字段

| 字段 | 说明 |
| --- | --- |
| `status` | `done` / `cancelled` / `error` |
| `success` / `failed` / `skipped` | 最终计数 |
| `error` | `status=error` 时的异常信息，其余为空串 |

## 8. 生命周期

```
GUI 启动 → spawn CLI --ipc（设置 TRIM_PKGVAR）
        → 可立即发 doctor / preview
        → start 后订阅 progress/done 事件
        → 结束（关窗/退出）→ 发 shutdown → 等退出 → kill
```

- CLI 在收到 `shutdown` 后自行退出；GUI 侧也要有「超时后强制 kill」的兜底。
- `start` 的归档在**独立 worker 子进程**运行，CLI 退出不必然终止 worker（worker 继承环境，继续写 state.json / 日志 / 报告）。
