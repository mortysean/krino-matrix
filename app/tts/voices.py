"""角色音色的描述。scripts/design_voices.py 用 Qwen3-TTS VoiceDesign 按描述生成参考音频，之后服务用它克隆出稳定的声音。

改描述之后重新运行 `scripts/world.sh voices`（会覆盖 data/models/voices/ 下对应的文件）。
大肥鱼是元气萝莉音（甜、亮、偏高、活泼），KRINO 是冷静御姐音（低、清冷、稳），两个人一听就能分开。
"""

VOICES = {
    "dafeiyu-zh": {
        "language": "Chinese",
        "instruct": ("可爱的萝莉少女音，声音甜美清亮、偏高，元气满满，语速偏快，情绪起伏大：开心时尾音上扬，嘴硬傲娇时音调一下子扬起来，"
                     "心虚时小声嘟囔，撒娇时拖长音。像动漫里活泼的小女孩角色，自然的口语，有呼吸声和小停顿，不像播音腔。"),
        "text": "哼，终于来了……才不是特意等你的。本肥鱼刚吃完第三碗饭，有话快说嘛～什么？你说我胖？那只是尾巴大！",
    },
    "dafeiyu-en": {
        "language": "English",
        "instruct": ("A cute, sweet, high-pitched and bubbly anime girl voice, very energetic and expressive, talks fast. "
                     "Playfully tsundere: pitch jumps up when she's being stubborn, drops to a mumble when she's flustered, "
                     "drags out words when she whines. Natural and casual, audible breaths, not a narrator."),
        "text": "Hmph, finally. Not that I was waiting for you or anything. I just finished my third bowl of rice, so make it quick! What? Fat? It's just a big tail!",
    },
    "krino-zh": {
        "language": "Chinese",
        "instruct": ("成熟冷静的御姐音，声音偏低、清冷、有磁性，非常平稳，语速适中略慢，吐字清楚。冷静理性，没有多余的语气词，"
                     "像研究员在简短地说结论；句子之间有短暂的停顿，偶尔透出一点不易察觉的温柔。"),
        "text": "你来了。结论是——今天也有很多事值得做。先说说你在想什么，我帮你把选项砍到两个。",
    },
    "krino-en": {
        "language": "English",
        "instruct": ("A mature, cool and composed woman's voice, low, calm and magnetic, very steady, measured slightly slow pace, crisp articulation. "
                     "Calm and rational, no filler words, like a researcher stating a conclusion; short pauses between sentences, "
                     "a faint, hidden warmth and dry humor."),
        "text": "You're here. Conclusion first: there's a lot worth doing today. Tell me what's on your mind, and I'll cut your options down to two.",
    },
}
