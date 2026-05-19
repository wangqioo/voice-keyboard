"""Built-in Application Shortcut Catalog presets.

The values are user-visible action names mapped to keyboard shortcuts. The
Speech Interpretation Provider sees only the action names; the local engine
keeps final authority over the concrete key sequences.
"""

_FEISHU_BITABLE_SHORTCUTS = {
    "多维表格撤销": "cmd+z",
    "多维表格重做": "cmd+shift+z",
    "多维表格加粗": "cmd+b",
    "多维表格斜体": "cmd+i",
    "多维表格下划线": "cmd+u",
    "多维表格删除线": "cmd+shift+x",
    "多维表格清除格式": "cmd+\\",
    "多维表格打开插入菜单": "/",
    "多维表格打开快捷键帮助": "cmd+/",
}

MACOS_APP_SHORTCUT_PRESETS: dict[str, dict[str, str]] = {
    # Chat and collaboration apps
    "com.openai.codex": {
        "发送": "cmd+enter",
        "新建会话": "cmd+n",
    },
    "com.bytedance.macos.feishu": {
        "发送": "enter",
        "换行": "shift+enter",
        "搜索": "cmd+k",
        "新建文档": "cmd+n",
        **_FEISHU_BITABLE_SHORTCUTS,
    },
    "com.bytedance.lark": {
        "发送": "enter",
        "换行": "shift+enter",
        "搜索": "cmd+k",
        "新建文档": "cmd+n",
        **_FEISHU_BITABLE_SHORTCUTS,
    },
    "lark": {
        "发送": "enter",
        "换行": "shift+enter",
        "搜索": "cmd+k",
        "新建文档": "cmd+n",
        **_FEISHU_BITABLE_SHORTCUTS,
    },
    "飞书": {
        "发送": "enter",
        "换行": "shift+enter",
        "搜索": "cmd+k",
        "新建文档": "cmd+n",
        **_FEISHU_BITABLE_SHORTCUTS,
    },
    "com.tencent.xinwechat": {
        "发送": "enter",
        "换行": "shift+enter",
        "搜索": "cmd+f",
    },
    "com.tencent.weworkmac": {
        "发送": "enter",
        "换行": "shift+enter",
        "搜索": "cmd+f",
    },
    "com.tinyspeck.slackmacgap": {
        "发送": "cmd+enter",
        "换行": "shift+enter",
        "搜索": "cmd+g",
    },
    "ru.keepcoder.telegram": {
        "发送": "enter",
        "换行": "shift+enter",
        "搜索": "cmd+f",
    },

    # Browsers
    "com.google.chrome": {
        "地址栏": "cmd+l",
        "重新打开标签": "cmd+shift+t",
        "开发者工具": "cmd+option+i",
        "查找": "cmd+f",
    },
    "com.microsoft.edgemac": {
        "地址栏": "cmd+l",
        "重新打开标签": "cmd+shift+t",
        "开发者工具": "cmd+option+i",
        "查找": "cmd+f",
    },
    "com.apple.safari": {
        "地址栏": "cmd+l",
        "重新打开标签": "cmd+shift+t",
        "查找": "cmd+f",
        "阅读器": "cmd+shift+r",
    },
    "org.mozilla.firefox": {
        "地址栏": "cmd+l",
        "重新打开标签": "cmd+shift+t",
        "开发者工具": "cmd+option+i",
        "查找": "cmd+f",
    },

    # Editors and note tools
    "com.microsoft.vscode": {
        "命令面板": "cmd+shift+p",
        "快速打开": "cmd+p",
        "全局搜索": "cmd+shift+f",
        "格式化": "option+shift+f",
        "切换终端": "ctrl+`",
    },
    "com.todesktop.230313mzl4w4u92": {
        "命令面板": "cmd+shift+p",
        "快速打开": "cmd+p",
        "全局搜索": "cmd+shift+f",
        "格式化": "option+shift+f",
        "切换终端": "ctrl+`",
    },
    "md.obsidian": {
        "命令面板": "cmd+p",
        "快速切换": "cmd+o",
        "全局搜索": "cmd+shift+f",
    },
    "notion.id": {
        "搜索": "cmd+p",
        "新页面": "cmd+n",
        "换行": "shift+enter",
    },
    "com.apple.textedit": {
        "打开设置": "cmd+,",
    },

    # Office document tools
    "com.microsoft.word": {
        "加粗": "cmd+b",
        "斜体": "cmd+i",
        "下划线": "cmd+u",
        "插入批注": "cmd+option+a",
        "标题 1": "cmd+option+1",
        "标题 2": "cmd+option+2",
        "标题 3": "cmd+option+3",
        "项目符号列表": "cmd+shift+l",
        "打开查找": "cmd+f",
    },
    "microsoft word": {
        "加粗": "cmd+b",
        "斜体": "cmd+i",
        "下划线": "cmd+u",
        "插入批注": "cmd+option+a",
        "标题 1": "cmd+option+1",
        "标题 2": "cmd+option+2",
        "标题 3": "cmd+option+3",
        "项目符号列表": "cmd+shift+l",
        "打开查找": "cmd+f",
    },
    "com.microsoft.excel": {
        "编辑单元格": "f2",
        "单元格内换行": "option+enter",
        "自动求和": "cmd+shift+t",
        "填充向下": "cmd+d",
        "筛选": "cmd+shift+f",
        "加粗": "cmd+b",
        "打开查找": "cmd+f",
    },
    "microsoft excel": {
        "编辑单元格": "f2",
        "单元格内换行": "option+enter",
        "自动求和": "cmd+shift+t",
        "填充向下": "cmd+d",
        "筛选": "cmd+shift+f",
        "加粗": "cmd+b",
        "打开查找": "cmd+f",
    },
    "com.microsoft.powerpoint": {
        "新建幻灯片": "cmd+shift+n",
        "复制幻灯片": "cmd+shift+d",
        "开始放映": "cmd+shift+enter",
        "从当前页放映": "cmd+enter",
        "演讲者视图": "option+enter",
        "插入批注": "cmd+shift+m",
        "加粗": "cmd+b",
    },
    "microsoft powerpoint": {
        "新建幻灯片": "cmd+shift+n",
        "复制幻灯片": "cmd+shift+d",
        "开始放映": "cmd+shift+enter",
        "从当前页放映": "cmd+enter",
        "演讲者视图": "option+enter",
        "插入批注": "cmd+shift+m",
        "加粗": "cmd+b",
    },
    "com.kingsoft.wpsoffice.mac": {
        "加粗": "cmd+b",
        "斜体": "cmd+i",
        "下划线": "cmd+u",
        "插入批注": "cmd+option+a",
        "新建幻灯片": "cmd+shift+n",
        "开始放映": "cmd+shift+enter",
        "编辑单元格": "f2",
        "自动求和": "cmd+shift+t",
        "填充向下": "cmd+d",
        "筛选": "cmd+shift+f",
        "打开查找": "cmd+f",
    },
    "wps office": {
        "加粗": "cmd+b",
        "斜体": "cmd+i",
        "下划线": "cmd+u",
        "插入批注": "cmd+option+a",
        "新建幻灯片": "cmd+shift+n",
        "开始放映": "cmd+shift+enter",
        "编辑单元格": "f2",
        "自动求和": "cmd+shift+t",
        "填充向下": "cmd+d",
        "筛选": "cmd+shift+f",
        "打开查找": "cmd+f",
    },
}
