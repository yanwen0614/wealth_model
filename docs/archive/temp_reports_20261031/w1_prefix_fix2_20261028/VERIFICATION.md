# 验证记录

## 执行环境

CNN worktree 为 `C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028`。运行 staged prefix 测试前设置：

```powershell
$env:PYTHONPATH='C:\Users\yanwen\AppData\Local\Temp\opencode\backtest-core-w1-stop-20261028\src'
uv run python -m unittest tests.unit.backtest.test_prefix_ledger_verifier tests.unit.backtest.test_staged_candidate_runner
```

结果：48 tests，全部通过。探针子进程单独分别导入原 wheel 与隔离 core，并断言导入路径及文件 SHA；cutoff 前 snapshots、trades、observer prefix 完全相同。

```text
原 wheel SHA: aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00
隔离 core SHA: 4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819
```

真实 W1 拒绝测试确认异常前没有调用 core，attempt audit 标记 `INCOMPLETE`，且未生成 execution ledger。测试目录仍会被外层 runner 创建以留存失败审计。

## 静态检查

```text
uv run ruff check <5 个指定实现/测试文件>  => All checks passed
uv run pyright <同一范围>                  => 0 errors, 0 warnings, 0 informations
```

## 环境差异与限制

未设置隔离 core `PYTHONPATH` 时，prefix 测试会把生产新参数传给原 wheel，并因旧 wheel 不支持 `stop_after_close` 而失败；该失败说明测试进程必须显式加载隔离 core。独立探针仍用另一个进程加载原 wheel，验证默认兼容路径及 mini 对照。

没有运行真实 W1、baseline/floor/ceil 12 路径、历史大重放或绩效。mini 观察序列相等不是历史 W1 等价证明。生产 proof generator 硬阻断，trusted proof pin 仍为 `None`，绩效保持锁定。

隔离 core 的 `tests.test_account_orders`：46 tests 全部通过；指定 core 文件 Ruff 通过，Pyright 为 0 errors/warnings/informations。`uv run` 在该树首次执行时创建 `.venv` 并安装 16 个依赖；完成后已移除这次新建的 `.venv`。core 源码未被该环境操作修改。
