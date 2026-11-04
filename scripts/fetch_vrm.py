"""下载默认 3D 形象（pixiv 的 VRM 1.0 示例模型），校验格式与再分发许可后放到 frontend/assets/vrm/default.vrm。

    python scripts/fetch_vrm.py            # 已存在且校验通过则跳过
    python scripts/fetch_vrm.py --force    # 重新下载

只用标准库；urllib 会读取 HTTPS_PROXY 等代理变量。模型文件不进 git（.gitignore），许可信息写进同目录 LICENSE.md。
没有这个文件时前端会显示内置的程序化形象，所以这一步失败不影响运行。
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/pixiv/three-vrm/dev/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm"
OUT_DIR = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "vrm"
OUT = OUT_DIR / "default.vrm"
MAX_BYTES = 64 * 1024 * 1024


def vrm_meta(data: bytes) -> dict:
    """读出 glb 里的 VRM meta（1.0：VRMC_vrm.meta；0.x：VRM.meta）。不是合法 VRM 时抛 ValueError。"""
    if data[:4] != b"glTF" or len(data) < 20:
        raise ValueError("不是 glTF 二进制文件")
    length, ctype = struct.unpack("<I4s", data[12:20])
    if ctype != b"JSON":
        raise ValueError("glb 第一个块不是 JSON")
    doc = json.loads(data[20:20 + length])
    ext = doc.get("extensions") or {}
    if "VRMC_vrm" in ext:
        return {"vrm_version": "1.0", **(ext["VRMC_vrm"].get("meta") or {})}
    if "VRM" in ext:
        return {"vrm_version": "0.x", **(ext["VRM"].get("meta") or {})}
    raise ValueError("文件里没有 VRM 扩展")


def check_license(meta: dict) -> None:
    if meta.get("vrm_version") != "1.0":
        raise ValueError("默认模型应为 VRM 1.0")
    if meta.get("allowRedistribution") is not True:
        raise ValueError("模型许可不允许再分发")
    if meta.get("modification") != "allowModificationRedistribution":
        raise ValueError("模型许可不允许修改后再分发")


def write_license(meta: dict, sha: str) -> None:
    rows = [("名称", meta.get("name")), ("作者", ", ".join(meta.get("authors") or [])),
            ("版权", meta.get("copyrightInformation")), ("许可", meta.get("licenseUrl")),
            ("允许再分发", meta.get("allowRedistribution")), ("修改", meta.get("modification")),
            ("商用", meta.get("commercialUsage")), ("署名要求", meta.get("creditNotation")),
            ("来源", URL), ("sha256", sha)]
    text = "# 默认 3D 形象的许可信息\n\n`default.vrm` 由 `scripts/fetch_vrm.py` 下载，下表来自模型文件自带的 VRM meta。\n\n"
    text += "| 项 | 值 |\n| --- | --- |\n" + "".join(f"| {k} | {v} |\n" for k, v in rows)
    (OUT_DIR / "LICENSE.md").write_text(text, encoding="utf-8")


def main() -> int:
    force = "--force" in sys.argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUT.exists() and not force:
        data = OUT.read_bytes()
        try:
            check_license(vrm_meta(data))
            write_license(vrm_meta(data), hashlib.sha256(data).hexdigest())
            print(f"已存在，跳过：{OUT}")
            return 0
        except ValueError as e:
            print(f"已有文件无效（{e}），重新下载")
    print(f"下载 {URL}")
    with urllib.request.urlopen(URL, timeout=120) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        print("文件过大，放弃", file=sys.stderr)
        return 1
    meta = vrm_meta(data)
    check_license(meta)
    sha = hashlib.sha256(data).hexdigest()
    tmp = OUT.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(OUT)
    write_license(meta, sha)
    print(f"已保存 {OUT}（{len(data) / 1e6:.1f} MB，sha256 {sha[:12]}…）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as e:
        print(f"获取默认 VRM 失败：{e}（前端会使用内置形象）", file=sys.stderr)
        sys.exit(1)
