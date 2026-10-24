import Foundation

/// 预览结果（来自 core.do_preview）。
struct PreviewSample: Identifiable {
    let id = UUID()
    let src: String
    let date: String
    let dateFrom: String
    let dst: String
    let bad: Bool
}

struct PreviewResult {
    let total: Int
    let sizeBytes: Int64
    let dateRange: (String, String)
    let badCount: Int
    let conflicts: Int
    let rawSkipHint: Int
    let removable: Bool
    let removableNote: String
    let exiftool: Bool
    let samples: [PreviewSample]

    static func parse(_ obj: [String: Any]) -> PreviewResult {
        let total = obj["total"] as? Int ?? 0
        let size = obj["size"] as? Int64 ?? (obj["size"] as? Int).map(Int64.init) ?? 0
        let range = obj["date_range"] as? [Any] ?? []
        let d0 = range.count > 0 ? (range[0] as? String ?? "") : ""
        let d1 = range.count > 1 ? (range[1] as? String ?? "") : ""
        let samples = (obj["sample"] as? [[String: Any]] ?? []).map { s in
            PreviewSample(
                src: s["src"] as? String ?? "",
                date: s["date"] as? String ?? "",
                dateFrom: s["date_from"] as? String ?? "",
                dst: s["dst_rel"] as? String ?? "",
                bad: s["bad"] as? Bool ?? false)
        }
        return PreviewResult(
            total: total,
            sizeBytes: size,
            dateRange: (d0, d1),
            badCount: obj["bad_count"] as? Int ?? 0,
            conflicts: obj["conflicts"] as? Int ?? 0,
            rawSkipHint: obj["raw_skip_hint"] as? Int ?? 0,
            removable: obj["removable"] as? Bool ?? false,
            removableNote: obj["removable_note"] as? String ?? "",
            exiftool: obj["exiftool"] as? Bool ?? false,
            samples: samples)
    }
}

/// 进度快照。
struct ProgressSnapshot {
    let status: String
    let current: Int
    let total: Int
    let success: Int
    let failed: Int
    let skipped: Int
}

func formatBytes(_ b: Int64) -> String {
    let gb = Double(b) / 1_073_741_824.0
    return String(format: "%.2f GB", gb)
}
