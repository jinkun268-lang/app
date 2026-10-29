package com.example.citruscollect.util

import org.junit.Assert.*
import org.junit.Test

class PhotoQualityTest {
    @Test fun exposureWarningsDoNotPretendToDiagnoseDisease() {
        assertTrue(PhotoQuality.assess(IntArray(32 * 32) { 3 }, 32, 32).warnings.contains("画面偏暗，建议补光或调整角度"))
        assertTrue(PhotoQuality.assess(IntArray(32 * 32) { 253 }, 32, 32).warnings.contains("画面偏亮，建议避开直射光"))
    }

    @Test fun lowDetailNeedsCheckingButDetailedTexturePasses() {
        assertTrue(PhotoQuality.assess(IntArray(32 * 32) { 120 }, 32, 32).warnings.any { it.contains("清晰度") })
        val texture = IntArray(32 * 32) { if ((it / 32 + it % 32) % 2 == 0) 75 else 180 }
        assertTrue(PhotoQuality.assess(texture, 32, 32).warnings.isEmpty())
    }

    @Test fun invalidImageIsRejectedAndSmallImageIsFlagged() {
        assertThrows(IllegalArgumentException::class.java) { PhotoQuality.assess(intArrayOf(1), 3, 3) }
        assertTrue(PhotoQuality.assess(IntArray(8 * 8) { 128 }, 8, 8).warnings.isNotEmpty())
    }

    @Test fun locationMustBeFreshValidAndAccurateEnough() {
        val now = 900_000L
        assertTrue(GeoFix(30.0, 120.0, 20.0, now).usableAt(now))
        assertFalse(GeoFix(30.0, 120.0, 20.0, now - 120_001).usableAt(now))
        assertFalse(GeoFix(91.0, 120.0, 20.0, now).usableAt(now))
        assertFalse(GeoFix(30.0, Double.NaN, 20.0, now).usableAt(now))
        assertFalse(GeoFix(30.0, 120.0, 1_001.0, now).usableAt(now))
        assertFalse(GeoFix(30.0, 120.0, -1.0, now).usableAt(now))
        assertFalse(GeoFix(30.0, 120.0, 20.0, now + 60_000).usableAt(now))
    }
}
