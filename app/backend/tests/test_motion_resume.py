"""动图任务被服务重启打断后接着做（workbench.resume_jobs）：已经下好的片段不重做，做完换上动图。

不调百炼：基础姿势和动作视频都用 ffmpeg 现场生成的绿幕小视频代替。
"""
import subprocess
import time

import pytest

from app import motion, workbench
from app.config import settings


def _green_clip(path):
    """5 秒、30 帧的绿幕视频，中间一个会动的白方块（当作人物）。"""
    ff = motion._ffmpeg()
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x00ff00:s=320x320:d=5:r=30",
                    "-vf", "drawbox=x=100+20*sin(t*3):y=80:w=120:h=180:color=white:t=fill", "-pix_fmt", "yuv420p", str(path)],
                   check=True)


def _fake_video(monkeypatch):
    """换成假的生成：返回被调用做了哪些动作。打开“百炼”开关（resume_jobs 只在真的能做视频时才接着做）。"""
    from PIL import Image
    calls = []
    monkeypatch.setattr(motion, "base_pose", lambda img: Image.new("RGB", (320, 320), (0, 255, 0)))

    def clip(base_uri, action, out):
        calls.append(out.stem)
        _green_clip(out)
    monkeypatch.setattr(motion, "clip", clip)
    monkeypatch.setattr(settings, "image_provider", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "test")
    return calls


def test_interrupted_motion_job_resumes(user, monkeypatch):
    from PIL import Image
    pytest.importorskip("imageio_ffmpeg")
    r = user.ok("post", "/api/workbench/character", json={"draft": {"persona": {"name": "接着做"}, "appearance": "x"}, "wait": True})
    c = r["character"]
    fake_video = _fake_video(monkeypatch)
    uid = user.info["id"]
    img = c["behavior"]["portrait"]["src"]
    # 模拟：做到一半服务重启了。工作目录里有基础姿势和前 3 段，角色上记着任务
    work = motion.new_work(uid)
    (work / "_raw").mkdir(parents=True)
    Image.new("RGB", (320, 320), (0, 255, 0)).save(work / "_raw" / "base.png")
    names = motion.clip_names()
    for n in names[:3]:
        _green_clip(work / "_raw" / f"{n}.mp4")
    workbench._set_origin(c["id"], motion_job={"done": 3, "total": len(names), "started": int(time.time()) - 600,
                                               "dir": work.name, "image": img})
    workbench.resume_jobs()
    for _ in range(300):
        x = user.ok("get", f"/api/characters/{c['id']}")
        if "motion_job" not in x:
            break
        time.sleep(0.2)
    assert sorted(fake_video) == sorted(names[3:])  # 只做了剩下的
    assert x["behavior"]["portrait"]["kind"] == "chibi" and x["behavior"]["portrait"]["src"].startswith(f"/media/u/{uid}/{work.name}/")
    assert (work / "chibi.json").is_file() and not (work / "_raw").exists()
    assert any(l["kind"] == "image" and l["src"] == img for l in x["looks"])  # 立绘留在她的形象里
