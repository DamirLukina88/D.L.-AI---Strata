package com.damirl.ray.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.damirl.ray.R
import com.damirl.ray.ui.theme.StrataLine
import com.damirl.ray.ui.theme.StrataSurface2

// Ray with his mug (the launcher icon's foreground) on a rounded tile.  The foreground keeps the adaptive icon's
// margins (the panda fills 66 of its 108 dp), so it is drawn larger than the tile and clipped to it
@Composable
fun RayAvatar(size: Dp, modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(size * 0.3f)
    Box(
        modifier = modifier
            .size(size)
            .clip(shape)
            .background(StrataSurface2)
            .border(1.dp, StrataLine, shape),
        contentAlignment = Alignment.Center
    ) {
        Image(
            painter = painterResource(R.mipmap.ic_launcher_foreground),
            contentDescription = "Ray",
            modifier = Modifier.requiredSize(size * 1.45f)
        )
    }
}
