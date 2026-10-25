These are public test fixtures for loopback-only CI TLS tests. The server key is
intentionally committed, has no production use, and is signed only by the test CA.

The localhost server certificate uses a one-year validity period (through
2027-10-24). macOS rejects the previous ten-year server certificate even when
its issuing CA is supplied explicitly. Regenerate the fixture before expiry;
keep the CA signing key out of the repository.
