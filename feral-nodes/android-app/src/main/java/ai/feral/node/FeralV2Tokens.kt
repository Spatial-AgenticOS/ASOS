package ai.feral.node

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.tween
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Feral v2 design tokens — canonical source of truth for the Android
 * ambient-OS UI. Mirrors `feral-client-v2/src/styles/tokens.css` and
 * `ios-app/App/FeralV2Tokens.swift`. Keep all three in lock-step.
 *
 * Persona-continuity rule: Orb / Chat / Voice screens must consume these
 * tokens — no hardcoded Color, FontSize, or Dp literals.
 */
object FeralV2Tokens {
    // ── Base + surfaces ─────────────────────────────────────────
    val bgBase      = Color(0xFF0B0B0D)
    val bgDeep      = Color(0xFF060607)
    val surface0    = Color(0x0FFFFFFF)
    val surface1    = Color(0x17FFFFFF)
    val surface2    = Color(0x21FFFFFF)
    val surfaceElev = Color(0x2EFFFFFF)

    val hairline        = Color(0x14FFFFFF)
    val hairlineStrong  = Color(0x24FFFFFF)
    val hairlineFocus   = Color(0x38FFFFFF)

    // ── Text ────────────────────────────────────────────────────
    val textPrimary    = Color(0xFFF5F5F7)
    val textSecondary  = Color(0xFFA1A1A8)
    val textTertiary   = Color(0xFF6E6E76)
    val textInverse    = Color(0xFF0B0B0D)

    // ── Accent (interactive only) ───────────────────────────────
    val accent     = Color(0xFF0A84FF)
    val accentSoft = Color(0x2E0A84FF)
    val accentRing = Color(0x590A84FF)

    // ── Semantic state ──────────────────────────────────────────
    val stateLive  = Color(0xFF30D158)
    val stateWarn  = Color(0xFFFFD60A)
    val stateError = Color(0xFFFF453A)

    // ── Radii ───────────────────────────────────────────────────
    val radiusXS = 6.dp
    val radiusSM = 10.dp
    val radiusMD = 14.dp
    val radiusLG = 20.dp

    // ── Type scale ──────────────────────────────────────────────
    val sizeXS   = 11.sp
    val sizeSM   = 12.sp
    val sizeBase = 13.sp
    val sizeMD   = 15.sp
    val sizeLG   = 18.sp
    val sizeXL   = 22.sp
    val size2XL  = 32.sp

    // ── Motion ──────────────────────────────────────────────────
    const val DUR_FAST_MS = 120
    const val DUR_BASE_MS = 180
    const val DUR_SLOW_MS = 320
    val easeOut = CubicBezierEasing(0.16f, 1f, 0.3f, 1f)
    fun baseAnim() = tween<Float>(durationMillis = DUR_BASE_MS, easing = easeOut)
}
