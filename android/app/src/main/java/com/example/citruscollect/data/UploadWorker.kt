package com.example.citruscollect.data

import android.content.Context
import androidx.work.*
import com.example.citruscollect.CitrusApplication
import com.example.citruscollect.network.AuthExpiredException
import com.example.citruscollect.network.UploadException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException
import java.io.IOException
import java.util.concurrent.TimeUnit

/** 每个任务绑定采集账号；重新登录同一账号时从 Room 恢复，绝不借用新账号凭据。 */
class UploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as CitrusApplication
        val id = inputData.getString("sample") ?: return Result.failure()
        val owner = inputData.getString("owner") ?: return Result.failure()
        if (app.container.authRepository.currentOwnerKey() != owner) return Result.retry()
        return try {
            app.container.repository.upload(id)
            Result.success()
        } catch (e: CancellationException) { throw e
        } catch (e: Exception) {
            if (e is AuthExpiredException || app.container.authRepository.currentOwnerKey() != owner) {
                app.container.repository.queueState(id, owner, "queued")
                return Result.retry()
            }
            var cause: Throwable? = e
            var transient = false
            while (cause != null) {
                if (cause is IOException || (cause is HttpException && (cause.code() == 429 || cause.code() >= 500))) transient = true
                cause = cause.cause
            }
            if (transient) {
                app.container.repository.queueState(id, owner, "retrying")
                Result.retry()
            } else {
                app.container.repository.queueState(id, owner, "failed")
                Result.failure()
            }
        }
    }
    companion object {
        fun enqueue(context: Context, sampleId: String, owner: String, restart: Boolean = false) {
            val request = OneTimeWorkRequestBuilder<UploadWorker>()
                .setInputData(workDataOf("sample" to sampleId, "owner" to owner))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .addTag("collection-upload")
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork("upload:$owner:$sampleId", if (restart) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP, request)
        }
    }
}
