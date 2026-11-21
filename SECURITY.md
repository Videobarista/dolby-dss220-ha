# Security Policy

## Supported versions

Only the most recent release receives fixes.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting (Security -> Report a
vulnerability) rather than opening a public issue.

## Scope

This integration runs inside Home Assistant on a local network and talks to a
Dolby DSS200/DSS220 cinema server through the SMI web services the server
itself exposes: SOAP over plain HTTP on TCP port 8080, without a password and
without encryption. It has no cloud component, stores no credentials, opens no
ports of its own and never logs in to the web interface of the server. Its one
Python requirement is `defusedxml`, used to parse the server's answers safely.

Treat the cinema network as trusted: anyone who can reach port 8080 can start,
stop and select shows, with or without this integration. See
[Network security](README.md#network-security) for a firewall setup.

### What the integration guards against

- Control is off by default. Until "Allow control" is switched on in the
  integration options, the integration only reads; every command is refused,
  also when it is called from an automation or script.
- Input typed into Home Assistant is validated before use: the host must be a
  plain host name or IP address and the port a valid port number. Every value
  sent to the server is checked against the values the server's own schema
  allows (show IDs must be `urn:uuid:` identifiers, inputs and schedule modes
  come from a fixed list, the volume must lie between 0 and 10) and is
  XML-escaped.
- Answers from the server are treated as untrusted: at most 4 MB is read per
  answer, XML is parsed with `defusedxml` (no DTDs, no entity expansion, no
  external entities), redirects are not followed, every request has a time
  limit and unexpected HTTP status codes are refused.
- The server is not flooded: one request at a time, the playback state every
  5 seconds, slower values every 30 seconds or 5 minutes, clip names are
  cached and an unreachable server is tried once per polling interval.
- Diagnostics leave out the IP address and the identifiers of the server and
  its components.
