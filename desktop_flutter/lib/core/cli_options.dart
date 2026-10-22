import 'package:args/args.dart';

class CliOptions {
  final String? server;
  final bool settings;
  final bool debug;
  final bool version;

  const CliOptions({
    this.server,
    this.settings = false,
    this.debug = false,
    this.version = false,
  });

  static CliOptions parse(List<String> args) {
    final parser = ArgParser()
      ..addOption('server', help: '设置并保存服务器地址')
      ..addFlag('settings', abbr: 's', negatable: false, help: '启动后打开设置')
      ..addFlag('debug', abbr: 'd', negatable: false, help: '输出调试日志')
      ..addFlag('version', abbr: 'v', negatable: false, help: '输出版本号');
    final result = parser.parse(args);
    return CliOptions(
      server: result.option('server'),
      settings: result.flag('settings'),
      debug: result.flag('debug'),
      version: result.flag('version'),
    );
  }
}
