package com.damirl.ray.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

// The LAN route: the probe sent the API key in clear to the LAN address on any Wi-Fi and trusted whatever answered;
// now only an answer to a nonce that needs the key (serve/server.py ray_lan_proof) makes the LAN the route, and a page
// is trusted only on the server's exact origins, the LAN one only while it is proven
class LanProofTest {

    private val key = "lan-proof-test-key"

    @Test
    fun theProofIsTheServersHmac() {
        // the same value serve/test_ray_lan_proof.py computes in Python for this key and nonce
        val nonce = "0123456789abcdef".repeat(2)
        val proof = NetworkClient.lanProof(key, nonce)
        assertEquals(64, proof.length)
        assertTrue(NetworkClient.proofMatches(key, nonce, """{"proof": "$proof"}"""))
    }

    @Test
    fun anotherHostCannotAnswer() {
        val nonce = NetworkClient.newNonce()
        assertEquals(32, nonce.length)
        assertFalse(NetworkClient.proofMatches(key, nonce, """{"proof": "${NetworkClient.lanProof("other", nonce)}"}"""))
        assertFalse(NetworkClient.proofMatches(key, nonce, """{"object": "list", "data": []}"""))   // a plain /v1/models
        assertFalse(NetworkClient.proofMatches(key, nonce, "<html>"))
        assertFalse(NetworkClient.proofMatches("", nonce, """{"proof": "${NetworkClient.lanProof("", nonce)}"}"""))
    }

    @Test
    fun aServerWithSeveralKeysIsProvenByAnyOfThem() {
        val nonce = NetworkClient.newNonce()
        val body = """{"proof": "${NetworkClient.lanProof("k-one", nonce)}", "proofs": ["${NetworkClient.lanProof("k-one", nonce)}", "${NetworkClient.lanProof(key, nonce)}"]}"""
        assertTrue(NetworkClient.proofMatches(key, nonce, body))
        assertFalse(NetworkClient.proofMatches("k-three", nonce, body))
    }

    @Test
    fun onlyTheExactOriginsAreTrusted() {
        val lan = StrataOrigins.originFor("http://192.168.1.10:8080")
        val remote = StrataOrigins.originFor("https://ray.example.org")
        assertTrue(StrataOrigins.isTrusted("https://ray.example.org/web/x.js", lan, remote, lanOk = false))
        assertTrue(StrataOrigins.isTrusted("https://ray.example.org:443/", lan, remote, lanOk = false))
        assertTrue(StrataOrigins.isTrusted("http://192.168.1.10:8080/", lan, remote, lanOk = true))
        assertFalse("the LAN page before a proof", StrataOrigins.isTrusted("http://192.168.1.10:8080/", lan, remote, lanOk = false))
        assertFalse("another port on the same PC", StrataOrigins.isTrusted("http://192.168.1.10:5173/", lan, remote, lanOk = true))
        assertFalse("http to the remote host", StrataOrigins.isTrusted("http://ray.example.org/", lan, remote, lanOk = true))
        assertFalse(StrataOrigins.isTrusted("https://evil.example/", lan, remote, lanOk = true))
    }
}
