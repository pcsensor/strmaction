"""生成 §18 测试样本目录（占位 .strm）。

用法：
    python scripts/make_samples.py --dest sample-media
    python scripts/make_samples.py --dest /tmp/strm --big 1000

生成的 .strm 内容为不可访问的示例 URL，仅用于验证目录解析与入库流程。
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

SAMPLES: dict[str, list[str]] = {
    "movies": [
        "流浪地球2 (2023)/流浪地球2 (2023).strm",
        "沙丘2 (2024)/沙丘2 (2024) - 2160p.strm",
        "沙丘2 (2024)/沙丘2 (2024) - 1080p.strm",
        "奥本海默 （2023）/奥本海默 （2023）.strm",
        "无名/无名.strm",
        "黑客帝国 (1999) {tmdb-603}/黑客帝国 (1999).strm",
    ],
    "tv": [
        "三体 (2023)/Season 01/三体 - S01E01.strm",
        "三体 (2023)/Season 01/三体 - S01E02.strm",
        "漫长的季节 (2023)/S01/漫长的季节.01.strm",
        "Some.Show.2020/Season 02/Some.Show.S02E03.1080p.strm",
        "狂飙/第一季/第12集.strm",
        "进击的巨人 (2013)/Season 01/进击的巨人 - S01E01.strm",
    ],
    "anime": [
        "进击的巨人 (2013)/Season 01/进击的巨人 - S01E01.strm",
        "进击的巨人 (2013)/Season 01/进击的巨人 - S01E02.strm",
    ],
    "home": [
        "2024-06-01 生日/VID_20240601.mp4.strm",
        "2024-06-01 生日/VID_20240601_2.mp4.strm",
    ],
    "course": [
        "Rust 实战/01 所有权/01 所有权.strm",
        "Rust 实战/01 所有权/02 借用与生命周期.strm",
        "Rust 实战/02 并发/01 线程.strm",
    ],
}


def write_strm(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    path.write_text(
        f"https://example.com/strm/{digest}.mp4?token=demo\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default="sample-media", help="输出目录")
    parser.add_argument("--big", type=int, default=0, help="额外生成 N 部电影用于压力测试")
    args = parser.parse_args()
    root = Path(args.dest)
    for folder, files in SAMPLES.items():
        for rel in files:
            write_strm(root / folder / rel, f"{folder}/{rel}")
    if args.big:
        for index in range(args.big):
            title = f"压力测试电影 {index:04d}"
            write_strm(
                root / "bulk" / f"{title} (2024)" / f"{title} (2024).strm",
                f"bulk/{index}",
            )
    total = sum(1 for _ in root.rglob("*.strm"))
    print(f"已生成 {total} 个 .strm 文件：{root.resolve()}")


if __name__ == "__main__":
    main()
