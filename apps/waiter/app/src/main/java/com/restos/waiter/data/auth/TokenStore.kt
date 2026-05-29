package com.restos.waiter.data.auth

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.tokenDataStore by preferencesDataStore(name = "auth")

private object Keys {
    val ACCESS = stringPreferencesKey("access_token")
    val REFRESH = stringPreferencesKey("refresh_token")
}

data class Tokens(val access: String, val refresh: String)

@Singleton
class TokenStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    val tokensFlow: Flow<Tokens?> = context.tokenDataStore.data.map { prefs ->
        val access = prefs[Keys.ACCESS]
        val refresh = prefs[Keys.REFRESH]
        if (access.isNullOrBlank() || refresh.isNullOrBlank()) null
        else Tokens(access, refresh)
    }

    suspend fun current(): Tokens? = tokensFlow.first()

    suspend fun save(tokens: Tokens) {
        context.tokenDataStore.edit { prefs ->
            prefs[Keys.ACCESS] = tokens.access
            prefs[Keys.REFRESH] = tokens.refresh
        }
    }

    suspend fun updateAccess(access: String) {
        context.tokenDataStore.edit { prefs ->
            prefs[Keys.ACCESS] = access
        }
    }

    suspend fun clear() {
        context.tokenDataStore.edit { it.clear() }
    }
}
