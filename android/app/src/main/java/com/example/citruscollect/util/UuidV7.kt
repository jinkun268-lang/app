package com.example.citruscollect.util

import java.security.SecureRandom
import java.util.UUID

/**
 * 生成符合 RFC 9562 布局的 UUIDv7（小写连字符形式），与服务端 `Id` 契约
 * `^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` 一致。
 *
 * 布局：48 位毫秒时间戳 + 4 位版本(7) + 12 位随机 + 2 位变体(10) + 62 位随机。
 */
object UuidV7 {
    private val random = SecureRandom()

    /** 用于识别旧版本生成的 UUIDv4 草稿（不可上传）。 */
    val regex: Regex = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

    fun generate(): String {
        val timestamp = System.currentTimeMillis() and 0xFFFFFFFFFFFFL // 48 bits
        val randA = random.nextLong() and 0xFFFL // 12 bits
        val randB = random.nextLong() and 0x3FFFFFFFFFFFFFFFL // 62 bits
        val msb = (timestamp shl 16) or (0x7L shl 12) or randA
        val lsb = (0x8L shl 60) or randB
        return UUID(msb, lsb).toString()
    }

    fun isValid(value: String): Boolean = regex.matches(value)
}
