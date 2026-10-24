# Playback download policy

The four clients automatically tune transport, with no new user controls:

- Start with two requests, increase gradually to at most four, and back off on
  failures or substantial throughput loss. Android reserves one slot for Media3.
- Use 4 MiB network segments, increasing to 8 MiB after healthy fast transfers.
  Disk storage remains in small blocks. Segment size is reduced for short files
  and small budgets.
- Reuse the final redirected URL and required media headers within a playback
  session. Concurrent expired requests share one resolution refresh, and each
  failed request is retried at most once. Temporary URLs are not persisted.
- Validate byte ranges, lengths and available entity validators. A server that
  does not support ranges retains ordinary transport. A server changing file
  identity after caching fails rather than mixing incompatible bytes.
- Prefer current playback data, deduplicate scheduled ranges, cancel obsolete
  speculative requests on seeks, and stop prefetch when the window is full.
  Existing cloud/device prefetch and disk budgets still apply. Exit removes the
  current video's cache and URL lease.
- Count only upstream bytes, using a monotonic three-second rolling window.
  Quiet gaps between bursts are averaged; a real stall becomes zero. The UI can
  distinguish waiting for data from reading an already populated cache.

Desktop sampling runs independently of MPV property reads; property polls are
single-flight with a timeout. iOS reuses completed HTTP/1.1 connections within the
playback session. Android decoder requests release cache-hole locks at segment
boundaries, allowing prefetch to fill later holes concurrently.

CI runs the local HTTP fixtures (redirects, expired links, concurrent requests,
range validation, fallback, capacity/eviction, seeks, shutdown and rate expiry),
Flutter checks, Android native tests, and builds all four clients. No local SDK
installation is required.

Real CDN improvement must be measured on the same file, fresh URL and headers,
using sequential runs with 1/2/4 connections. A larger number on the smoothed UI
is not evidence of higher average throughput; aggregate received bytes divided
by elapsed time is the comparison metric.
