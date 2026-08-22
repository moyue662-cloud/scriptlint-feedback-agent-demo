# ScriptLint 八天 MVP 执行基线

> 状态：第三阶段可视化 Demo 与固定评测已完成
> 数据：人工构造 · Demo
> 分支：`codex/scriptlint-demo`

## 1. 一句话产品

ScriptLint 是面向短剧编剧团队的反馈记忆 Agent：它把用户纠正变成可确认、
可追溯、带作用域的创作规则，并在后续相似剧本审计任务中自动检索、应用或
忽略这些规则。

## 2. 赛题闭环

```text
用户提交剧本审计任务
→ Agent 规划并调用预置工具
→ 输出带证据的结果
→ 用户纠正结果
→ 生成 candidate 规则
→ 用户确认后转为 active
→ 后续相似任务检索规则
→ 显示 apply / ignore / conflict 及原因
```

## 3. 第一阶段演示结论

固定项目为《雨夜便利店》（人工构造）。用户纠正系统：女主在第 1—3 集不得
获知男主是集团继承人，且规则只约束女主。系统形成 `rule_017`，人工确认后：

1. 第 3 集出现明确身份揭示时，应用 `rule_017` 并生成违例；
2. 第 4 集出现同样行为时，因超出集数范围而忽略 `rule_017`；
3. 若另一条已确认规则要求第 3 集必须揭示身份，输出规则冲突并停止自动选择。

## 4. 第一阶段交付物

- `schemas/scriptlint.py`：规则、剧本事实、审计结果与演示数据契约；
- `services/scriptlint_audit_service.py`：确定性作用域、违例和规则冲突判断；
- `eval/fixtures/scriptlint_demo.json`：明确标注的人工构造数据；
- `scriptlint_phase1_demo.py`：可离线运行的四场景演示；
- `tests/test_scriptlint_phase1.py`：结果变化、正确忽略和冲突停止的回归测试。

## 5. 运行与验收

```powershell
py -B scriptlint_phase1_demo.py
py -B -m pytest -q -p no:cacheprovider
```

第一阶段必须证明：同一类任务在无记忆时没有规则结论，确认反馈记忆后能命中；
规则在范围外不会误用；相反规则同时有效时不会擅自裁决。

## 6. 后续开发边界

第二阶段已经接入窄场景自然语言意见提取、SQLite 候选规则、人工确认门禁、
Agent 计划和可持久化工具轨迹。运行：

```powershell
py -B scriptlint_phase2_demo.py
```

该 Demo 严格比较“无反馈”“候选未确认”“确认后”三次同类任务。第三阶段在此
基础上加入 Streamlit 工作台、双向证据展示和固定评测。当前不做自动成片、
完整剧本生成、平台接入、向量数据库、图数据库和自动覆盖剧本。

第三阶段已新增：

- `scriptlint_app.py`：可录屏的审计台、候选确认、双向证据和工具轨迹页面；
- `eval/fixtures/scriptlint_eval.json`：11 条人工构造金标准任务；
- `eval/run_scriptlint_eval.py`：无记忆 / 确认记忆双组对照；
- 记忆效果、同类错误下降、隔离、P95 后端耗时和估算 token 面板。

```powershell
py -m streamlit run app.py
```

下一阶段不再扩大功能面，重点增加少量真实用户反馈、修复易用性问题并准备路演。

第四阶段已新增：

- “用户验证”页：匿名编号、角色、闭环完成、规则正确性、清晰度、信任和使用意愿；
- 至少 3 人且规则正确率不低于 80% 的方向性门槛，样本不足时禁止显示验证通过；
- 本地 SQLite 持久化与匿名 CSV 导出，不保存姓名、联系方式或真实剧本；
- `USER_VALIDATION_PROTOCOL.md`：3–5 人主持测试协议；
- `PITCH_SCRIPT_3MIN.md`：三分钟逐段话术；
- `DEMO_CHECKLIST.md`：现场检查和无网兜底。

真实验证结果当前保持为空，必须由实际参与者完成操作后录入。
