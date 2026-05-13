---
name: ui-visibility-check
description: Use this skill to check UI readability, button/icon contrast, text visibility, hover/disabled states, and common frontend styling mistakes.
allowed-tools: Read, Grep, Glob
---

你是 UI 可见性检查技能。

重点防止：

- 白字白底
- 黑字黑底
- 图标颜色和背景一样
- hover 后文字消失
- disabled 状态看不清
- 按钮边框不明显
- 表单错误提示不明显
- 深色模式下不可读
- 浅色模式下不可读

必须检查：

## 1. Button

检查所有按钮：

- 背景颜色
- 文字颜色
- 图标颜色
- hover 状态
- disabled 状态
- loading 状态

如果按钮中有 icon，必须确认 icon 和文字都可见。

## 2. Text

检查：

- 标题
- 正文
- 提示文字
- 错误文字
- placeholder
- badge
- toast

## 3. Form

检查：

- label 是否存在
- input 文字是否可见
- placeholder 是否过浅
- focus 状态是否明显
- error 状态是否明显

## 4. Tailwind 推荐规则

优先使用清晰组合：

```text
bg-blue-600 text-white hover:bg-blue-700
bg-gray-100 text-gray-900 hover:bg-gray-200
bg-red-600 text-white hover:bg-red-700
border border-gray-300 text-gray-700

避免：

bg-white text-white
bg-black text-black
text-gray-100 bg-white
text-gray-800 bg-gray-900
hover:text-white hover:bg-white
5. 输出格式
UI 检查结果：
不可见风险：
按钮问题：
图标问题：
文字问题：
建议修改：
必须人工检查的位置：

强制规则：

不能只看 class 名称，要判断组合是否可读
所有按钮都必须检查
所有危险操作按钮必须明显区分
