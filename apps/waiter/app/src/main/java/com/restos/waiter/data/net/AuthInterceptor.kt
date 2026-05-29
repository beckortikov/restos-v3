package com.restos.waiter.data.net

import com.restos.waiter.data.auth.TokenStore
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Подкладывает Authorization: Bearer <access> ко всем запросам, если токен есть.
 * Эндпоинты /auth/waiter/pin/ и /auth/refresh/ должны помечаться заголовком
 * `X-Skip-Auth: 1`, чтобы не зацикливаться на рефреше.
 */
@Singleton
class AuthInterceptor @Inject constructor(
    private val tokenStore: TokenStore,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        if (request.header(SKIP_AUTH_HEADER) != null) {
            val cleaned = request.newBuilder().removeHeader(SKIP_AUTH_HEADER).build()
            return chain.proceed(cleaned)
        }
        val tokens = runBlocking { tokenStore.current() }
        val withAuth = if (tokens != null) {
            request.newBuilder()
                .header("Authorization", "Bearer ${tokens.access}")
                .build()
        } else {
            request
        }
        return chain.proceed(withAuth)
    }

    companion object {
        const val SKIP_AUTH_HEADER = "X-Skip-Auth"
    }
}
