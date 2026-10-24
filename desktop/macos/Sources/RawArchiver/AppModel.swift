import Foundation
import SwiftUI

/// 应用状态：持有 IPC 客户端，封装预览/归档/进度逻辑。
final class AppModel: ObservableObject {
    // 输入
    @Published var source: String = ""
    @Published var output: String = ""
    @Published var brandFolder: Bool = false
    @Published var handleJpg: Bool = true
    @Published var handleVideo: Bool = true
    @Published var staging: Bool = true
    @Published var mode: String = "copy"   // copy / move

    // 预览
    @Published var previewResult: PreviewResult?
    @Published var previewing: Bool = false

    // 任务
    @Published var taskId: String = ""
    @Published var isRunning: Bool = false
    @Published var progress = ProgressSnapshot(status: "", current: 0, total: 0, success: 0, failed: 0, skipped: 0)
    @Published var logs: [String] = []
    @Published var statusText: String = ""

    // 环境
    @Published var doctorText: String = ""
    @Published var errorText: String = ""

    private let client = IpcClient()
    private let defaults = UserDefaults.standard

    init() {
        // 恢复上次设置
        source = defaults.string(forKey: "source") ?? ""
        output = defaults.string(forKey: "output") ?? ""
        brandFolder = defaults.bool(forKey: "brandFolder")
        handleJpg = defaults.object(forKey: "handleJpg") as? Bool ?? true
        handleVideo = defaults.object(forKey: "handleVideo") as? Bool ?? true
        staging = defaults.object(forKey: "staging") as? Bool ?? true
        mode = defaults.string(forKey: "mode") ?? "copy"

        client.onEvent = { [weak self] evt in
            DispatchQueue.main.async { self?.handleEvent(evt) }
        }
    }

    var varDir: String {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
        let dir = (base?.path ?? NSHomeDirectory() + "/Library/Application Support") + "/RawArchiver"
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        return dir
    }

    func startup() {
        guard let cli = IpcClient.locateCli() else {
            errorText = "未找到核心引擎（RawArchiver-cli）。请设置环境变量 RA_CLI 指向它。"
            return
        }
        client.launch(cliPath: cli, varDir: varDir)
        client.request("doctor") { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                switch result {
                case .success(let obj):
                    let r = obj["result"] as? [String: Any] ?? [:]
                    let exif = r["exifread"] as? Bool ?? false
                    let pil = r["pillow"] as? Bool ?? false
                    let et = r["exiftool"] as? String
                    self.doctorText = "ExifTool: \(et ?? "未找到") ｜ exifread: \(exif ? "是" : "否") ｜ Pillow: \(pil ? "是" : "否")"
                case .failure(let e):
                    self.doctorText = "自检失败: \(e.localizedDescription)"
                }
            }
        }
    }

    func persist() {
        defaults.set(source, forKey: "source")
        defaults.set(output, forKey: "output")
        defaults.set(brandFolder, forKey: "brandFolder")
        defaults.set(handleJpg, forKey: "handleJpg")
        defaults.set(handleVideo, forKey: "handleVideo")
        defaults.set(staging, forKey: "staging")
        defaults.set(mode, forKey: "mode")
    }

    func chooseSource() {
        if let p = chooseDirectory() {
            source = p
            persist()
        }
    }

    func chooseOutput() {
        if let p = chooseDirectory() {
            output = p
            persist()
        }
    }

    private var opts: [String: Any] {
        ["brandFolder": brandFolder, "handleJpg": handleJpg,
         "handleVideo": handleVideo, "staging": staging, "mode": mode]
    }

    func preview() {
        guard !source.isEmpty, !output.isEmpty else {
            errorText = "请先填写源与输出目录"
            return
        }
        previewing = true
        previewResult = nil
        client.request("preview", payload: ["source": source, "output": output, "opts": opts]) { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.previewing = false
                switch result {
                case .success(let obj):
                    if let r = obj["result"] as? [String: Any] {
                        self.previewResult = PreviewResult.parse(r)
                    }
                case .failure(let e):
                    self.errorText = e.localizedDescription
                }
            }
        }
    }

    func start() {
        guard !isRunning else { return }
        // 移动模式 + 可移动介质二次确认
        if mode == "move", let pr = previewResult, pr.removable {
            // 由 ContentView 弹确认后调用 doStart；这里直接走（确认逻辑在 UI 层）
        }
        doStart()
    }

    func doStart() {
        logs.removeAll()
        progress = ProgressSnapshot(status: "", current: 0, total: 0, success: 0, failed: 0, skipped: 0)
        statusText = "正在启动…"
        isRunning = true
        client.request("start", payload: ["source": source, "output": output, "opts": opts]) { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                switch result {
                case .success(let obj):
                    self.taskId = obj["result"] as? String ?? (obj["result"] as? [String: Any])?["taskId"] as? String ?? ""
                case .failure(let e):
                    self.isRunning = false
                    self.errorText = e.localizedDescription
                }
            }
        }
    }

    func cancel() {
        guard !taskId.isEmpty else { return }
        client.request("cancel", payload: ["taskId": taskId]) { _ in }
    }

    func stopClient() {
        client.stop()
    }

    // MARK: - 事件

    private func handleEvent(_ evt: IpcClient.Event) {
        switch evt {
        case .progress(let obj):
            if let s = obj["status"] as? String { statusText = s }
            progress = ProgressSnapshot(
                status: obj["status"] as? String ?? "",
                current: obj["current"] as? Int ?? 0,
                total: obj["total"] as? Int ?? 0,
                success: obj["success"] as? Int ?? 0,
                failed: obj["failed"] as? Int ?? 0,
                skipped: obj["skipped"] as? Int ?? 0)
            appendLogs(obj["logs"] as? [[String: Any]] ?? [])
        case .done(let obj):
            isRunning = false
            let status = obj["status"] as? String ?? "done"
            let success = obj["success"] as? Int ?? 0
            let failed = obj["failed"] as? Int ?? 0
            let skipped = obj["skipped"] as? Int ?? 0
            statusText = status
            if status == "error" {
                errorText = obj["error"] as? String ?? "归档出错"
            }
            let msg = "完成：成功 \(success) / 失败 \(failed) / 跳过 \(skipped)"
            logs.append(msg)
        }
    }

    private func appendLogs(_ items: [[String: Any]]) {
        for it in items {
            let t = it["t"] as? String ?? ""
            if let msg = it["msg"] as? String {
                logs.append("[\(t)] \(msg)")
            } else if let src = it["src"] as? String, let dst = it["dst"] as? String {
                logs.append("[\(t)] \(src) -> \(dst)")
            } else {
                logs.append("[\(t)]")
            }
        }
    }
}
