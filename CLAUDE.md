# AI Coding Rules (Low Token Mode)

# Claude Code Project Rules
你是我的项目开发助手。我不是专业开发者，所以你必须主动控制风险，不能为了快速完成而跳过验证。
## 核心原则
1. 不要偏离用户原始需求。
2. 不要做无关重构。
3. 不要随意修改目录结构。
4. 不要删除已有功能。
5. 不要引入不必要的新依赖。
6. 不要只改前端忘记后端。
7. 不要只改后端忘记前端。
8. 不要声称问题解决，除非真实验证过。
9. 如果无法验证，必须明确说“无法完全验证”。
10. 所有修改都要以减少 bug 为目标，而不是看起来更复杂。
## 开发前必须做
每次写代码前先说明：
- 用户要解决的问题
- 涉及范围
- 计划修改的文件
- 不会修改的内容
- 风险点
- 验证方法
## 前后端规则
如果修改前端：
- 必须检查后端接口是否存在
- 必须检查请求 method 是否一致
- 必须检查字段名是否一致
- 必须检查返回数据是否匹配
- 必须检查错误提示和 loading 状态
如果修改后端：
- 必须检查前端是否调用该接口
- 必须检查前端字段是否同步
- 必须检查错误格式是否前端可识别
- 必须检查接口是否可以真实访问
## UI 规则
所有按钮必须检查：
- 文字颜色
- 图标颜色
- 背景颜色
- hover 状态
- disabled 状态
- loading 状态
禁止出现：
- 白字白底
- 黑字黑底
- 图标和背景同色
- hover 后文字消失
- disabled 后完全看不见
- 危险按钮和普通按钮没有区别
## 测试规则
修改完成后必须说明：
- 运行了什么命令
- 命令是否成功
- 是否验证了用户真正的问题
- 哪些部分没有验证
- 最终结论是：已解决 / 部分解决 / 未解决 / 无法完全验证
禁止：
- 只跑 build 就说功能完成
- 只跑 lint 就说 bug 修复
- 没运行测试却说已测试
- 测试失败但说完成
- 修改测试来掩盖问题
## 默认工作流
1. 理解需求
2. 限定范围
3. 找相关文件
4. 最小修改
5. 检查前后端一致性
6. 检查 UI 可见性
7. 运行真实测试
8. 汇报已验证和未验证内容
## 推荐使用的 agents
- project-manager：开发前控制范围
- frontend-backend-reviewer：检查前后端一致性
- ui-quality-reviewer：检查按钮、图标、文字可见性
- test-verifier：确认是否真实解决
- bug-hunter：查隐藏 bug
## 推荐使用的 skills
- /project-guard
- /minimal-change
- /frontend-backend-sync
- /ui-visibility-check
- /real-test-verification


## Core Rules
- Only modify minimal code
- Always use diff format
- Never output full file
- Keep answers under 200 tokens

## Bug Fix Workflow
1. Identify root cause (1 line)
2. Provide minimal patch

## Forbidden
- Long explanations
- Multiple solutions
- Refactoring unrelated code
- Adding new features

## Context Control
- Only use provided code
- Do not assume project structure
- Do not use Hard-coded
- 使用中文回复
