package com.restos.waiter.data.net

import kotlinx.serialization.Serializable

/**
 * Django backend всегда отвечает обёрткой:
 *   { "data": <payload> }                     — успех
 *   { "error": { "code", "message", "detail" } } — ошибка
 * См. prd-v3/01-API-CONTRACT.md.
 */
@Serializable
data class Envelope<T>(
    val data: T? = null,
    val error: ApiError? = null,
)

@Serializable
data class ApiError(
    val code: String,
    val message: String,
    val detail: String? = null,
)

class ApiException(val apiError: ApiError) : RuntimeException(apiError.message)
