# Playback download policy

The four clients automatically tune transport, with no new user controls:

- Android and iOS start with two requests, increase gradually to at most four,
  and back off on failures or substantial throughput loss without reducing the
  policy below two. Android reserves one slot for Media3. Actual active requests
  can be fewer when the cache window is full, no eligible data remains, or
  prefetch is disabled. Windows and macOS instead keep one sequential stream
  (see below): cloud-drive CDNs take 5–15s to establish a new connection, so
  parallel range requests cost far more than they gain.
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

## Playback gaps and slow segments (2.0.5)

The decoder's requested byte range takes priority over speculative work. The
time-to-byte conversion is used only to bound the prefetch window and display
cache ranges; it does not identify the urgent missing bytes. Out-of-order
completion remains supported and successful later ranges are retained.
All four platforms yield distant speculative work when actual playable buffer
ahead drops below ten seconds, before a full rebuffer is required.

- **Android / TV:** separate playback and prefetch HTTP/cache factories. Playback
  reads never block on a speculative cache-hole lock. They cancel overlapping
  prefetch calls and use a three-second connect/read timeout, with at most two
  consecutive recovery attempts from the last byte actually delivered. Cache
  writers close on their owning worker and commit 2 MiB fragments. Buffering
  retains the nearest speculative worker and yields the other workers; it does
  not change the user's play/pause intent or switch to whole-file transport.
- **Windows / macOS:** a single sequential origin stream plus at most two short
  probes (4 MiB each, head and tail). The stream starts at the playhead, reads to
  EOF, publishes each received chunk into the bounded disk store and pauses when
  it is `prefetch` bytes ahead; advancing the playhead resumes the same
  connection instead of opening another one. Cached reads never touch the
  origin. Only the first and last 4 MiB use a probe; every other miss restarts
  the main stream, because a sequential read served by 4 MiB probes would open a
  new CDN connection per block. Explicit seeks only update the playhead; a stale
  local response is stopped by its generation, but it is closed rather than
  detached once headers are committed — `detachSocket()` throws
  `Bad state: Headers already sent` there and used to leave the client waiting
  for its network timeout. A connection attempt is never cancelled: Dart's
  HttpClient cannot abort a queued `getUrl`, so the only safe action is to let
  it finish. Timeouts are 25s for connect/headers and 12s without body bytes; a
  restart resumes after the last written byte, so failed attempts cannot leave
  holes. The local decoder's `network-timeout` is 30s to cover one full connect
  attempt. See [the transport redesign](desktop-playback-transport-redesign.md).
- **iOS:** serve an available cached prefix before waiting on its owner; each
  speculative data callback wakes waiting readers. A missing range promotes its
  existing request, reduces speculative competition, and receives the same bounded
  stall recovery. Retried and preempted requests resume after received bytes,
  validate the new response, and deliver response headers only once. Deliberate
  local backpressure is excluded from the stall watchdog.

Transport segments remain 4–8 MiB. Recovery requests may be smaller because they
fetch a missing suffix. Every attempt shares the connection and capacity limits,
signed URL lease and file-identity checks. Seeks and shutdown cancel obsolete
work. Regression fixtures cover a withheld head with successful later segments,
partial-prefix delivery, exact-offset recovery, retry bounds, cancellation races
and a minimum two-request policy. Device/CDN playback remains a separate check.

CI runs the local HTTP fixtures (redirects, expired links, concurrent requests,
range validation, fallback, capacity/eviction, seeks, shutdown and rate expiry),
Flutter checks, Android native tests, and builds all four clients. No local SDK
installation is required.

Real CDN improvement must be measured on the same file, fresh URL and headers,
using sequential runs with 1/2/4 connections. A larger number on the smoothed UI
is not evidence of higher average throughput; aggregate received bytes divided
by elapsed time is the comparison metric.
