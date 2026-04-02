# codex-project-template

[中文](README.zh-CN.md) | [English](README.en.md)

一个用于构建 Codex 开发 harness 的最小可复用仓库模板。它的目标是帮助项目从零散对话式使用，逐步走向可持续的计划、执行、验证和交接循环。

## 项目目标

这个项目的目标是成为一个可实际使用的 `development harness coding` 模板。它不只是存放 prompt，而是提供一个轻量的交付操作系统，用来支撑：

- 外置的项目规则
- sprint 合同
- 进度交接
- QA 交接
- 统一验证入口
- 后续可扩展的 skills、automation 和 evaluator 风格审查

## 设计来源

这个模板受到 Anthropic 文章的启发：

- [Harness design: Building long-running applications with LLMs](https://www.anthropic.com/engineering/harness-design-long-running-apps)

相关记录已经沉淀在仓库中：

- [docs/references/harness-design-long-running-apps.md](docs/references/harness-design-long-running-apps.md)

这个模板承接的核心思想是：

- 把长任务拆成小的 sprint contract
- 把规划、实现、评估逻辑分开
- 把状态写进文件，而不是只留在聊天里
- 在宣布完成前显式验证结果

## 模板包含什么

- `AGENTS.md`：Codex 的稳定项目规则
- `docs/spec.md`：产品和系统意图
- `docs/progress.md`：当前状态与下一步
- `docs/contracts/`：按 sprint 组织的合同
- `docs/qa/`：QA 报告与验收记录
- `docs/references/`：设计来源和参考记录
- `scripts/check.sh`：统一验证入口
- `.agents/skills/`：可选的本地高频 workflow skills

## 推荐使用方式

1. 把这个模板复制到一个新项目仓库里。
2. 根据项目实际情况修改 `AGENTS.md`。
3. 用真实产品目标替换 `docs/spec.md`。
4. 基于 `docs/contracts/sprint-template.md` 创建第一轮 sprint。
5. 让 Codex 按下面的循环工作：
   - 读取 `AGENTS.md`
   - 读取 `docs/spec.md`
   - 读取 `docs/progress.md`
   - 只实现当前 active sprint contract
   - 运行 `./scripts/check.sh`
   - 更新 `docs/progress.md`
   - 把 QA 结论写入 `docs/qa/`

## 核心思路

这个模板围绕一个轻量 harness 构建：

1. 把状态写进文件，而不是只放在聊天里。
2. 用小而可验证的 sprint contract 推进工作。
3. 把实现和 QA 审查分离。
4. 保持一个统一的验证命令。
5. 记录进度，保证下一次 Codex 会话可以无缝继续。

## 后续迭代计划

这个仓库会分阶段演进，而不是一开始就变成一个庞大的全功能 harness。

### 阶段 1：最小交付 harness

- 稳定 `AGENTS.md`、`spec`、`progress`、`contracts`、`qa` 这些核心文件。
- 使用 `scripts/check.sh` 作为统一验证入口。
- 在真实项目中证明这套循环有效。

### 阶段 2：更强的验证能力

- 加入项目级 smoke check。
- 根据需要补充浏览器或 API 验收检查。
- 让 QA 报告更接近 evaluator 风格审查。

### 阶段 3：抽取 skills

- 把高频重复任务抽成本地 skills。
- 优先保留 contract 编写和 QA review 这类高价值 skill。
- 只有当 workflow 真正重复时才继续扩展。

### 阶段 4：后台执行

- 增加适合 automation 的约定。
- 定义哪些任务可以在无人值守情况下继续。
- 只有当验证稳定后才引入 worktree 或后台运行。

### 阶段 5：插件化或团队分发

- 把这套 harness 打磨成适合团队复用的形式。
- 等 workflow 充分验证后，再考虑走向 plugin 分发。

## 建议的第一轮 Sprint

对于一个全新项目，建议第一轮 sprint 先完成：

- 一条主用户路径
- 最小测试或 smoke check
- 初始进度记录

## 备注

- 这个模板刻意保持轻量。
- 只有在 workflow 真正有价值时再继续加结构。
- 设计思路优先沉淀到 `docs/references/`，不要埋在聊天历史里。
