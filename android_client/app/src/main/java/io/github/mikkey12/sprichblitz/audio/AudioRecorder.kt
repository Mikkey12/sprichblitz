package io.github.mikkey12.sprichblitz.audio

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File

/**
 * Records mic audio to an app-private `.m4a` (AAC in an MPEG-4 container) inside
 * cacheDir. Privacy: the file lives only in the app sandbox and the caller MUST
 * delete it in a `finally` right after upload — see the note in README.md.
 *
 * 16 kHz mono keeps the file tiny (well under the 25 MB / 60 s backend limit);
 * the 59 s hard stop is enforced by the caller's timer, not here.
 */
class AudioRecorder(context: Context) {

    private val appContext = context.applicationContext
    private var recorder: MediaRecorder? = null
    private var outputFile: File? = null

    init {
        // Best effort after a process crash/forced stop: recordings are never
        // meant to survive the app process.
        appContext.cacheDir.listFiles()
            ?.filter { it.isFile && it.name.startsWith("rec_") && it.name.endsWith(".m4a") }
            ?.forEach { it.delete() }
    }

    val isRecording: Boolean get() = recorder != null

    /** Begin recording. Throws on failure (mic busy, permission missing, …). */
    fun start() {
        check(recorder == null) { "already recording" }
        val file = File.createTempFile("rec_", ".m4a", appContext.cacheDir)
        val rec = newRecorder()
        try {
            rec.apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioChannels(1)
                setAudioSamplingRate(16_000)
                setAudioEncodingBitRate(64_000)
                setOutputFile(file.absolutePath)
                prepare()
                start()
            }
        } catch (e: Exception) {
            rec.release()
            file.delete()
            throw e
        }
        recorder = rec
        outputFile = file
    }

    /**
     * Stop and return the recorded file, or null if the recording was too short
     * / invalid (MediaRecorder.stop throws for near-empty captures). On failure
     * the partial file is deleted immediately.
     */
    fun stop(): File? {
        val rec = recorder ?: return null
        val file = outputFile
        recorder = null
        outputFile = null
        return try {
            rec.stop()
            file
        } catch (_: RuntimeException) {
            file?.delete()
            null
        } finally {
            rec.release()
        }
    }

    /** Abort recording and delete any partial file (e.g. on cancel / error). */
    fun cancel() {
        val rec = recorder ?: return
        recorder = null
        val file = outputFile
        outputFile = null
        try {
            rec.stop()
        } catch (_: RuntimeException) {
            // partial capture — nothing to keep
        } finally {
            rec.release()
            file?.delete()
        }
    }

    @Suppress("DEPRECATION")
    private fun newRecorder(): MediaRecorder =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) MediaRecorder(appContext)
        else MediaRecorder()
}
