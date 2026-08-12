(() => {
  "use strict";

  document.documentElement.lang = "zh-CN";
  document.title = "PaplyAI 模型网关管理台";

  const translations = new Map(Object.entries({
    "LiteLLM": "PaplyAI",
    "🚅 LiteLLM": "◇ PaplyAI",
    "LiteLLM home": "PaplyAI 首页",
    "LiteLLM Dashboard": "PaplyAI 模型网关管理台",
    "Loading...": "正在加载…",
    "AI Gateway": "模型网关",
    "AI GATEWAY": "模型网关",
    "Virtual Keys": "访问密钥",
    "Playground": "模型调试",
    "Models + Endpoints": "模型与端点",
    "Models & Endpoints": "模型与端点",
    "Agentic": "智能体",
    "MCP Servers": "MCP 服务器",
    "Skills": "技能",
    "Guardrails": "安全护栏",
    "Policies": "策略",
    "Tools": "工具",
    "Observability": "可观测性",
    "OBSERVABILITY": "可观测性",
    "Usage": "用量统计",
    "Cost Optimization": "成本优化",
    "Logs": "调用日志",
    "Guardrails Monitor": "安全监控",
    "Access Control": "访问控制",
    "ACCESS CONTROL": "访问控制",
    "Teams": "团队",
    "Internal Users": "内部用户",
    "Organizations": "组织",
    "Access Groups": "访问组",
    "Budgets": "预算",
    "Developer Tools": "开发者工具",
    "DEVELOPER TOOLS": "开发者工具",
    "API Reference": "接口文档",
    "AI Hub": "模型中心",
    "Learning Resources": "学习资源",
    "Response Cache": "响应缓存",
    "Experimental": "实验功能",
    "SETTINGS": "设置",
    "New": "新增",
    "Account": "账户",
    "Admin": "管理员",
    "Docs": "文档",
    "Blog": "博客",
    "Login": "登录",
    "Access your LiteLLM Admin UI.": "登录 PaplyAI 模型网关管理台。",
    "Default Credentials": "默认登录凭据",
    "By default, Username is": "默认用户名为",
    "and Password is your set LiteLLM Proxy": "，密码为已设置的 LiteLLM Proxy",
    "Need to set UI credentials or SSO?": "需要设置管理台账号或单点登录？",
    "Check the documentation": "查看配置文档",
    "Username": "用户名",
    "Enter your username": "请输入用户名",
    "Password": "密码",
    "Enter your password": "请输入密码",
    "Login with SSO": "使用单点登录",
    "Every key that authenticates requests to the gateway.": "用于验证模型网关请求的全部访问密钥。",
    "+ Create New Key": "+ 新建访问密钥",
    "Create New Key": "新建访问密钥",
    "Search by key alias...": "按密钥名称搜索…",
    "Search by key alias…": "按密钥名称搜索…",
    "Columns": "显示列",
    "Filters": "筛选",
    "Key": "密钥",
    "Team": "团队",
    "User": "用户",
    "Created At": "创建时间",
    "Last Active": "最近使用",
    "Spend / Budget": "费用 / 预算",
    "Spend /": "费用 /",
    "Spend": "费用",
    "Budget Reset": "预算重置时间",
    "Budget Reset At": "预算重置时间",
    "Rows per page": "每页行数",
    "Unknown": "暂无记录",
    "Active": "正常",
    "Inactive": "停用",
    "Status": "状态",
    "Models": "模型",
    "Model": "模型",
    "Add Model": "添加模型",
    "Add New Model": "添加新模型",
    "Search": "搜索",
    "Refresh": "刷新",
    "Save": "保存",
    "Cancel": "取消",
    "Close": "关闭",
    "Edit": "编辑",
    "Delete": "删除",
    "Create": "创建",
    "Update": "更新",
    "Name": "名称",
    "Description": "说明",
    "Actions": "操作",
    "No results.": "暂无结果。",
    "No data": "暂无数据",
    "All": "全部",
    "Enabled": "已启用",
    "Disabled": "已停用",
    "On": "开启",
    "Off": "关闭",
    "Copy": "复制",
    "Copied": "已复制",
    "Settings": "设置",
    "General": "常规",
    "API Keys": "接口密钥",
    "New User": "新建用户",
    "Create User": "创建用户",
    "Invite User": "邀请用户",
    "Create Team": "创建团队",
    "New Team": "新建团队",
    "Total Spend": "累计费用",
    "Total Tokens": "Token 总量",
    "Requests": "请求数",
    "Successful Requests": "成功请求",
    "Failed Requests": "失败请求",
    "Input Tokens": "输入 Token",
    "Output Tokens": "输出 Token",
    "Cost": "费用",
    "Budget": "预算",
    "Daily": "每日",
    "Weekly": "每周",
    "Monthly": "每月",
    "Today": "今天",
    "Last 7 Days": "最近 7 天",
    "Last 30 Days": "最近 30 天",
    "Apply": "应用",
    "Reset": "重置",
    "Export": "导出",
    "View": "查看",
    "Details": "详情",
    "Back": "返回",
    "Next": "下一步",
    "Previous": "上一步",
    "Page": "页码",
    "of": "/",
    "Beta": "测试版",
    "Notifications": "通知",
    "Join Slack": "加入 Slack 社区",
    "LiteLLM on GitHub": "LiteLLM GitHub 仓库",
    "Collapse sidebar": "收起侧边栏",
    "Community links": "社区链接",
    "Go to first page": "转到第一页",
    "Go to previous page": "转到上一页",
    "Go to next page": "转到下一页",
    "Go to last page": "转到最后一页",
    "Sort options for Spend or Budget": "费用或预算排序选项"
  }));

  const attributeNames = ["placeholder", "title", "aria-label"];
  const ignoredTags = new Set(["SCRIPT", "STYLE", "CODE", "PRE"]);

  function translateDynamic(value) {
    const normalized = value.replace(/\u00a0/g, " ").trim();
    let match = normalized.match(/^Showing (\d+)\s*[-–]\s*(\d+) of (\d+)$/);
    if (match) return `显示第 ${match[1]}–${match[2]} 条，共 ${match[3]} 条`;
    match = normalized.match(/^Page (\d+) of (\d+)$/);
    if (match) return `第 ${match[1]} 页，共 ${match[2]} 页`;
    match = normalized.match(/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{4})$/);
    if (match) {
      const months = {Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6,
        Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12};
      return `${match[3]}年${months[match[1]]}月${match[2]}日`;
    }
    match = normalized.match(/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{2}:\d{2}:\d{2})$/);
    if (match) {
      const months = {Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6,
        Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12};
      return `${months[match[1]]}月${match[2]}日 ${match[3]}`;
    }
    match = normalized.match(/^Account menu — Admin — signed in as (.+)$/);
    if (match) return `账户菜单 — 管理员 — 当前用户 ${match[1]}`;
    return value;
  }

  function translated(value) {
    return translations.get(value) || translateDynamic(value);
  }

  function translateTextNode(node) {
    if (!node.parentElement || ignoredTags.has(node.parentElement.tagName)) return;
    const original = node.nodeValue || "";
    const trimmed = original.trim();
    if (!trimmed) return;
    const replacement = translated(trimmed);
    if (replacement === trimmed) return;
    node.nodeValue = original.replace(trimmed, replacement);
  }

  function translateElement(element) {
    for (const attribute of attributeNames) {
      if (!element.hasAttribute(attribute)) continue;
      const value = element.getAttribute(attribute) || "";
      const replacement = translated(value.trim());
      if (replacement !== value.trim()) element.setAttribute(attribute, replacement);
    }
    if (element.tagName === "IMG" && element.getAttribute("alt") === "LiteLLM") {
      element.setAttribute("alt", "PaplyAI");
      element.setAttribute("src", "/ui/paplyai-logo.png");
    }
  }

  function translateTree(root) {
    if (root.nodeType === Node.TEXT_NODE) {
      translateTextNode(root);
      return;
    }
    if (!(root instanceof Element) && root !== document) return;
    if (root instanceof Element) translateElement(root);
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
      else translateElement(node);
    }
  }

  let scheduled = false;
  const observer = new MutationObserver((mutations) => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      for (const mutation of mutations) {
        if (mutation.type === "characterData") translateTextNode(mutation.target);
        if (mutation.type === "attributes") translateElement(mutation.target);
        for (const node of mutation.addedNodes) translateTree(node);
      }
    });
  });

  function startLocalization() {
    translateTree(document);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: attributeNames
    });
    let remainingPasses = 12;
    const timer = window.setInterval(() => {
      translateTree(document);
      remainingPasses -= 1;
      if (remainingPasses === 0) window.clearInterval(timer);
    }, 500);
  }

  // The upstream UI hydrates server-rendered React. Mutating its text before
  // hydration completes causes React mismatch errors, so localization starts
  // after the load event and one idle rendering turn.
  window.addEventListener("load", () => {
    const start = () => requestAnimationFrame(startLocalization);
    if ("requestIdleCallback" in window) window.requestIdleCallback(start);
    else window.setTimeout(start, 0);
  }, {once: true});
})();
