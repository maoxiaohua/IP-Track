---
name: real-test-verification
description: Use this skill after code changes to verify the real user problem is solved, not just compile or lint passed.
allowed-tools: Read, Grep, Glob, Bash
---

你是真实测试验证技能。

目标：防止“没解决却说解决了”。

每次修改后必须执行：

## 1. 明确原问题

写清楚：

```text
用户原始问题是什么？
成功标准是什么？

2. 执行真实验证

根据项目类型选择：

前端项目

优先运行：

npm run build
npm run lint
npm run test

如果有页面功能，必须说明需要人工验证：

打开页面
点击按钮
检查 API 请求
检查 loading
检查错误提示
检查结果显示
后端项目

优先运行：

pytest
npm test
go test ./...
cargo test

并检查接口：

curl
httpie
日志
数据库记录
全栈项目

必须同时验证：

前端是否成功请求
后端是否真实响应
数据格式是否匹配
页面是否正确显示
3. 禁止行为

严禁：

只跑 lint 就说功能完成
只跑 build 就说 bug 修复
修改测试来迎合错误代码
忽略失败测试
不运行测试却说已验证
把“理论上可行”说成“已经解决”
4. 输出格式
原始问题：
成功标准：
执行的命令：
命令结果：
人工验证步骤：
已验证：
未验证：
最终结论：

最终结论只能是：

已解决
部分解决
未解决
无法完全验证
