/// How the decoded picture is mapped onto the player surface.
enum VideoScaleMode {
  /// Keep the video's own aspect ratio, letterboxed inside the surface.
  fit,

  /// Fill the surface, cropping the overflowing edges (centre crop).
  crop,

  /// Fill the surface, stretching the picture (distorts the image).
  stretch,

  /// Fit inside a fixed 16:9 frame.
  ratio16x9,

  /// Fit inside a fixed 4:3 frame.
  ratio4x3,

  /// Fit inside a fixed 21:9 frame.
  ratio21x9,
}

extension VideoScaleModeMeta on VideoScaleMode {
  /// Stable id used in the persisted configuration and the native channels.
  String get id => switch (this) {
        VideoScaleMode.fit => 'fit',
        VideoScaleMode.crop => 'crop',
        VideoScaleMode.stretch => 'stretch',
        VideoScaleMode.ratio16x9 => '16:9',
        VideoScaleMode.ratio4x3 => '4:3',
        VideoScaleMode.ratio21x9 => '21:9',
      };

  String get label => switch (this) {
        VideoScaleMode.fit => '原比例',
        VideoScaleMode.crop => '铺满屏幕（裁剪）',
        VideoScaleMode.stretch => '拉伸铺满（变形）',
        VideoScaleMode.ratio16x9 => '16:9',
        VideoScaleMode.ratio4x3 => '4:3',
        VideoScaleMode.ratio21x9 => '21:9',
      };

  String get description => switch (this) {
        VideoScaleMode.fit => '按视频自身比例显示，多余区域留黑边',
        VideoScaleMode.crop => '放大到铺满屏幕，裁掉超出画面的部分',
        VideoScaleMode.stretch => '拉伸到铺满屏幕，画面会被拉变形',
        VideoScaleMode.ratio16x9 => '放进 16:9 画幅，视频在其中保持原比例',
        VideoScaleMode.ratio4x3 => '放进 4:3 画幅，视频在其中保持原比例',
        VideoScaleMode.ratio21x9 => '放进 21:9 画幅，视频在其中保持原比例',
      };

  /// Aspect ratio the picture is forced into, or null to follow the video.
  double? get forcedAspect => switch (this) {
        VideoScaleMode.ratio16x9 => 16 / 9,
        VideoScaleMode.ratio4x3 => 4 / 3,
        VideoScaleMode.ratio21x9 => 21 / 9,
        _ => null,
      };
}

VideoScaleMode videoScaleModeFromId(String? id) => switch (id) {
      'crop' => VideoScaleMode.crop,
      'stretch' => VideoScaleMode.stretch,
      '16:9' => VideoScaleMode.ratio16x9,
      '4:3' => VideoScaleMode.ratio4x3,
      '21:9' => VideoScaleMode.ratio21x9,
      _ => VideoScaleMode.fit,
    };
