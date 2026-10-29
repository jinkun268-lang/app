package com.example.citruscollect.data

import com.example.citruscollect.network.AuthExpiredException
import com.example.citruscollect.network.Backend
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.test.runCurrent
import org.junit.Assert.*
import org.junit.Test

class AccountBoundaryTest {
    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    @Test fun rotatingTokensDoesNotRestartAccountObservers() = kotlinx.coroutines.test.runTest {
        val store = FakeSessionStore()
        store.saveLogin("http://localhost:18080/api/v1/", "alice", "collector", "a1", "r1", 100)
        val repository = AuthRepository(Backend(), store)
        val identities = mutableListOf<String?>()
        backgroundScope.launch(kotlinx.coroutines.test.UnconfinedTestDispatcher(testScheduler)) { repository.ownerKey.collect { identities.add(it) } }
        runCurrent()
        store.saveTokens("a2", "r2", 100)
        runCurrent()
        assertEquals(1, identities.size)
        store.clear()
        runCurrent()
        assertEquals(2, identities.size)
        assertNull(identities.last())
    }

    @Test fun accountIdentityIncludesServerAndUserAndIgnoresTrailingSlash() {
        assertEquals(AuthRepository.accountKey("https://example.test/api/v1", "alice"), AuthRepository.accountKey("https://example.test/api/v1/", "alice"))
        assertNotEquals(AuthRepository.accountKey("https://example.test/api/v1", "alice"), AuthRepository.accountKey("https://other.test/api/v1", "alice"))
        assertNotEquals(AuthRepository.accountKey("https://example.test/api/v1", "alice"), AuthRepository.accountKey("https://example.test/api/v1", "bob"))
    }
    @Test fun queuedOwnerNeverReceivesDifferentAccountCredentials() = runBlocking {
        val store = FakeSessionStore()
        store.saveLogin("http://localhost:18080/api/v1/", "bob", "collector", "bob-access", "bob-refresh", 100)
        val repository = AuthRepository(Backend(), store)
        var invoked = false
        try {
            repository.authorizedFor(AuthRepository.accountKey("http://localhost:18080/api/v1/", "alice")) { _, _ -> invoked = true }
            fail("different account must be rejected")
        } catch (_: AuthExpiredException) { }
        assertFalse(invoked)
        assertEquals(AuthRepository.accountKey("http://localhost:18080/api/v1/", "bob"), repository.currentOwnerKey())
        store.clear()
        assertNull(repository.currentOwnerKey())
        assertNull(repository.ownerKey.first())
    }
}
