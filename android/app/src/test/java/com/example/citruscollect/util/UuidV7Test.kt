package com.example.citruscollect.util

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UuidV7Test {

    @Test
    fun generatedIdMatchesServerContract() {
        repeat(200) {
            val id = UuidV7.generate()
            assertTrue("应匹配 UUIDv7 契约: $id", UuidV7.regex.matches(id))
            assertEquals(36, id.length)
            assertEquals('7', id[14]) // 版本位
        }
    }

    @Test
    fun oldV4DraftsAreRejected() {
        // 旧实现用 UUID.randomUUID()（v4），第三组不是 7xxx，必须被识别为非法。
        assertFalse(UuidV7.isValid("019a0000-0000-4000-8000-000000000003"))
        assertFalse(UuidV7.isValid("not-a-uuid"))
        assertTrue(UuidV7.isValid(UuidV7.generate()))
    }

    @Test
    fun idsAreUnique() {
        val seen = HashSet<String>()
        repeat(1000) { seen.add(UuidV7.generate()) }
        assertEquals(1000, seen.size)
    }
}
