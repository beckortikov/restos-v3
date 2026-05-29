package com.restos.waiter.data.orders

import com.restos.waiter.data.common.PagedEnvelope
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.http.GET
import retrofit2.http.Query

interface CancelReasonsApi {
    /** kind = "item" | "order" | "refund" — фильтр по типу отмены. */
    @GET("api/v1/cancel_reasons/")
    suspend fun list(
        @Query("kind") kind: String? = null,
        @Query("is_active") isActive: Boolean? = true,
    ): PagedEnvelope<CancelReasonDto>
}

@Serializable
data class CancelReasonDto(
    val id: Long,
    val kind: String,
    val label: String,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("is_active") val isActive: Boolean = true,
)
