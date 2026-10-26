package com.example.citruscollect

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.example.citruscollect.data.AppDatabase
import com.example.citruscollect.data.AuthRepository
import com.example.citruscollect.data.DataStoreSessionStore
import com.example.citruscollect.data.repository.SampleRepository
import com.example.citruscollect.network.Backend
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** 手动组装依赖（未引入 DI 框架）。 */
class AppContainer(app: Application) {
    // 相机回调等需要在组合销毁后仍能落库的 IO 作用域。
    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val db = AppDatabase.get(app)
    val sessionStore = DataStoreSessionStore(app)
    val backend = Backend()
    val authRepository = AuthRepository(backend, sessionStore)
    val repository = SampleRepository(db.sampleDao(), db.imageDao(), backend, authRepository)

    /**
     * 当前采集批次（仅本地）：承载地点、日期、采集人和默认品种。
     * 为空时图片记录页显示“历史记录”，采集页会提示先建批次。
     */
    var batchId by mutableStateOf<String?>(null)

    init {
        // 启动时恢复持久化的服务地址；恢复与登录提交在仓库内互斥，
        // 用户先登录新地址时不被旧持久地址覆盖。authorized 首次请求前
        // 也会幂等待恢复完成（无需阻塞主线程）。
        appScope.launch {
            repository.cleanupAbandonedEmptyDrafts()
            if (batchId == null) batchId = repository.latestBatch()?.batchId
            authRepository.restorePersistedBaseUrl()
        }
    }
}

class CitrusApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
