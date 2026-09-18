# 变更全流程 SOP

> 本文件定义「从需求进来到 commit 沉淀」的完整流程。各模板按需加载：
> 写前 → `proposal.md`；写中 → `coding.md`；打灯 → `review.md`；记录 → 本目录其余模板。

## 时间戳约定（精确到秒）

- 人类可读：`YYYY-MM-DD HH:MM:SS`（本地时区），用于报告 / 修复记录 / 台账正文。
- 目录与变更 ID（无冒号，跨平台安全）：`YYYYMMDD-HHMMSS`。
- 变更 ID = `YYYYMMDD-HHMMSS-功能名`，取「变更发起」时刻（proposal 阶段生成；历史补录取代码 commit 时间）。
- 时间一律用真实执行时间（`git log` 的 commit 时间或生成时刻），不凭记忆编造。

## 0. 入口判断
- 变更类型：新功能 / bug 修复 / 轻量修改
- 分级：轻量（免 proposal）/ 标准 / 高风险（安全/加密/DB/并发/删除旧行为）
- bug 修复 → 强制先「历史回溯」：grep `context/risk-ledger.md` + 读对应 `version/`

## 1. 写前（标准/高风险必走，轻量跳过）
1. 产出 `version/<变更ID>/proposal.md`；
2. **停下等人确认**（人确认/修改/拒绝）；
3. 未获批禁止写任何产品代码。

## 2. 写中
- 遵守 `coding.md`（架构/目录/≤300 行/依据/【推理生成】标注/测试重点）。

## 3. 写后收尾（实现完成 → 立即）
- 3.1 写代码 agent：生成 `feature.md`（基于 `git diff` 真实摘要）
- 3.2 写代码 agent：生成 `test_plan.md`
- 3.3 交接独立验证 agent：
  - 跑真实命令（pytest / typecheck / build / prompt_eval）
  - 对比 proposal vs feature（偏差 → 黄/红）
  - 按 `review.md` 打红黄绿，写 `test_report.md`
- 3.4 红黄处理：
  - 红 → 停下问人 → 修 → 在 report 追加「修复记录」→ 回到 3.3
  - 黄 → 列出风险，人决定「修 / 接受继续」

## 4. 提交与沉淀（人 commit 之后）
- 4.1 回填 commit hash 到 feature.md
- 4.2 追加一行到 `context/risk-ledger.md`（变更ID/时间(秒级)/功能/风险/黄红/hash）
- 4.3 若触发校准 → 回写 `review.md` / `coding.md`

## 5. 完成
- 下一次 bug 回溯时，这些记录就是「历史真相」。
