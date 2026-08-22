"""
Multi-Agent 量化策略协同系统

Agent A (Strategist): 基于 LLM 生成 v2 策略代码
Agent B (Backtester):  调用现有回测引擎执行回测
Agent C (Analyst):     基于 LLM 分析回测结果并给出优化建议
Orchestrator:          编排闭环迭代直到策略达标
"""
