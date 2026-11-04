# 第三方前端库（本地托管，运行时不依赖 CDN）

| 文件 | 来源 | 版本 | 许可 |
| --- | --- | --- | --- |
| `pixi/pixi.min.js` | [pixi.js](https://github.com/pixijs/pixijs) | 7.4.2 | MIT（`pixi/LICENSE`） |
| `live2d/pixi-live2d-display-cubism4.min.js` | [pixi-live2d-display-lipsyncpatch](https://github.com/RaSan147/pixi-live2d-display)（guansss/pixi-live2d-display 的分支，加了口型同步） | 0.5.0-ls-8 | MIT（`live2d/LICENSE-pixi-live2d-display`） |
| `live2d/live2dcubismcore.min.js` | [Live2D Cubism Core for Web](https://www.live2d.com/sdk/download/web/) | 5 | Live2D Proprietary Software License，文件头注明属于可再分发代码（Redistributable Code） |

Cubism Core 不是开源软件。个人和小企业免费使用；中型以上企业正式发布前需要和 Live2D 签发布许可，见 https://www.live2d.com/en/sdk/license/ 。

页面用普通 `<script>` 按顺序加载（Cubism Core → PixiJS → pixi-live2d-display），它们挂在全局 `Live2DCubismCore`、`PIXI` 上。

升级：`npm pack pixi.js@7 pixi-live2d-display-lipsyncpatch`，从 `dist/` 复制同名文件；Cubism Core 从 Live2D 官网下载。
