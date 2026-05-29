package com.restos.waiter.data.tables

import com.restos.waiter.data.common.PagedEnvelope
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.http.GET

interface TablesApi {
    @GET("api/v1/tables/")
    suspend fun listTables(): PagedEnvelope<TableDto>

    @GET("api/v1/tables/zones/")
    suspend fun listZones(): PagedEnvelope<ZoneDto>
}

@Serializable
data class ZoneDto(
    val id: Long,
    val name: String,
    @SerialName("sort_order") val sortOrder: Int = 0,
)

@Serializable
data class TableDto(
    val id: Long,
    val number: Int,
    val name: String,
    val capacity: Int = 0,
    val zone: Long? = null,
    @SerialName("zone_name") val zoneName: String? = null,
    val status: String,
    @SerialName("status_display") val statusDisplay: String? = null,
    val waiter: Long? = null,
    @SerialName("waiter_name") val waiterName: String? = null,
    @SerialName("current_order") val currentOrderId: Long? = null,
    @SerialName("guests_count") val guestsCount: Int = 0,
    @SerialName("opened_at") val openedAt: String? = null,
)
