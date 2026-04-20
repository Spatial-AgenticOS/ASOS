//
//  FeralV2Tokens.swift
//  Feral iOS — shared design tokens for the v2 ambient-OS UI.
//
//  Canonical source of truth for v2 colors, type, radii, and motion on
//  iOS. Mirrors `feral-client-v2/src/styles/tokens.css`. Keep both files
//  in lock-step; drift means the mobile surface looks different from the
//  web client.
//
//  Persona-continuity rule: Orb / Chat / Voice screens must read from
//  these tokens only — no hardcoded SwiftUI Colors.
//
import SwiftUI

public enum FeralV2Tokens {
    // MARK: - Base + surfaces
    public static let bgBase       = Color(red: 0.043, green: 0.043, blue: 0.051)   // #0B0B0D
    public static let bgDeep       = Color(red: 0.024, green: 0.024, blue: 0.027)   // #060607
    public static let surface0     = Color.white.opacity(0.06)
    public static let surface1     = Color.white.opacity(0.09)
    public static let surface2     = Color.white.opacity(0.13)
    public static let surfaceElev  = Color.white.opacity(0.18)

    public static let hairline        = Color.white.opacity(0.08)
    public static let hairlineStrong  = Color.white.opacity(0.14)
    public static let hairlineFocus   = Color.white.opacity(0.22)

    // MARK: - Text
    public static let textPrimary    = Color(red: 0.96, green: 0.96, blue: 0.97)
    public static let textSecondary  = Color(red: 0.63, green: 0.63, blue: 0.66)
    public static let textTertiary   = Color(red: 0.43, green: 0.43, blue: 0.46)
    public static let textInverse    = Color(red: 0.043, green: 0.043, blue: 0.051)

    // MARK: - Accent (interactive-only)
    public static let accent       = Color(red: 0.039, green: 0.518, blue: 1.0)    // #0A84FF
    public static let accentSoft   = Color(red: 0.039, green: 0.518, blue: 1.0).opacity(0.18)
    public static let accentRing   = Color(red: 0.039, green: 0.518, blue: 1.0).opacity(0.35)

    // MARK: - Semantic state (never decorative)
    public static let stateLive   = Color(red: 0.188, green: 0.820, blue: 0.345)   // #30D158
    public static let stateWarn   = Color(red: 1.000, green: 0.839, blue: 0.039)   // #FFD60A
    public static let stateError  = Color(red: 1.000, green: 0.271, blue: 0.227)   // #FF453A

    // MARK: - Radii
    public static let radiusXS: CGFloat = 6
    public static let radiusSM: CGFloat = 10
    public static let radiusMD: CGFloat = 14
    public static let radiusLG: CGFloat = 20

    // MARK: - Type scale
    public static let sizeXS: CGFloat   = 11
    public static let sizeSM: CGFloat   = 12
    public static let sizeBase: CGFloat = 13
    public static let sizeMD: CGFloat   = 15
    public static let sizeLG: CGFloat   = 18
    public static let sizeXL: CGFloat   = 22
    public static let size2XL: CGFloat  = 32

    // MARK: - Motion
    public static let durFast: Double = 0.12
    public static let durBase: Double = 0.18
    public static let durSlow: Double = 0.32
    public static let easeOut = Animation.timingCurve(0.16, 1, 0.3, 1, duration: durBase)
}
