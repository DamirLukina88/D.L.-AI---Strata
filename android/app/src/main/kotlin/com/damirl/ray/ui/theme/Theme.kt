/*
 * Copyright 2026 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.damirl.ray.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Always Strata's dark palette: the companion hosts the web app, whose default theme is dark, and its native screens
// (setup, the voice drawer) should look like part of it rather than follow the wallpaper or the system theme
private val StrataColorScheme = darkColorScheme(
    primary = StrataAccent,
    onPrimary = Color.White,
    primaryContainer = StrataAccentTint,
    onPrimaryContainer = StrataAccentText,
    secondary = StrataAccentText,
    onSecondary = StrataBg,
    secondaryContainer = StrataAccentTint,
    onSecondaryContainer = StrataAccentText,
    tertiary = StrataOk,
    background = StrataBg,
    onBackground = StrataInk,
    surface = StrataSurface,
    onSurface = StrataInk,
    surfaceVariant = StrataSurface2,
    onSurfaceVariant = StrataInkSoft,
    surfaceContainerLowest = StrataBg,
    surfaceContainerLow = StrataSurface,
    surfaceContainer = StrataSurface,
    surfaceContainerHigh = StrataSurface2,
    surfaceContainerHighest = StrataSurface2,
    outline = StrataInkMuted,
    outlineVariant = StrataLine,
    error = StrataDanger,
)

@Composable
fun RayTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = StrataColorScheme,
        typography = Typography,
        content = content
    )
}
