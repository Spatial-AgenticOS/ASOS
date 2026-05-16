package ai.feral.bridge

/**
 * FERAL v2 ambient-OS design tokens — Android counterpart of
 * `ASOS/feral-nodes/ios-app/App/FeralV2Tokens.swift` and
 * `feral-client-v2/src/styles/tokens.css`. Canonical source of truth
 * for v2 colors, type, radii, and motion on Android. Keep all three
 * platform copies in lock-step; drift means the mobile surface looks
 * different across iOS and Android, and across mobile and web.
 *
 * Persona-continuity rule: Orb / Chat / Voice screens must read from
 * these tokens only — no hardcoded colors.
 *
 * **No Compose dependency**: the bridge module is platform-agnostic
 * (used from XML and Compose apps alike), so this file deals in raw
 * values. Convert per consuming surface:
 *
 * - **Compose**: `Color(FeralV2Tokens.bgBaseArgb)`,
 *   `FeralV2Tokens.radiusXSDp.dp`, `FeralV2Tokens.sizeXSSp.sp`,
 *   `tween(FeralV2Tokens.durBaseMs, easing = CubicBezierEasing(…))`.
 * - **View**: `view.setBackgroundColor(FeralV2Tokens.bgBaseArgb)`,
 *   resources `dpToPx(FeralV2Tokens.radiusXSDp)`.
 */
object FeralV2Tokens {

    // ─────────────────────────── Base + surfaces ───────────────────────────
    /** `#0B0B0D` ambient bg base. */
    const val bgBaseArgb = 0xFF0B0B0D.toInt()

    /** `#060607` ambient bg deep. */
    const val bgDeepArgb = 0xFF060607.toInt()

    /** White at 6% — surface level 0 (chrome). */
    const val surface0Argb = 0x0FFFFFFF
    /** White at 9% — surface level 1 (cards). */
    const val surface1Argb = 0x17FFFFFF
    /** White at 13% — surface level 2 (raised). */
    const val surface2Argb = 0x21FFFFFF
    /** White at 18% — elevated surface (sheet / popover). */
    const val surfaceElevArgb = 0x2EFFFFFF

    /** White at 8% — default hairline divider. */
    const val hairlineArgb = 0x14FFFFFF
    /** White at 14% — strong hairline (selected). */
    const val hairlineStrongArgb = 0x24FFFFFF
    /** White at 22% — focused hairline. */
    const val hairlineFocusArgb = 0x38FFFFFF

    // ───────────────────────────────── Text ────────────────────────────────
    const val textPrimaryArgb = 0xFFF5F5F7.toInt()
    const val textSecondaryArgb = 0xFFA1A1A8.toInt()
    const val textTertiaryArgb = 0xFF6E6E75.toInt()
    const val textInverseArgb = 0xFF0B0B0D.toInt()

    // ──────────────────────── Accent (interactive only) ────────────────────
    /** `#0A84FF` — interactive only, never decorative. */
    const val accentArgb = 0xFF0A84FF.toInt()
    /** Accent at 18% — soft fill (selected pill, focus halo). */
    const val accentSoftArgb = 0x2E0A84FF.toInt()
    /** Accent at 35% — ring around focused element. */
    const val accentRingArgb = 0x590A84FF.toInt()

    // ──────────────────── Semantic state (never decorative) ─────────────────
    /** `#30D158` — live / connected / healthy. */
    const val stateLiveArgb = 0xFF30D158.toInt()
    /** `#FFD60A` — warning / degraded / pending. */
    const val stateWarnArgb = 0xFFFFD60A.toInt()
    /** `#FF453A` — error / disconnected / blocked. */
    const val stateErrorArgb = 0xFFFF453A.toInt()

    // ──────────────────────────────── Radii ────────────────────────────────
    /** Radius scale in **density-independent pixels** (dp). */
    const val radiusXSDp = 6
    const val radiusSMDp = 10
    const val radiusMDDp = 14
    const val radiusLGDp = 20

    // ───────────────────────────── Type scale ──────────────────────────────
    /** Type scale in **scale-independent pixels** (sp). */
    const val sizeXSSp = 11
    const val sizeSMSp = 12
    const val sizeBaseSp = 13
    const val sizeMDSp = 15
    const val sizeLGSp = 18
    const val sizeXLSp = 22
    const val size2XLSp = 32

    // ──────────────────────────────── Motion ───────────────────────────────
    /** Animation durations in **milliseconds**. */
    const val durFastMs = 120
    const val durBaseMs = 180
    const val durSlowMs = 320

    /**
     * Cubic-bezier easing matching iOS
     * `Animation.timingCurve(0.16, 1, 0.3, 1, …)`. Compose:
     *
     *   ```
     *   tween(
     *       durationMillis = FeralV2Tokens.durBaseMs,
     *       easing = CubicBezierEasing(*FeralV2Tokens.easeOutControlPoints),
     *   )
     *   ```
     */
    val easeOutControlPoints: FloatArray = floatArrayOf(0.16f, 1f, 0.3f, 1f)
}
