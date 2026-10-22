import 'package:flutter/material.dart';

class ErrorPage extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  final VoidCallback onSettings;

  const ErrorPage({
    super.key,
    required this.message,
    required this.onRetry,
    required this.onSettings,
  });

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: const Color(0xFF0B0E13),
      child: Center(
        child: Container(
          width: 460,
          margin: const EdgeInsets.all(32),
          padding: const EdgeInsets.fromLTRB(28, 26, 28, 24),
          decoration: BoxDecoration(
            color: const Color(0xF20C0F14),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: const Color(0x1FFFFFFF)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off_rounded, color: Color(0xFFF0A94D), size: 42),
              const SizedBox(height: 14),
              const Text(
                '无法连接 StrmAction 服务器',
                style: TextStyle(color: Colors.white, fontSize: 19, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 10),
              Text(
                message.isEmpty ? '请检查服务器地址与网络。' : message,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Color(0xFFA9B0BE), fontSize: 12.5, height: 1.5),
              ),
              const SizedBox(height: 20),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: const Color(0xFFF0A94D),
                      foregroundColor: const Color(0xFF17120B),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 11),
                    ),
                    onPressed: onRetry,
                    child: const Text('重试', style: TextStyle(fontWeight: FontWeight.bold)),
                  ),
                  const SizedBox(width: 12),
                  OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: const Color(0xFFE8EAEF),
                      side: const BorderSide(color: Color(0x29FFFFFF)),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 11),
                    ),
                    onPressed: onSettings,
                    child: const Text('设置'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
