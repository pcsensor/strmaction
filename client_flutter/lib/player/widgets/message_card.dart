import 'dart:async';

import 'package:flutter/material.dart';

class MessageCard extends StatefulWidget {
  final bool visible;
  final String title;
  final String description;
  final String? primary;
  final String? secondary;
  final int? countdown;
  final VoidCallback? onPrimary;
  final VoidCallback? onSecondary;
  final VoidCallback? onCopyLink;
  final VoidCallback? onDismiss;

  const MessageCard({
    super.key,
    required this.visible,
    required this.title,
    required this.description,
    required this.primary,
    required this.secondary,
    required this.countdown,
    required this.onPrimary,
    required this.onSecondary,
    this.onCopyLink,
    this.onDismiss,
  });

  @override
  State<MessageCard> createState() => _MessageCardState();
}

class _MessageCardState extends State<MessageCard> {
  Timer? _timer;
  int _remaining = 0;

  @override
  void initState() {
    super.initState();
    _resetCountdown();
  }

  @override
  void didUpdateWidget(covariant MessageCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.countdown != widget.countdown ||
        oldWidget.primary != widget.primary ||
        oldWidget.visible != widget.visible) {
      _resetCountdown();
    }
  }

  void _resetCountdown() {
    _timer?.cancel();
    _timer = null;
    _remaining = widget.countdown ?? 0;
    if (widget.visible && _remaining > 0) {
      _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
        if (!mounted) return;
        setState(() {
          _remaining -= 1;
        });
        if (_remaining <= 0) {
          timer.cancel();
          widget.onPrimary?.call();
        }
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final primaryText = widget.primary == null
        ? null
        : (_remaining > 0 ? '${widget.primary} ($_remaining)' : widget.primary);
    return IgnorePointer(
      ignoring: !widget.visible,
      child: AnimatedOpacity(
        opacity: widget.visible ? 1 : 0,
        duration: const Duration(milliseconds: 180),
        child: ColoredBox(
          color: const Color(0x66000000),
          child: Center(
            child: Container(
              width: 420,
              margin: const EdgeInsets.all(40),
              padding: const EdgeInsets.fromLTRB(28, 24, 28, 22),
              decoration: BoxDecoration(
                color: const Color(0xF00C0F14),
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: const Color(0x1FFFFFFF)),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(children: [
                    if (widget.onDismiss != null) const SizedBox(width: 40),
                    Expanded(child: Text(
                    widget.title,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 19,
                      fontWeight: FontWeight.bold,
                    ),
                    )),
                    if (widget.onDismiss != null) IconButton(
                      tooltip: '关闭提示',
                      onPressed: widget.onDismiss,
                      icon: const Icon(Icons.close, color: Colors.white70),
                      constraints: const BoxConstraints.tightFor(width: 40, height: 40),
                      padding: EdgeInsets.zero,
                    ),
                  ]),
                  if (widget.description.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Text(
                      widget.description,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: Color(0xFFA9B0BE),
                        fontSize: 12.5,
                        height: 1.5,
                      ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  Wrap(
                    alignment: WrapAlignment.center,
                    spacing: 10,
                    runSpacing: 8,
                    children: [
                      if (primaryText != null)
                        FilledButton(
                          style: FilledButton.styleFrom(
                            backgroundColor: const Color(0xFFF0A94D),
                            foregroundColor: const Color(0xFF17120B),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                            padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 10),
                          ),
                          onPressed: widget.onPrimary,
                          child: Text(
                            primaryText,
                            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold),
                          ),
                        ),
                      if (widget.secondary != null)
                        OutlinedButton(
                          style: OutlinedButton.styleFrom(
                            foregroundColor: const Color(0xFFE8EAEF),
                            side: const BorderSide(color: Color(0x29FFFFFF)),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                            padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 10),
                          ),
                          onPressed: widget.onSecondary,
                          child: Text(widget.secondary!, style: const TextStyle(fontSize: 14)),
                        ),
                      if (widget.onCopyLink != null) TextButton(onPressed: widget.onCopyLink, child: const Text('复制链接')),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
