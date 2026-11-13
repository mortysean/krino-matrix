"""官网 krinomatrix.com 的地区与产品配置（build.py 读这里；不叫 site.py 是因为和 Python 自带的 site 模块重名）。

两个地区站 /cn/ 和 /global/ 各自独立运营：语言、产品列表、联系方式、法律文件、第三方服务都按地区配，
页面正文在 content/<地区>/ 下，各写各的。共用的只有外壳（顶栏、页脚、样式、脚本）。

- 给某个地区加产品：在 PRODUCTS 里登记，在该地区的 products 列表里加一项，再写 content/<地区>/products/<slug>.html。
- 某个地区下架产品：从它的 products 列表里删掉即可，另一个地区不受影响。
- 某个地区不要某个页面：删掉 content/<地区>/<页面>.html，导航和站点地图会跟着去掉。
"""

SITE = "https://krinomatrix.com"
CONTACT = "support@krinomatrix.com"
UPDATED = "2026-11-10"  # 法律文件的更新日期（地区里写了 updated 就用地区自己的）

# 产品本身的信息（和地区无关）。图片路径相对站点根目录。
PRODUCTS = {
    "world": {"name": "KRINO WORLD", "image": "assets/krino.png"},
}

REGIONS = {
    "cn": {
        "lang": "zh-CN",
        "og_locale": "zh_CN",
        "label": "中国大陆",
        "switch": "中国大陆 · 中文",  # 别的地区页面上“切到这里”的链接文字
        "company": "杭州决策矩阵科技有限公司",
        "brand_sub": "决策矩阵",
        "icp": "浙ICP备2026093639号",
        "contact": CONTACT,
        "site_name": "决策矩阵 KRINO MATRIX",
        "description": "杭州决策矩阵科技有限公司：我们做会记得你、有自我、会成长的 AI 角色。",
        # 以后接入的国内服务（微信登录、微信支付、支付宝、统计……）写在这里，只影响 /cn/
        "services": {},
        "products": [
            {"slug": "world", "tagline": "会记得你的 AI 角色世界", "status": "已上线",
             "app": "/cn/products/world/", "cta": "立即体验"},
        ],
        "t": {  # 外壳上的文字
            "products": "产品", "developers": "开发者", "about": "关于", "contact": "联系",
            "manifesto": "宣言", "apocalypse": "启示与应验", "tree": "战略", "enter": "进入 Krino World", "login": "登录",
            "privacy": "隐私政策", "terms": "服务条款", "cookies": "Cookie 政策",
            "legal": "法律", "company_h": "公司", "region": "地区", "change_region": "切换地区",
            "all_products": "产品介绍", "learn": "了解", "home": "首页",
            "cookie_note": '本站不做追踪，也不接任何统计。只用一个 Cookie 记住你选的地区。<a href="{base}cookies/">了解更多</a>',
            "got_it": "知道了",
        },
    },
    "global": {
        "lang": "en",
        "og_locale": "en_US",
        "label": "International",
        "switch": "International · English",
        "company": "Krino Matrix",
        "brand_sub": "",
        "icp": "",
        "contact": CONTACT,
        "site_name": "KRINO MATRIX",
        "updated": "2026-11-12",  # 国际站隐私政策改过（不再写总部所在地）
        "description": "Krino Matrix builds AI characters that remember you, know themselves and grow.",
        # International services (Stripe, sign-in providers, analytics…) go here and only affect /global/
        "services": {},
        "products": [
            {"slug": "world", "tagline": "A world of AI characters that remember you", "status": "Live",
             "app": "/global/products/world/", "cta": "Try it now"},
        ],
        "t": {
            "products": "Products", "developers": "Developers", "about": "About", "contact": "Contact",
            "manifesto": "Manifesto", "apocalypse": "Apocalypse & Fulfillment", "tree": "Krino Tree", "enter": "Enter Krino World", "login": "Log in",
            "privacy": "Privacy Policy", "terms": "Terms of Service", "cookies": "Cookie Policy",
            "legal": "LEGAL", "company_h": "COMPANY", "region": "Region", "change_region": "Change region",
            "all_products": "Product overview", "learn": "Explore", "home": "Home",
            "cookie_note": 'No tracking and no analytics here. One cookie remembers the region you picked. <a href="{base}cookies/">Learn more</a>',
            "got_it": "GOT IT",
        },
    },
}
