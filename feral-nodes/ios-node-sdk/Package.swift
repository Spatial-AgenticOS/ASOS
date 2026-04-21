// swift-tools-version: 5.9
//
// FeralNodeSDK — iOS phone-as-HUP-daemon bridge for Theora hardware.
//
// The three vendor adapters (Veepoo wristband, JW Ble health glasses,
// QCSDK W610) are compiled into the library but their attach()
// implementations intentionally throw FeralNodeError.adapterNotWired
// until the vendor frameworks are linked in. See README.md for the
// per-adapter wire-up checklist.
import PackageDescription

let package = Package(
    name: "FeralNodeSDK",
    platforms: [
        .iOS(.v15),
        .macOS(.v12),
    ],
    products: [
        .library(
            name: "FeralNodeSDK",
            targets: ["FeralNodeSDK"]
        ),
    ],
    dependencies: [
        // No external Swift deps. URLSessionWebSocketTask handles the
        // HUP wire; vendor frameworks are linked via the host app,
        // not this package, because they ship as .framework binaries
        // not SwiftPM packages.
    ],
    targets: [
        .target(
            name: "FeralNodeSDK",
            path: "Sources/FeralNodeSDK"
        ),
        .testTarget(
            name: "FeralNodeSDKTests",
            dependencies: ["FeralNodeSDK"],
            path: "Tests/FeralNodeSDKTests"
        ),
    ]
)
