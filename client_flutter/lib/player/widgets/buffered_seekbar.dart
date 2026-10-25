import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../playback_engine.dart';

String formatTime(double seconds) {
  final total = seconds < 0 ? 0 : seconds.toInt();
  final hours = total ~/ 3600;
  final minutes = (total % 3600) ~/ 60;
  final secs = total % 60;
  if (hours > 0) {
    return '${hours.toString().padLeft(2, '0')}:'
        '${minutes.toString().padLeft(2, '0')}:'
        '${secs.toString().padLeft(2, '0')}';
  }
  return '${minutes.toString().padLeft(2, '0')}:'
      '${secs.toString().padLeft(2, '0')}';
}

class BufferedSeekBar extends StatefulWidget {
  final double position;
  final double duration;
  final List<BufferedRange> bufferedRanges;
  final ValueChanged<double> onSeek;
  final ValueChanged<bool>? onSeekingChanged;

  /// The drag or pending seek target; null resumes the playback position.
  final ValueChanged<double?>? onPreviewChanged;

  const BufferedSeekBar({
    super.key,
    required this.position,
    required this.duration,
    required this.bufferedRanges,
    required this.onSeek,
    this.onSeekingChanged,
    this.onPreviewChanged,
  });

  @override
  State<BufferedSeekBar> createState() => _BufferedSeekBarState();
}

class _BufferedSeekBarState extends State<BufferedSeekBar> {
  bool _dragging = false;
  bool _inDrag = false;
  double _dragPosition = 0;
  double? _pendingPosition;
  Timer? _pendingTimer;
  double? _hoverX;
  double _lastX = 0;

  static const double _headWidth = 3.5;
  static const double _headHalf = _headWidth / 2;
  static const double _edge = 10;

  double _left(double width) => _edge + _headHalf;

  double _right(double width) => width - _edge - _headHalf;

  double _xToSeconds(double x, double width) {
    final left = _left(width);
    final right = _right(width);
    if (right <= left || widget.duration <= 0) return 0;
    final ratio = ((x - left) / (right - left)).clamp(0.0, 1.0);
    return ratio * widget.duration;
  }

  void _begin(double x, double width) {
    _lastX = x;
    _pendingTimer?.cancel();
    _pendingPosition = null;
    final wasDragging = _dragging;
    final target = _xToSeconds(x, width);
    setState(() {
      _dragging = true;
      _dragPosition = target;
    });
    widget.onPreviewChanged?.call(target);
    if (!wasDragging) {
      widget.onSeekingChanged?.call(true);
    }
  }

  void _update(double x, double width) {
    if (!_dragging) return;
    _lastX = x;
    setState(() => _dragPosition = _xToSeconds(x, width));
    widget.onPreviewChanged?.call(_dragPosition);
  }

  void _end(double x, double width) {
    if (!_dragging) return;
    final target = _xToSeconds(x, width);
    _pendingTimer?.cancel();
    _pendingPosition = target;
    setState(() {
      _dragging = false;
      _dragPosition = target;
    });
    widget.onPreviewChanged?.call(target);
    widget.onSeekingChanged?.call(false);
    widget.onSeek(target);

    _pendingTimer = Timer(const Duration(milliseconds: 1500), () {
      if (mounted && _pendingPosition != null) {
        setState(() => _pendingPosition = null);
        widget.onPreviewChanged?.call(null);
      }
    });
  }

  @override
  void didUpdateWidget(covariant BufferedSeekBar oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_pendingPosition != null) {
      if ((widget.position - _pendingPosition!).abs() < 0.8) {
        _pendingTimer?.cancel();
        _pendingPosition = null;
        // The parent may render the preview outside this bar. Notify it after
        // this build so it can safely update its own state.
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted && !_dragging && _pendingPosition == null) {
            widget.onPreviewChanged?.call(null);
          }
        });
      }
    }
  }

  @override
  void dispose() {
    _pendingTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final shown = _dragging ? _dragPosition : (_pendingPosition ?? widget.position);
        return MouseRegion(
          cursor: SystemMouseCursors.click,
          onHover: (event) => setState(() => _hoverX = event.localPosition.dx),
          onExit: (_) => setState(() => _hoverX = null),
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapDown: (details) => _begin(details.localPosition.dx, width),
            onTapUp: (details) => _end(details.localPosition.dx, width),
            onTapCancel: () {
              scheduleMicrotask(() {
                if (mounted && !_inDrag && _dragging) {
                  _pendingTimer?.cancel();
                  _pendingPosition = null;
                  setState(() => _dragging = false);
                  widget.onPreviewChanged?.call(null);
                  widget.onSeekingChanged?.call(false);
                }
              });
            },
            onHorizontalDragStart: (details) {
              _inDrag = true;
              _begin(details.localPosition.dx, width);
            },
            onHorizontalDragUpdate: (details) =>
                _update(details.localPosition.dx, width),
            onHorizontalDragEnd: (details) {
              _inDrag = false;
              _end(_lastX, width);
            },
            onHorizontalDragCancel: () {
              _inDrag = false;
              if (_dragging) {
                _pendingTimer?.cancel();
                _pendingPosition = null;
                setState(() => _dragging = false);
                widget.onPreviewChanged?.call(null);
                widget.onSeekingChanged?.call(false);
              }
            },
            child: SizedBox(
              height: 32,
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Positioned.fill(
                    child: CustomPaint(
                      painter: _SeekBarPainter(
                        position: shown,
                        duration: widget.duration,
                        bufferedRanges: mergeBufferedRanges(widget.bufferedRanges),
                        left: _left(width),
                        right: _right(width),
                      ),
                    ),
                  ),
                  if (_hoverX != null && widget.duration > 0)
                    Positioned(
                      left: (_hoverX! - 30).clamp(0.0, math.max(0.0, width - 60)),
                      top: -28,
                      child: IgnorePointer(
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: const Color(0xCC000000),
                            borderRadius: BorderRadius.circular(6),
                            border: Border.all(color: const Color(0x33FFFFFF)),
                          ),
                          child: Text(
                            formatTime(_xToSeconds(_hoverX!, width)),
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _SeekBarPainter extends CustomPainter {
  final double position;
  final double duration;
  final List<BufferedRange> bufferedRanges;
  final double left;
  final double right;

  const _SeekBarPainter({
    required this.position,
    required this.duration,
    required this.bufferedRanges,
    required this.left,
    required this.right,
  });

  @override
  void paint(Canvas canvas, Size size) {
    if (size.width <= 0 || size.height <= 0 || right <= left) return;
    final centerY = size.height / 2;
    const trackHeight = 8.0;
    const radius = trackHeight / 2;
    const lineHeight = 2.5;

    final trackPaint = Paint()..color = const Color(0x3DFFFFFF);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(left, centerY - radius, right - left, trackHeight),
        const Radius.circular(radius),
      ),
      trackPaint,
    );

    double xFor(double seconds) {
      if (duration <= 0) return left;
      final ratio = (seconds / duration).clamp(0.0, 1.0);
      return left + ratio * (right - left);
    }

    final headX = xFor(position);
    if (headX > left) {
      final playedPaint = Paint()..color = const Color(0xFFF0A94D);
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(left, centerY - radius, headX - left, trackHeight),
          const Radius.circular(radius),
        ),
        playedPaint,
      );
    }

    final bufferedPaint = Paint()..color = const Color(0xE8FFFFFF);
    for (final range in bufferedRanges) {
      if (range.end <= range.start) continue;
      final x1 = xFor(range.start);
      final x2 = xFor(range.end);
      if (x2 <= x1) continue;
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(x1, centerY - lineHeight / 2, x2 - x1, lineHeight),
          const Radius.circular(1),
        ),
        bufferedPaint,
      );
    }

    final headPaint = Paint()..color = Colors.white;
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(headX - 1.75, centerY - 8, 3.5, 16),
        const Radius.circular(1.75),
      ),
      headPaint,
    );
  }

  @override
  bool shouldRepaint(covariant _SeekBarPainter oldDelegate) {
    return oldDelegate.position != position ||
        oldDelegate.duration != duration ||
        oldDelegate.left != left ||
        oldDelegate.right != right ||
        !areBufferedRangesEqual(oldDelegate.bufferedRanges, bufferedRanges);
  }
}
