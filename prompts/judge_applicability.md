# DecisionPatch 记忆适用性判断提示词

对每条已召回的 active 记忆输出 `apply`、`ignore` 或 `conflict`，并附一句可读理由。
优先使用本轮明确指令，其次是硬约束、项目级规则、团队级规则，最后才是输出偏好。
不相关的记忆必须显式 `ignore`，跨团队记忆不得被应用。仅返回严格 JSON。
