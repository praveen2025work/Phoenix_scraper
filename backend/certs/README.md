# certs/

Drop your corporate **root CA certificate** here as `phoenix-ca.pem` (PEM format —
text starting with `-----BEGIN CERTIFICATE-----`) and the scraper trusts it
automatically when talking to Phoenix over HTTPS. No environment variables, no
extra installs.

- A bundle works too: concatenate several PEM blocks (root + intermediates) into
  the one file.
- Pickup is relative to the directory you run `pheonix` from (normally
  `backend/`, i.e. `backend/certs/phoenix-ca.pem`) — run `pheonix doctor` to
  confirm the bundle was found, or set `PHEONIX_CA_BUNDLE` to an absolute path
  in `.env`.
- How to obtain the certificate: see "HTTPS" in `backend/README.md`.

`*.pem` files in this directory are gitignored so a certificate never lands in
the public repo by accident. CA certificates contain no secret material (they
do reveal your company name), so if you *want* yours versioned:
`git add -f certs/phoenix-ca.pem`.
