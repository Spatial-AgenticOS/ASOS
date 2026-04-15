// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "FeralNode",
    platforms: [.iOS(.v16)],
    products: [
        .library(name: "FeralBridge", targets: ["FeralBridge"]),
    ],
    targets: [
        .target(
            name: "FeralBridge",
            path: "Sources/FeralBridge"
        ),
    ]
)
