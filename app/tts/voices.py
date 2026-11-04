"""角色音色的描述。scripts/design_voices.py 用 Qwen3-TTS VoiceDesign 按描述生成参考音频，之后服务用它克隆出稳定的声音。

改描述之后重新运行 `scripts/world.sh voices`（会覆盖 data/models/voices/ 下对应的文件）。
不写“萝莉”“幼态”这类描述：角色都是成年人的声音。
"""

VOICES = {
    "dafeiyu-zh": {
        "language": "Chinese",
        "instruct": ("二十岁左右的年轻女声，音色明亮、带一点软糯的鼻音，语速偏快。语气慵懒又傲娇，像在和很熟的朋友斗嘴："
                     "嘴硬的时候音调突然扬起来，心虚时又小声嘟囔，句尾常常拖长一点。自然的口语，有呼吸声和小停顿，不像播音腔。"),
        "text": "哼，终于来了……才不是特意等你的。本肥鱼刚吃完第三碗饭，有话快说嘛～什么？你说我胖？那只是尾巴大！",
    },
    "dafeiyu-en": {
        "language": "English",
        "instruct": ("Young adult woman around twenty, bright voice with a slightly soft, nasal warmth, talks fast. "
                     "Lazy, smug, playfully tsundere, like teasing a close friend: pitch jumps up when she's being stubborn, "
                     "drops to a mumble when she's flustered, drags out sentence endings. Natural and casual, audible breaths, not a narrator."),
        "text": "Hmph, finally. Not that I was waiting for you or anything. I just finished my third bowl of rice, so make it quick! What? Fat? It's just a big tail!",
    },
    "krino-zh": {
        "language": "Chinese",
        "instruct": ("二十五岁左右的女性，声音清冷、偏低、非常平稳，语速适中略慢，吐字清楚。冷静理性，没有多余的语气词，"
                     "像研究员在简短地说结论；句子之间有短暂的停顿，偶尔透出一点不易察觉的温柔。"),
        "text": "你来了。结论是——今天也有很多事值得做。先说说你在想什么，我帮你把选项砍到两个。",
    },
    "krino-en": {
        "language": "English",
        "instruct": ("Woman in her mid-twenties, cool, low and very steady voice, measured slightly slow pace, crisp articulation. "
                     "Calm and rational, no filler words, like a researcher stating a conclusion; short pauses between sentences, "
                     "a faint, hidden warmth and dry humor."),
        "text": "You're here. Conclusion first: there's a lot worth doing today. Tell me what's on your mind, and I'll cut your options down to two.",
    },
}
