# app

### Security

- **Host keys fail closed.** `SshRepository.PinningHostKeyVerifier` pins type + SHA-256 fingerprint. Never auto-accept.