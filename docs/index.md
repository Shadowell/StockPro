# StockPro 文档中心

这里是 StockPro 当前文档的统一入口。产品行为以代码、`docs/spec.md` 和对应 Sprint 合同为准；README 面向第一次了解和运行项目的人，进度文档保留实现与验证历史。

## 先看什么

| 读者 | 建议入口 | 内容 |
| --- | --- | --- |
| 第一次了解 StockPro | [项目 README](../README.md) | 产品定位、快速开始、功能地图和架构总览 |
| 日常使用者 | [用户指南](user_guide.md) | 从数据准备到研究、回测、Paper 和复盘 |
| 本地开发/运维 | [本地运行手册](deployment.md) | 安装、隔离库 `setup_isolation_db.sh`、启动、日志、健康检查和排障 |
| 产品与研发 | [产品规格](spec.md) | 产品边界、核心对象、工作流和验收规则 |
| 前后端开发 | [技术架构](technical_architecture.md) | 组件关系、请求链路、安全与扩展边界 |
| 数据研究 | [数据架构](DATA_ARCHITECTURE.md) | Provider、PG、快照、质量和调度 |
| API/Agent 接入 | [API 指南](api.md) | 鉴权、接口域、写操作规范和 OpenAPI |
| 策略作者 | [策略中心页面合同](pages/策略中心.md) | 策略 API、版本、验证和运行限制 |

## 页面合同

13 个一级工作区与登录门禁的页面级行为契约（路由、状态、数据边界）在
[pages/](pages/) 目录下逐页维护，是前端页面实现与验收的直接依据：

[首页](pages/首页.md) · [行情](pages/行情.md) · [股票池](pages/股票池.md) · [因子库](pages/因子库.md) ·
[策略中心](pages/策略中心.md) · [回测](pages/回测.md) · [模拟盘](pages/模拟盘.md) · [盯盘](pages/盯盘.md) ·
[信号中心](pages/信号中心.md) · [监控](pages/监控.md) · [复盘中心](pages/复盘中心.md) ·
[数据中心](pages/数据中心.md) · [人工智能研发](pages/人工智能研发.md) · [登录门禁](pages/登录门禁.md)

## 产品事实入口

- [产品规格](spec.md)：当前产品合同。
- [开发进度](progress.md)：按时间记录已完成实现、实际验证和已知缺口；不是安装手册。
- [Sprint 合同](contracts/)：具体迭代的范围、边界和验收证据。当前合同的指向文件是 [contracts/active.md](contracts/active.md)；文件名包含 `active-` 不代表仍在开发，先看正文 `Status`。
- [A 股研究路线](ashare-research-roadmap.md)：重建前的研究平台专业化路线，已被 BitPro-first 重建接续。
- [API 指南](api.md)：人工维护的稳定入口；健康/鉴权主入口为 `/api/*`，当前业务域为 `/api/v2/*`，完整字段以运行中的 OpenAPI 为准。

## 设计、架构与运行

- [技术架构](technical_architecture.md)
- [数据架构](DATA_ARCHITECTURE.md)
- [本地运行手册](deployment.md)
- [本地运行手册](deployment.md) 中的启动、停止、验证和部署入口

## 历史材料

- [QA 目录](qa/README.md)：人工审查报告和模板。
- [最近测试报告](test_report.md)：特定阶段的测试快照，不代表当前每次提交的结果。
- [专业化交付清单](todo.md)：2026-08-09 基线的 P0/P1/P2 审计与修复记录，已被 BitPro-first 重建取代。
- [早期功能说明](mguide/functionals.md) 与 [模块分析（归档）](archive/)：设计和实现背景。
- [历史计划](superpowers/plans/)：已执行或被替代的实施计划。
- 根目录的 Electron、优化总结与 AKShare 接口笔记已移入 [archive/](archive/)。

最后更新：2026-08-28。
