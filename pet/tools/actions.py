"""KRINO 娘桌宠的动作表：每个动作一段 5 秒视频，都从基础姿势开始、回到基础姿势结束（首尾帧相同），所以随便怎么接都不跳。

    python pet/tools/actions.py <基础姿势.png> <输出目录> [动作名 ...]   # 不写动作名 = 全部（已经有的跳过）

动作名也是插件里的动画名，对应的时机见 pet/plugin/src/client.tsx 里的 PLAN。
"""
from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ACTIONS = {
    # 平时
    "idle": "她安静地站着呼吸，身体随呼吸轻轻起伏，头微微左右晃了一下，眨了两次眼睛，长发和外套下摆随之轻轻飘动，最后回到一开始的姿势。",
    "glasses": "她抬起右手用食指轻轻推了推眼镜，眼镜反了一下光，然后露出一点得意的小微笑，手放下，回到一开始的姿势。",
    "look": "她好奇地先往左边看，再往右边看，头跟着轻轻转动，长发跟着甩动，然后看回前方，回到一开始的姿势。",
    "stretch": "她双手举过头顶伸了个大大的懒腰，踮起脚尖，眼睛眯成一条线，身体左右轻晃一下，然后放下手臂，回到一开始的姿势。",
    "doze": "她站着打瞌睡，眼睛慢慢闭上，头一点一点地往下垂，脑袋上飘出一个小小的鼻涕泡，突然惊醒抖了一下，揉了揉眼睛，回到一开始的姿势。",
    # 和你互动
    "wave": "她开心地抬起右手朝前方挥手打招呼，笑得眼睛弯弯，身体随着挥手轻轻左右摇摆，挥了几下后手放下，回到一开始的姿势。",
    "happy": "她非常开心，原地轻快地蹦跳了两下，双手握拳放在胸前，眼睛笑成弯月，长发和外套在空中弹起又落下，落地后回到一开始的姿势。",
    "surprised": "她像是被轻轻戳了一下，吓了一跳，身体往上一缩，眼睛睁得圆圆的，头发微微竖起，然后脸红害羞地低下头，双手捂了一下脸颊，再放下，回到一开始的姿势。",
    "nod": "她认真地点了两下头表示明白了，表情坚定可靠，右手比了一个小小的 OK 手势，然后放下，回到一开始的姿势。",
    # 陪你干活（DSH 里的 AI 在工作时）
    "think": "她右手托着下巴歪着头思考，眼睛向上看，头顶冒出一个小小的问号，然后恍然大悟地眼睛一亮，手放下，回到一开始的姿势。",
    "read": "她从外套里拿出一本黑色的小书，低头专注地翻阅了两页，轻轻点头，然后把书合上收回外套里，回到一开始的姿势。",
    "type": "她面前凭空出现一块半透明的小键盘，她双手飞快地敲打，表情专注认真，敲完最后一下键盘消失，她满意地点头，回到一开始的姿势。",
    "done": "她开心地双手举起比出两个 V 字手势，眨了一下眼睛，身体轻轻一跳，然后放下手，回到一开始的姿势。",
}


def main() -> None:
    base, out = Path(sys.argv[1]), Path(sys.argv[2])
    names = sys.argv[3:] or list(ACTIONS)
    todo = [n for n in names if not (out / f"{n}.mp4").exists()]
    clip = Path(__file__).with_name("clip.py")

    def one(n: str) -> str:
        r = subprocess.run([sys.executable, str(clip), str(base), str(out / f"{n}.mp4"), ACTIONS[n]], capture_output=True, text=True)
        return f"{n}: {'ok' if r.returncode == 0 else r.stderr.strip().splitlines()[-1]}"

    with ThreadPoolExecutor(max_workers=3) as pool:  # 百炼视频并发有限，三个一组
        for line in pool.map(one, todo):
            print(line, flush=True)


if __name__ == "__main__":
    main()
