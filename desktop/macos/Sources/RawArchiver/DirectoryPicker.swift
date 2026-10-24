import AppKit

/// 用 NSOpenPanel 选择目录（SwiftUI 的 fileImporter 只适合选文件）。
func chooseDirectory() -> String? {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.allowsMultipleSelection = false
    panel.prompt = "选择"
    panel.message = "选择目录"
    if panel.runModal() == .OK {
        return panel.url?.path
    }
    return nil
}

/// 在访达中打开目录。
func revealInFinder(_ path: String) {
    if !path.isEmpty {
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }
}
