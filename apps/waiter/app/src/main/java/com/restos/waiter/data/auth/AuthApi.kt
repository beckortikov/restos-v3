package com.restos.waiter.data.auth

import com.restos.waiter.data.net.AuthInterceptor
import kotlinx.serialization.Serializable
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST

interface AuthApi {

    @POST("api/v1/auth/waiter/pin/")
    suspend fun loginWithPin(
        @Body body: PinLoginRequest,
        @Header(AuthInterceptor.SKIP_AUTH_HEADER) skipAuth: String = "1",
    ): PinLoginEnvelope

    @GET("api/v1/auth/me/")
    suspend fun me(): MeEnvelope

    @POST("api/v1/auth/pin/logout/")
    suspend fun logout(): LogoutEnvelope
}

@Serializable
data class PinLoginRequest(val pin: String)

@Serializable
data class PinLoginEnvelope(val data: PinLoginData? = null)

@Serializable
data class PinLoginData(
    val access: String,
    val refresh: String,
    val user: UserDto,
)

@Serializable
data class MeEnvelope(val data: MeData? = null)

@Serializable
data class MeData(
    val user: UserDto,
    val restaurant: RestaurantDto? = null,
)

@Serializable
data class UserDto(
    val id: Long,
    val username: String,
    val full_name: String,
    val role: String,
    val permissions: List<String> = emptyList(),
) {
    val displayName: String get() = full_name.ifBlank { username }
}

@Serializable
data class RestaurantDto(
    val id: Long,
    val name: String,
)

@Serializable
data class LogoutEnvelope(val data: LogoutData? = null)

@Serializable
data class LogoutData(val ok: Boolean = false)
