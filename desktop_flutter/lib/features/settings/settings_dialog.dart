import 'package:flutter/material.dart';

import '../../core/config.dart';

class SettingsDialog extends StatefulWidget {
  final AppConfig initial;
  final bool allowCancel;

  const SettingsDialog({
    super.key,
    required this.initial,
    required this.allowCancel,
  });

  @override
  State<SettingsDialog> createState() => _SettingsDialogState();
}

class _SettingsDialogState extends State<SettingsDialog> {
  late final TextEditingController _server;
  late final TextEditingController _cache;
  late bool _allowSelfSigned;
  String? _error;

  @override
  void initState() {
    super.initState();
    _server = TextEditingController(text: widget.initial.serverUrl);
    _cache = TextEditingController(text: '${widget.initial.cacheLimitMb}');
    _allowSelfSigned = widget.initial.allowSelfSignedHttps;
  }

  @override
  void dispose() {
    _server.dispose();
    _cache.dispose();
    super.dispose();
  }

  void _submit() {
    try {
      final server = normalizeServerUrl(_server.text);
      final cache = normalizeCacheLimit(int.tryParse(_cache.text.trim()) ?? 0);
      final next = widget.initial.copyWith(
        serverUrl: server,
        cacheLimitMb: cache,
        allowSelfSignedHttps: _allowSelfSigned,
      ).normalized();
      Navigator.of(context).pop(next);
    } on ConfigException catch (error) {
      setState(() => _error = error.message);
    } on Object catch (error) {
      setState(() => _error = '保存失败：$error');
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: const Color(0xFF0B0E13),
      surfaceTintColor: Colors.transparent,
      titlePadding: const EdgeInsets.fromLTRB(24, 22, 24, 0),
      contentPadding: const EdgeInsets.fromLTRB(24, 12, 24, 0),
      actionsPadding: const EdgeInsets.fromLTRB(24, 8, 24, 20),
      title: const Text(
        'StrmAction 设置',
        style: TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.bold),
      ),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '原生内嵌播放，进度自动回传；登录在网页内完成。',
                style: TextStyle(color: Color(0xFF8B94A7), fontSize: 11.5),
              ),
              const SizedBox(height: 18),
              const _Label('服务器地址'),
              const SizedBox(height: 6),
              _field(
                controller: _server,
                hintText: 'https://media.example.com',
                keyboardType: TextInputType.url,
              ),
              const SizedBox(height: 14),
              const _Label('预读缓存上限（MB，0 = 关闭）'),
              const SizedBox(height: 6),
              _field(
                controller: _cache,
                hintText: '128',
                keyboardType: TextInputType.number,
              ),
              const SizedBox(height: 8),
              const Text(
                '范围 16–2048 MB；0 表示不启用 demuxer 缓存。',
                style: TextStyle(color: Color(0xFF7C8698), fontSize: 11),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Checkbox(
                    value: _allowSelfSigned,
                    activeColor: const Color(0xFFE8B06A),
                    checkColor: const Color(0xFF17120B),
                    onChanged: (value) => setState(() => _allowSelfSigned = value ?? false),
                  ),
                  const Expanded(
                    child: Text(
                      '允许自签名 HTTPS 证书',
                      style: TextStyle(color: Color(0xFFC9CFDA), fontSize: 12.5),
                    ),
                  ),
                ],
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(
                  _error!,
                  style: const TextStyle(color: Color(0xFFFDA4AF), fontSize: 11.5),
                ),
              ],
              const SizedBox(height: 8),
              const Text(
                '登录状态由 WebView 保存；首次使用需要重新登录一次。',
                style: TextStyle(color: Color(0xFF7C8698), fontSize: 11),
              ),
            ],
          ),
        ),
      ),
      actions: [
        if (widget.allowCancel)
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('取消', style: TextStyle(color: Color(0xFFC9CFDA))),
          ),
        FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xFFE8B06A),
            foregroundColor: const Color(0xFF17120B),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
          ),
          onPressed: _submit,
          child: const Text('保存并进入', style: TextStyle(fontWeight: FontWeight.bold)),
        ),
      ],
    );
  }

  Widget _field({
    required TextEditingController controller,
    required String hintText,
    TextInputType? keyboardType,
  }) {
    return TextField(
      controller: controller,
      keyboardType: keyboardType,
      autofocus: false,
      style: const TextStyle(color: Color(0xFFE8EAEF), fontSize: 13),
      decoration: InputDecoration(
        hintText: hintText,
        hintStyle: const TextStyle(color: Color(0xFF5E6675), fontSize: 13),
        filled: true,
        fillColor: const Color(0xFF11151C),
        contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 11),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: Color(0x1FFFFFFF)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: Color(0xB3E8B06A)),
        ),
      ),
    );
  }
}

class _Label extends StatelessWidget {
  final String text;

  const _Label(this.text);

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(color: Color(0xFFC9CFDA), fontSize: 12),
    );
  }
}
