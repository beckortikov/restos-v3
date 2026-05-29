package com.restos.waiter.data.config

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.serverConfigDataStore by preferencesDataStore(name = "server_config")
private val KEY_BASE_URL = stringPreferencesKey("base_url")

/**
 * Хранит base URL Django-бэкенда, к которому привязан планшет. Задаётся при
 * первичном онбординге (сканирование QR с кассы или ручной ввод). Меняется
 * только через «Сменить ресторан» в профиле.
 *
 * Возвращает URL ВСЕГДА со слэшем в конце (нормализуем при записи).
 */
@Singleton
class ServerConfigStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    val baseUrlFlow: Flow<String?> = context.serverConfigDataStore.data.map { prefs ->
        prefs[KEY_BASE_URL]?.takeIf { it.isNotBlank() }
    }

    suspend fun current(): String? = baseUrlFlow.first()

    suspend fun save(rawUrl: String) {
        val normalized = normalize(rawUrl)
        context.serverConfigDataStore.edit { it[KEY_BASE_URL] = normalized }
    }

    suspend fun clear() {
        context.serverConfigDataStore.edit { it.remove(KEY_BASE_URL) }
    }

    companion object {
        /** http://host[:port][/path]/ — обязательно со слэшем в конце. */
        fun normalize(raw: String): String {
            var u = raw.trim()
            if (!u.startsWith("http://") && !u.startsWith("https://")) {
                u = "http://$u"
            }
            if (!u.endsWith("/")) u += "/"
            return u
        }

        fun isValid(raw: String): Boolean {
            val trimmed = raw.trim()
            if (trimmed.isBlank()) return false
            return runCatching {
                val normalized = normalize(trimmed)
                val url = java.net.URI(normalized)
                url.host?.isNotBlank() == true && url.scheme in setOf("http", "https")
            }.getOrDefault(false)
        }
    }
}
