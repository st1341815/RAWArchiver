import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @State private var showMoveConfirm = false
    @State private var showError = false
    @State private var showAbout = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            directoryFields
            options
            actionButtons
            Divider()
            if model.previewResult != nil || model.previewing {
                previewSection
            }
            if model.isRunning || !model.logs.isEmpty {
                progressSection
            }
            Spacer(minLength: 0)
        }
        .padding()
        .onAppear {
            model.startup()
        }
        .onDisappear {
            model.persist()
        }
        .alert("确认清空源设备？", isPresented: $showMoveConfirm) {
            Button("确认归档后清空源", role: .destructive) { model.doStart() }
            Button("取消", role: .cancel) {}
        } message: {
            Text("源为可移动设备，移动模式下归档完成后将清空卡上的文件，此操作不可回滚。")
        }
        .alert("错误", isPresented: $showError) {
            Button("好", role: .cancel) {}
        } message: {
            Text(model.errorText)
        }
        .sheet(isPresented: $showAbout) {
            aboutView
        }
    }

    private var header: some View {
        HStack {
            Text("RAW 归档").font(.title2).bold()
            if let pr = model.previewResult {
                Text("v1.1.0").font(.caption).foregroundColor(.secondary)
            } else {
                Text("v1.1.0").font(.caption).foregroundColor(.secondary)
            }
            Spacer()
            Button("关于") { showAbout = true }
        }
    }

    private var directoryFields: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("源（SD/TF/U 盘或本地目录）").font(.headline)
            HStack {
                TextField("/Volumes/SD卡/DCIM", text: $model.source)
                    .textFieldStyle(.roundedBorder)
                    .onChange(of: model.source) { _ in model.persist() }
                Button("选择目录…") { model.chooseSource() }
            }
            Text("输出目录（归档落点）").font(.headline)
            HStack {
                TextField("~/Pictures/归档", text: $model.output)
                    .textFieldStyle(.roundedBorder)
                    .onChange(of: model.output) { _ in model.persist() }
                Button("选择目录…") { model.chooseOutput() }
            }
        }
    }

    private var options: some View {
        HStack(spacing: 16) {
            Toggle("按品牌分层", isOn: $model.brandFolder)
                .onChange(of: model.brandFolder) { _ in model.persist() }
            Toggle("处理 JPG", isOn: $model.handleJpg)
                .onChange(of: model.handleJpg) { _ in model.persist() }
            Toggle("处理视频", isOn: $model.handleVideo)
                .onChange(of: model.handleVideo) { _ in model.persist() }
            Toggle("内部暂存", isOn: $model.staging)
                .help("先完整拷到启动盘再归档（卡源推荐；空间紧张可取消）")
                .onChange(of: model.staging) { _ in model.persist() }
            Spacer()
            Picker("模式", selection: $model.mode) {
                Text("复制（保留源）").tag("copy")
                Text("移动（清空源）").tag("move")
            }
            .pickerStyle(.menu)
            .frame(width: 180)
            .onChange(of: model.mode) { _ in model.persist() }
        }
    }

    private var actionButtons: some View {
        HStack(spacing: 10) {
            Button("预览") {
                model.preview()
            }
            .disabled(model.previewing || model.isRunning || model.source.isEmpty || model.output.isEmpty)

            Button("开始归档") {
                if model.mode == "move", let pr = model.previewResult, pr.removable {
                    showMoveConfirm = true
                } else {
                    model.doStart()
                }
            }
            .disabled(model.isRunning || model.previewResult == nil)

            Button("取消") { model.cancel() }
                .disabled(!model.isRunning)

            if !model.errorText.isEmpty {
                Button("⚠") { showError = true }
            }
        }
    }

    private var previewSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            if model.previewing {
                ProgressView("正在扫描源（读卡较慢，请稍候）…")
            } else if let pr = model.previewResult {
                Text(summaryText(pr)).font(.callout)
                if !warningsText(pr).isEmpty {
                    Text(warningsText(pr))
                        .font(.callout)
                        .foregroundColor(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Table(pr.samples) {
                    TableColumn("源文件", value: \.src)
                    TableColumn("拍摄日期", value: \.date)
                    TableColumn("日期来源", value: \.dateFrom)
                    TableColumn("目标路径", value: \.dst)
                }
                .frame(minHeight: 160)
            }
        }
    }

    private var progressSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            ProgressView(value: progressValue)
            HStack {
                Text("\(model.statusText)  \(model.progress.current)/\(model.progress.total)")
                Spacer()
                Text("成功 \(model.progress.success) 失败 \(model.progress.failed) 跳过 \(model.progress.skipped)")
            }
            .font(.callout)
            ScrollViewReader { proxy in
                ScrollView {
                    Text(model.logs.joined(separator: "\n"))
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .id("logtail")
                }
                .frame(height: 140)
                .background(Color(NSColor.textBackgroundColor))
                .border(Color.secondary.opacity(0.3))
                .onChange(of: model.logs.count) { _ in
                    proxy.scrollTo("logtail", anchor: .bottom)
                }
            }
        }
    }

    private var progressValue: Double {
        let t = max(model.progress.total, 1)
        return Double(model.progress.current) / Double(t)
    }

    private func summaryText(_ pr: PreviewResult) -> String {
        var s = "\(pr.total) 个文件 / \(formatBytes(pr.sizeBytes))"
        if !pr.dateRange.0.isEmpty && !pr.dateRange.1.isEmpty {
            s += " ｜ 日期 \(pr.dateRange.0) ~ \(pr.dateRange.1)"
        }
        s += " ｜ ExifTool: \(pr.exiftool ? "可用" : "未找到")"
        return s
    }

    private func warningsText(_ pr: PreviewResult) -> String {
        var w = ""
        if pr.badCount > 0 { w += "注意：\(pr.badCount) 个文件只能靠文件修改时间推断日期。\n" }
        if pr.rawSkipHint > 0 { w += "提示：\(pr.rawSkipHint) 个照片读不到拍摄日期，执行时将被跳过。\n" }
        if pr.conflicts > 0 { w += "提示：\(pr.conflicts) 个目标已存在同名文件，将自动追加 _1/_2。\n" }
        if pr.removable && model.mode == "move" {
            w += "源为可移动设备，移动模式下归档完成后将清空源设备，此操作不可回滚。"
        }
        return w
    }

    private var aboutView: some View {
        VStack(spacing: 8) {
            Text("RAW 归档").font(.title)
            Text("v1.1.0").foregroundColor(.secondary)
            Text(model.doctorText).font(.callout).foregroundColor(.secondary).padding(.horizontal)
            Text("数据目录：\(model.varDir)").font(.caption).foregroundColor(.secondary)
            Button("关闭") { showAbout = false }
        }
        .padding(24)
        .frame(width: 420)
    }
}
