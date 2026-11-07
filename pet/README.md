# KRINO 娘 · DSH 桌宠

- `plugin/`：发布到 npm 的 DSH 插件 `dsh-pet-krino`（纯 JS，不用打包）。说明见 `plugin/README.md`。
- `tools/`：做动作素材的三步，密钥用项目 `.env` 的 `DASHSCOPE_API_KEY`，Python 用 krino_matrix 环境。
- `work/`：生成过程中的中间文件（Q 版底图、绿幕视频），不进插件。

## 做素材

```bash
PY=/home/seanhuang2004/anaconda3/envs/krino_matrix/bin/python
# 1. 以立绘为参考，生成 Q 版基础姿势（绿幕），挑一张存成 work/krino/base.png
$PY pet/tools/qimage.py app/frontend/assets/krino.png pet/work/krino "白色长发、细框眼镜、菱形发夹……" 2
# 2. 每个动作一段 5 秒视频：首帧、尾帧都是基础姿势 → 所有动作都能无缝衔接。动作表在 tools/actions.py
$PY pet/tools/actions.py pet/work/krino/base.png pet/work/krino/clips            # 已有的跳过；也可以只写动作名
# 3. 绿幕 → 透明 WebM（所有片段同一个裁切框，人物位置大小不变）
$PY pet/tools/key.py pet/work/krino/clips pet/plugin/assets/clips 400
```

费用：千问图像一张约 0.25 元；万相首尾帧视频 720P 一段 5 秒约 1 元（`wan2.2-kf2v-flash`）。

加新动作：在 `tools/actions.py` 的 `ACTIONS` 里加一行描述，跑第 2、3 步，再在 `plugin/lib/client.js` 的 `MOODS` / `POKE` 里用上它。

## 本地试插件

```bash
cd pet/plugin && npm pack --pack-destination /tmp
dsh plugin --profile krino-test add /tmp/dsh-pet-krino-<版本>.tgz   # krino-test 是测试用的 profile，不影响平时的 web
dsh krino-test --patch ~/.dsh/openrouter.patch.yml
```

## 发布

```bash
cd pet/plugin && npm publish            # 需要先 npm login；发布前把 package.json 的 version 加一
```

然后到 <https://dsh.so/zh/submit/> 提交（投稿进度在 github.com/ihuajiu/dsh-plugin-submissions）。
