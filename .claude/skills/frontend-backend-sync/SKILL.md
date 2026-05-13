---
name: frontend-backend-sync
description: Use this skill whenever frontend or backend code changes to ensure routes, methods, request fields, response fields, and error handling remain consistent.
allowed-tools: Read, Grep, Glob, Bash
---

你是前后端同步检查技能。

适用场景：

- 新增页面
- 新增按钮
- 新增 API
- 修改表单
- 修改接口字段
- 修改数据库模型
- 修改返回格式
- 修改错误处理

必须检查：

## 1. API 路由

- 前端请求的 URL 是否存在
- 后端 route 是否匹配
- 是否有 baseURL 问题
- 是否有代理配置问题

## 2. HTTP 方法

检查：

- GET
- POST
- PUT
- PATCH
- DELETE

前端和后端必须一致。

## 3. 请求参数

检查：

- query 参数
- path 参数
- body 参数
- form-data
- JSON 字段名

字段名必须一致。

## 4. 返回数据

检查前端使用的字段是否在后端真实返回中存在。

例如：

前端使用：

```js
data.items
data.total
data.success
后端必须真实返回这些字段。

5. 错误处理

必须检查：

后端错误格式
前端是否显示错误
loading 是否结束
用户是否知道失败原因
6. 输出格式
前端入口文件：
后端接口文件：
接口是否匹配：
字段是否匹配：
错误处理是否完整：
发现的问题：
必须修复：
验证命令：

强制规则：

不允许只修改前端
不允许只修改后端
改接口必须同步检查调用方
改字段必须全局搜索引用
