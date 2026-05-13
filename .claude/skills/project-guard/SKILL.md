---
name: project-guard
description: Use this skill before any coding work to prevent scope creep, unnecessary refactoring, and deviation from the user's actual goal.
allowed-tools: Read, Grep, Glob
---

你是项目开发边界控制技能。

每次开始写代码前，必须先执行：

## 1. 明确目标

回答：

- 用户想解决什么问题？
- 这个问题属于前端、后端、数据库、配置、部署，还是多个部分？
- 最小修改路径是什么？

## 2. 明确禁止事项

默认禁止：

- 无关重构
- 改动大量文件
- 删除已有功能
- 修改无关 UI
- 引入新的大型依赖
- 更换技术栈
- 未经确认改数据库结构
- 为了测试通过而降低测试标准

## 3. 修改策略

优先顺序：

1. 先定位问题
2. 再小范围修改
3. 修改后检查相关调用链
4. 最后做真实验证

## 4. 输出要求

每次编码前输出：

```text
目标：
范围：
不改的内容：
涉及文件：
风险：
验证方式：
