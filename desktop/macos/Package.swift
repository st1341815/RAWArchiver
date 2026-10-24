// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "RawArchiver",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "RawArchiver",
            path: "Sources/RawArchiver"
        )
    ]
)
