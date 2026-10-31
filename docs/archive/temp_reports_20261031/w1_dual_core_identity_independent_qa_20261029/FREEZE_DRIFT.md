# 最终封存：冻结完整性 FAIL

本会话只向指定 QA 目录写入；没有修改目标源码、测试、wheel 或真实输入。
首次中途快照一致；最终运行汇总脚本时，原“前后一致”断言失败，随即检查发现外部改写。
未恢复、覆盖、清理或重置这些外部改动，也未向用户请求额外权限。

| 文件 | 审前 SHA-256 | 首次漂移观测 SHA-256 |
|---|---|---|
| staged_production_inputs.py | `621614715bee614c6ba3f5a662a0fac1653f62ffc5be8eaab6035105f23a03c3` | `1213a9adf2c7dd26df22d9ee5026d79cade53f65fcd9646c9fc0cac6ff88c39d` |
| test_dual_core_identity.py | `102495417703101406520c78491a8b3ad4187dbddf549255aa374474035e8bf2` | `0159f0b3928cf41d0d40104956a5759bd33265fe5e0b0a44446368c6825c0afc` |

随后再次观测到两文件继续变化：production_inputs为`a5e3c725cbc8037c3ca0c17f96bc672ca9ca6e3ddadbb3d075f984aaacad46ab`，测试为`464dc56c019a81604e1097cc3c2d77fa5b7501202f42be8ff4fbd6248e2930ab`。
最后一次快照以 HASHES_after 与 FREEZE_DRIFT.json 为机器证据；不能把本报告当作继续更新后文件的认证。
23项中22项未变；补充4项中的原wheel、真实v12 manifest、sidecar未变，双身份测试变化。
两个 Git HEAD 和 status 路径清单没有变化：原来已经未提交/未跟踪的文件被改写，status无法表示这种内容变化。

首次漂移版本`1213a9…c39d`的静态观察（不是最后移动版本的重新验收）：

- 默认 `_verify_prepared:744-777` 新增 `_trusted_runtime_identity`、精确 sidecar字节、manifest字节及scope校验，并将runtime检查前置。
- `_validate_prepared_manifest_scope:726-735` 新增原wheel path+SHA和非空artifacts限制。
- 因此 F2/F3 应作为审前版本的实测缺陷；新版有修复意图，但本轮未动态验证其完整效果。
- 新版 `:649-650` 仍使用 `execution_end=calendar[-1]`，F5边界问题静态仍在。
- runner与attestor文件哈希未变，F1公共包装层循环proof和F4 experiment清空问题不受这两处外部改动消除。

106项、Ruff、Pyright和反例日志全部保留；它们只能归属于相应执行时的源码身份。
最终裁决仍FAIL，增加“冻结完整性未保持”原因，不为最终移动版本重用旧测试通过结论。
后续应先冻结明确字节版本，再完整复验；本次没有因检测到漂移而擅自修复代码或运行真实cutoff。
