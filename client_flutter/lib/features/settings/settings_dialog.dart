import 'package:flutter/material.dart';

import '../../core/config.dart';
import '../../core/trust.dart';

class SettingsDialog extends StatefulWidget {
  final AppConfig initial;
  final bool allowCancel;
  final String? accountKey;

  const SettingsDialog({
    super.key,
    required this.initial,
    required this.allowCancel,
    this.accountKey,
  });

  @override
  State<SettingsDialog> createState() => _SettingsDialogState();
}

class _SettingsDialogState extends State<SettingsDialog> {
  late final TextEditingController _server;
  late final TextEditingController _cache;
  late final TextEditingController _boostSpeed;
  late final TextEditingController _ca;
  late final TextEditingController _disk;
  late bool _inheritCache;
  late bool _inheritMode;
  late String _mode;
  String? _error;

  @override
  void initState() {
    super.initState();
    _server = TextEditingController(text: widget.initial.serverUrl);
    _cache = TextEditingController(text: '${widget.initial.cacheLimitMb}');
    _boostSpeed = TextEditingController(text: '${widget.initial.boostSpeed}');
    _ca = TextEditingController(text: widget.initial.trustedCaPem);
    _disk = TextEditingController(text: '${widget.initial.diskCacheLimitMb}');
    _inheritCache = widget.initial.inheritCacheDefaults;
    _inheritMode = !widget.initial.playbackOverrides.containsKey(widget.accountKey);
    _mode = widget.initial.playbackOverrides[widget.accountKey] ?? 'builtin';
  }

  @override
  void dispose() {
    _ca.dispose();
    _disk.dispose();
    _server.dispose();
    _cache.dispose();
    _boostSpeed.dispose();
    super.dispose();
  }

  void _submit() {
    try {
      final server = normalizeServerUrl(_server.text);
      final cache = normalizeCacheLimit(int.tryParse(_cache.text.trim()) ?? 0);
      final boostSpeed = double.tryParse(_boostSpeed.text.trim()) ?? defaultBoostSpeed;
      validateCaBundle(_ca.text);
      final overrides = Map<String, String>.from(widget.initial.playbackOverrides);
      if (widget.accountKey != null) {
        if (_inheritMode) { overrides.remove(widget.accountKey); }
        else { overrides[widget.accountKey!] = _mode; }
      }
      final next = widget.initial.copyWith(
        serverUrl: server,
        cacheLimitMb: cache,
        trustedCaPem: _ca.text,
        inheritCacheDefaults: _inheritCache,
        diskCacheLimitMb: int.tryParse(_disk.text) ?? 2048,
        playbackOverrides: overrides,
        boostSpeed: boostSpeed,
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
                '本机覆盖生效时使用以上容量；0 关闭预读。磁盘容量单独设置。',
                style: TextStyle(color: Color(0xFF7C8698), fontSize: 11),
              ),
              const SizedBox(height: 14),
              const _Label('长按倍速（0.25 - 4.0，默认 2.0）'),
              const SizedBox(height: 6),
              _field(
                controller: _boostSpeed,
                hintText: '2.0',
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
              ),
              const SizedBox(height: 8),
              const Text(
                '播放时长按画面或键盘右方向键加速，松开恢复原速。',
                style: TextStyle(color: Color(0xFF7C8698), fontSize: 11),
              ),
              const SizedBox(height: 12),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('使用云端缓存默认值'),
                value: _inheritCache,
                onChanged: (value) => setState(() => _inheritCache = value),
              ),
              const _Label('磁盘缓存上限（MB，0 = 关闭，退出播放清空）'),
              _field(controller: _disk, hintText: '2048', keyboardType: TextInputType.number),
              const SizedBox(height: 14),
              if (widget.accountKey != null) ...[
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('使用账号默认播放方式'),
                  value: _inheritMode,
                  onChanged: (value) => setState(() => _inheritMode = value),
                ),
                DropdownButtonFormField<String>(
                  initialValue: _mode,
                  items: const [
                    DropdownMenuItem(value: 'builtin', child: Text('内部播放')),
                    DropdownMenuItem(value: 'copy', child: Text('复制链接')),
                  ],
                  onChanged: _inheritMode ? null : (value) => setState(() => _mode = value ?? 'builtin'),
                ),
                const SizedBox(height: 14),
              ],
              const _Label('私有根 CA（PEM，可粘贴多张证书）'),
              TextField(
                controller: _ca, minLines: 3, maxLines: 8,
                autocorrect: false,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
                decoration: const InputDecoration(hintText: '-----BEGIN CERTIFICATE-----'),
              ),
              const Text('公共证书自动验证；私有 CA 同样校验主机名。旧版放行开关需改为导入根 CA。', style: TextStyle(fontSize: 11)),
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
