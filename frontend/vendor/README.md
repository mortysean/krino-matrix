# 第三方前端库（本地托管，运行时不依赖 CDN）

| 目录 | 包 | 版本 | 许可证 | 来源文件 |
| --- | --- | --- | --- | --- |
| `three/` | [three](https://github.com/mrdoob/three.js) | 0.186.1 | MIT（`three/LICENSE`） | `build/three.module.js`、`build/three.core.js`、`examples/jsm/loaders/GLTFLoader.js`、`examples/jsm/utils/{BufferGeometryUtils,SkeletonUtils}.js` |
| `three-vrm/` | [@pixiv/three-vrm](https://github.com/pixiv/three-vrm) | 3.5.5 | MIT（`three-vrm/LICENSE`） | `lib/three-vrm.module.min.js` |

页面里用 import map 解析裸模块名：

```html
<script type="importmap">
{ "imports": { "three": "/static/vendor/three/three.module.js",
               "three/addons/": "/static/vendor/three/addons/",
               "@pixiv/three-vrm": "/static/vendor/three-vrm/three-vrm.module.min.js" } }
</script>
```

升级：`npm pack three@<版本> @pixiv/three-vrm@<版本>`，解包后按上表覆盖同名文件，并更新本表。
