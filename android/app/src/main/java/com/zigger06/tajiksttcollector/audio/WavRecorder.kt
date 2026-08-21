package com.zigger06.tajiksttcollector.audio

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.concurrent.thread

data class RecordingResult(
    val file: File,
    val durationMs: Long,
    val sampleRate: Int,
)

class WavRecorder {
    private var audioRecord: AudioRecord? = null
    private var worker: Thread? = null
    private var outputFile: File? = null
    private var bytesWritten: Long = 0

    @Volatile
    var isRecording: Boolean = false
        private set

    var sampleRate: Int = 16000
        private set

    fun start(file: File) {
        check(!isRecording) { "Recording is already active" }
        file.parentFile?.mkdirs()
        val recorder = createRecorder()
        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            error("Microphone could not be initialized")
        }

        outputFile = file
        audioRecord = recorder
        bytesWritten = 0
        recorder.startRecording()
        isRecording = true
        worker = thread(name = "wav-recorder") {
            val buffer = ByteArray(maxOf(4096, recorder.bufferSizeInFrames * 2))
            FileOutputStream(file).use { output ->
                output.write(ByteArray(WAV_HEADER_SIZE))
                while (isRecording) {
                    val read = recorder.read(buffer, 0, buffer.size)
                    if (read > 0) {
                        output.write(buffer, 0, read)
                        bytesWritten += read
                    }
                }
                output.flush()
            }
        }
    }

    fun stop(): RecordingResult? {
        if (!isRecording) return null
        isRecording = false
        val recorder = audioRecord
        try {
            recorder?.stop()
        } catch (_: IllegalStateException) {
        }
        worker?.join(2000)
        recorder?.release()
        audioRecord = null
        worker = null

        val file = outputFile ?: return null
        writeHeader(file, bytesWritten, sampleRate)
        val duration = bytesWritten * 1000L / (sampleRate * CHANNELS * BYTES_PER_SAMPLE)
        return RecordingResult(file, duration, sampleRate)
    }

    fun cancel() {
        val file = outputFile
        stop()
        file?.delete()
    }

    private fun createRecorder(): AudioRecord {
        for (rate in intArrayOf(16000, 48000, 44100)) {
            val minimum = AudioRecord.getMinBufferSize(
                rate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
            if (minimum <= 0) continue
            val candidate = AudioRecord.Builder()
                .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(rate)
                        .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                        .build(),
                )
                .setBufferSizeInBytes(maxOf(minimum * 2, 8192))
                .build()
            if (candidate.state == AudioRecord.STATE_INITIALIZED) {
                sampleRate = rate
                return candidate
            }
            candidate.release()
        }
        error("No supported microphone sample rate")
    }

    private fun writeHeader(file: File, dataSize: Long, rate: Int) {
        val byteRate = rate * CHANNELS * BYTES_PER_SAMPLE
        val blockAlign = CHANNELS * BYTES_PER_SAMPLE
        val header = ByteBuffer.allocate(WAV_HEADER_SIZE).order(ByteOrder.LITTLE_ENDIAN)
            .put("RIFF".toByteArray(Charsets.US_ASCII))
            .putInt((36L + dataSize).coerceAtMost(Int.MAX_VALUE.toLong()).toInt())
            .put("WAVE".toByteArray(Charsets.US_ASCII))
            .put("fmt ".toByteArray(Charsets.US_ASCII))
            .putInt(16)
            .putShort(1.toShort())
            .putShort(CHANNELS.toShort())
            .putInt(rate)
            .putInt(byteRate)
            .putShort(blockAlign.toShort())
            .putShort(16.toShort())
            .put("data".toByteArray(Charsets.US_ASCII))
            .putInt(dataSize.coerceAtMost(Int.MAX_VALUE.toLong()).toInt())
            .array()
        RandomAccessFile(file, "rw").use {
            it.seek(0)
            it.write(header)
        }
    }

    companion object {
        private const val WAV_HEADER_SIZE = 44
        private const val CHANNELS = 1
        private const val BYTES_PER_SAMPLE = 2
    }
}
