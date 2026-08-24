# StockPro 文档中心

这里是 StockPro 当前文档的统一入口。产品行为以代码、`docs/spec.md` 和对应 Sprint 合同为准；README 面向第一次了解和运行项目的人，进度文档保留实现与验证历史。

## 先看什么

| 读者 | 建议入口 | 内容 |
| --- | --- | --- |
| 第一次了解 StockPro | [项目 README](../README.md) | 产品定位、功能地图、架构和快速开始 |
| 日常使用者 | [用户指南](user_guide.md) | 从数据准备到研究、回测、Paper 和复盘 |
| 本地开发/运维 | [本地运行手册](deployment.md) | 安装、隔离库 `setup_isolation_db.sh`、启动、日志、健康检查和排障 |
| 产品与研发 | [产品规格](spec.md) | 产品边界、核心对象、工作流和验收规则 |
| 当前交付 | [专业化交付清单](todo.md) | 当前唯一优先级队列、问题状态与统一验收门槛 |
| 前后端开发 | [技术架构](technical_architecture.md) | 组件关系、请求链路、安全与扩展边界 |
| 数据研究 | [数据架构](DATA_ARCHITECTURE.md) | Provider、PG、快照、质量和调度 |
| API/Agent 接入 | [API 指南](api.md) | 鉴权、接口域、写操作规范和 OpenAPI |
| 策略作者 | [策略开发说明](../strategies/README.md) | 策略 API、版本、验证和运行限制 |
| 代码使用与分发 | [MIT License](../LICENSE) | 源代码授权范围与免责声明 |

## 产品事实入口

- [产品规格](spec.md)：当前产品合同。
- [开发进度](progress.md)：按时间记录已完成实现、实际验证和已知缺口；不是安装手册。
- [Sprint 合同](contracts/)：具体迭代的范围、边界和验收证据。文件名包含 `active-` 不代表当前仍在开发，先看正文的 `Status`。
- [当前专业化合同](contracts/active-platform-professionalization.md)：2026-08-09 起的当前 Active 合同。
- [专业化交付清单](todo.md)：全页面审计后的 P0/P1/P2 实施顺序与完成证据。
- [A 股研究路线](ashare-research-roadmap.md)：研究平台专业化路线和长期方向。
- [API 指南](api.md)：人工维护的稳定入口；完整字段以运行中的 OpenAPI 为准。

## 设计、架构与运行

- [技术架构](technical_architecture.md)
- [数据架构](DATA_ARCHITECTURE.md)
- [本地运行手册](deployment.md)
- [前端开发说明](../frontend/README.md)
- [脚本使用说明](../SCRIPTS_USAGE.md)

## QA 与历史材料

- [QA 目录](qa/README.md)：人工审查报告和模板。
- [最近测试报告](test_report.md)：特定阶段的测试快照，不代表当前每次提交的结果。
- [页面/模块分析](modules/) 与 [早期功能说明](mguide/functionals.md)：设计和实现背景。
- [历史计划](superpowers/plans/)：已执行或被替代的实施计划。
- 根目录的 Electron、优化总结、AKShare 接口笔记属于早期历史或 Provider 研究材料，不是当前产品合同。

最后更新：2026-08-09。
