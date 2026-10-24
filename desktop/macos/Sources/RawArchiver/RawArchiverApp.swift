import SwiftUI

@main
struct RawArchiverApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 780, minHeight: 620)
        }
        .windowResizability(.contentSize)
    }
}
