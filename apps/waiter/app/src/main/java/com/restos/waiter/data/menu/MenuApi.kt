package com.restos.waiter.data.menu

import com.restos.waiter.data.common.PagedEnvelope
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.http.GET
import retrofit2.http.Query

interface MenuApi {
    @GET("api/v1/menu/items/")
    suspend fun listItems(
        @Query("category") categoryId: Long? = null,
        @Query("is_available") isAvailable: Boolean? = true,
        @Query("page_size") pageSize: Int = 500,
    ): PagedEnvelope<MenuItemDto>

    @GET("api/v1/menu/categories/")
    suspend fun listCategories(): PagedEnvelope<CategoryDto>
}

@Serializable
data class MenuItemDto(
    val id: Long,
    val category: Long? = null,
    val name: String,
    val price: String,
    val emoji: String = "",
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("is_available") val isAvailable: Boolean = true,
    @SerialName("stop_reason") val stopReason: String? = null,
    val kind: String = "dish",
)

@Serializable
data class CategoryDto(
    val id: Long,
    val name: String,
    @SerialName("sort_order") val sortOrder: Int = 0,
)
