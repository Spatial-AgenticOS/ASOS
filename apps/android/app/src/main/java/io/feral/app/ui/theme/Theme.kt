package ai.feral.app.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

val FeralTeal = Color(0xFF00BFA5)
val FeralTealDark = Color(0xFF00897B)

private val DarkColorScheme = darkColorScheme(
    primary = FeralTeal,
    secondary = FeralTealDark,
    tertiary = Color(0xFF80CBC4),
)

private val LightColorScheme = lightColorScheme(
    primary = FeralTeal,
    secondary = FeralTealDark,
    tertiary = Color(0xFF004D40),
)

@Composable
fun FeralTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = colorScheme.surface.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !darkTheme
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography(),
        content = content,
    )
}
