import Foundation

/// 与核心引擎 CLI 的 IPC 客户端（NDJSON over stdin/stdout）。
/// 线程安全：所有请求与响应处理都在串行队列上。
final class IpcClient {
    enum Event {
        case progress([String: Any])
        case done([String: Any])
    }

    var onEvent: ((Event) -> Void)?

    private var process: Process?
    private var stdinHandle: FileHandle?
    private var nextId = 0
    private var pending: [Int: (Result<[String: Any], Error>) -> Void] = [:]
    private var buffer = Data()
    private let queue = DispatchQueue(label: "rawarchiver.ipc")

    var isRunning: Bool {
        process?.isRunning ?? false
    }

    /// 定位 CLI 可执行文件：环境变量 RA_CLI 优先，其次 .app 内嵌的 RawArchiver-cli。
    static func locateCli() -> String? {
        if let env = ProcessInfo.processInfo.environment["RA_CLI"], !env.isEmpty {
            return env
        }
        if let res = Bundle.main.resourceURL {
            let cli = res.appendingPathComponent("RawArchiver-cli/RawArchiver-cli")
            if FileManager.default.isExecutableFile(atPath: cli.path) {
                return cli.path
            }
        }
        return nil
    }

    func launch(cliPath: String, varDir: String) {
        stop()

        let p = Process()
        let inPipe = Pipe()
        let outPipe = Pipe()
        p.executableURL = URL(fileURLWithPath: cliPath)
        p.arguments = ["--ipc"]
        p.standardInput = inPipe
        p.standardOutput = outPipe
        p.standardError = FileHandle.nullDevice
        var env = ProcessInfo.processInfo.environment
        env["TRIM_PKGVAR"] = varDir
        env["PYTHONIOENCODING"] = "utf-8"
        p.environment = env

        do {
            try p.run()
        } catch {
            return
        }
        process = p
        stdinHandle = inPipe.fileHandleForWriting
        buffer = Data()
        pending.removeAll()
        nextId = 0

        outPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { return }
            self?.queue.async { self?.consume(data) }
        }
    }

    func request(_ cmd: String, payload: [String: Any] = [:],
                 completion: @escaping (Result<[String: Any], Error>) -> Void) {
        queue.async { [weak self] in
            guard let self = self, self.isRunning else {
                completion(.failure(NSError(domain: "ipc", code: -1,
                    userInfo: [NSLocalizedDescriptionKey: "核心服务未运行"])))
                return
            }
            self.nextId += 1
            let id = self.nextId
            self.pending[id] = completion
            var obj = payload
            obj["id"] = id
            obj["cmd"] = cmd
            guard let data = try? JSONSerialization.data(withJSONObject: obj) else {
                self.pending.removeValue(forKey: id)
                completion(.failure(NSError(domain: "ipc", code: -2,
                    userInfo: [NSLocalizedDescriptionKey: "请求序列化失败"])))
                return
            }
            var line = data
            line.append(0x0A)
            self.stdinHandle?.write(line)
        }
    }

    func stop() {
        if let h = stdinHandle {
            try? h.write(Data("{\"id\":999999,\"cmd\":\"shutdown\"}\n".utf8))
            try? h.close()
        }
        process?.terminate()
        process = nil
        stdinHandle = nil
    }

    // MARK: - 私有

    private func consume(_ data: Data) {
        buffer.append(data)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let lineData = buffer[buffer.startIndex..<nl]
            buffer.removeSubrange(buffer.startIndex...nl)
            let line = String(data: lineData, encoding: .utf8) ?? ""
            handleLine(line)
        }
    }

    private func handleLine(_ line: String) {
        guard !line.isEmpty,
              let data = line.data(using: .utf8),
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return
        }
        if let id = obj["id"] as? Int {
            let cb = pending.removeValue(forKey: id)
            guard let cb = cb else { return }
            if let ok = obj["ok"] as? Bool, !ok {
                let msg = obj["error"] as? String ?? "未知错误"
                cb(.failure(NSError(domain: "ipc", code: 1,
                    userInfo: [NSLocalizedDescriptionKey: msg])))
            } else {
                cb(.success(obj))
            }
        } else if let evt = obj["evt"] as? String {
            if evt == "progress" { onEvent?(.progress(obj)) }
            else if evt == "done" { onEvent?(.done(obj)) }
        }
    }
}
