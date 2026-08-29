package com.zigger06.tajiksttcollector.audio

import android.media.MediaDataSource

/** MediaPlayer bridge for WAV bytes already cached in process RAM. */
class ByteArrayMediaDataSource(private val bytes: ByteArray) : MediaDataSource() {
    override fun getSize(): Long = bytes.size.toLong()

    override fun readAt(position: Long, buffer: ByteArray, offset: Int, size: Int): Int {
        if (position < 0 || position >= bytes.size) return -1
        val available = bytes.size - position.toInt()
        val count = minOf(size, available)
        bytes.copyInto(
            destination = buffer,
            destinationOffset = offset,
            startIndex = position.toInt(),
            endIndex = position.toInt() + count,
        )
        return count
    }

    override fun close() = Unit
}
