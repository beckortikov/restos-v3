package com.restos.waiter.data.net

import com.restos.waiter.data.auth.TokenStore
import dagger.Lazy
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.Serializable
import okhttp3.Authenticator
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.Route
import javax.inject.Inject
import javax.inject.Singleton

/**
 * На 401 пытается обновить access по refresh. При неуспехе — чистит токены,
 * UI увидит AuthStatus.LoggedOut и редиректнет на PIN-экран.
 *
 * OkHttpClient берётся лениво, чтобы избежать циклической зависимости
 * (клиенту нужен Authenticator, а Authenticator делает HTTP-вызов).
 */
@Singleton
class TokenAuthenticator @Inject constructor(
    private val tokenStore: TokenStore,
    private val clientProvider: Lazy<OkHttpClient>,
    private val json: kotlinx.serialization.json.Json,
    private val config: NetworkConfig,
) : Authenticator {

    override fun authenticate(route: Route?, response: Response): Request? {
        if (response.request.header(AuthInterceptor.SKIP_AUTH_HEADER) != null) return null
        if (responseCount(response) >= 2) return null

        val refresh = runBlocking { tokenStore.current()?.refresh } ?: return null

        val newAccess = runBlocking { tryRefresh(refresh) } ?: run {
            runBlocking { tokenStore.clear() }
            return null
        }
        runBlocking { tokenStore.updateAccess(newAccess) }
        return response.request.newBuilder()
            .header("Authorization", "Bearer $newAccess")
            .build()
    }

    private fun tryRefresh(refresh: String): String? {
        val payload = json.encodeToString(
            RefreshRequest.serializer(),
            RefreshRequest(refresh),
        )
        val request = Request.Builder()
            .url("${config.baseUrl}api/v1/auth/refresh/")
            .header(AuthInterceptor.SKIP_AUTH_HEADER, "1")
            .post(payload.toRequestBody(JSON))
            .build()
        return runCatching {
            clientProvider.get().newCall(request).execute().use { resp ->
                if (!resp.isSuccessful) return@use null
                val body = resp.body?.string() ?: return@use null
                val parsed = json.decodeFromString(RefreshResponse.serializer(), body)
                parsed.data?.access
            }
        }.getOrNull()
    }

    private fun responseCount(response: Response): Int {
        var count = 1
        var prior = response.priorResponse
        while (prior != null) {
            count++
            prior = prior.priorResponse
        }
        return count
    }

    private companion object {
        val JSON = "application/json; charset=utf-8".toMediaType()
    }
}

@Serializable
private data class RefreshRequest(val refresh: String)

@Serializable
private data class RefreshResponse(val data: RefreshData? = null)

@Serializable
private data class RefreshData(val access: String)

data class NetworkConfig(val baseUrl: String)
