# log_manager/ — 日志目录创建

- `__init__.py:1` `LoggerManager(log_dir,config)` 创建 `logs/run_YYYYMMDD_HHMMSS/` 并写 `config.json`，返回 `run_log_dir` 供 `train.py:155` 注入 `Trainer`。
- `Trainer` 要求 `config["run_log_dir"]` 已存在且可 `os.makedirs`；改路径只改 `train LOG_DIR`，勿在 `Trainer` 内另建目录。
- T18 轮转（保守清理）：`collect_rotation_plan(log_dir, keep_last_n=10, max_total_bytes=2GiB, exclude)` dry-run 只列清单不删；`prune_old_runs(..., dry_run=False)` 才删超限最老顶层 `run_*`；`KEEP/` 与当次 `exclude` 永不进待删。入库边界：`logs/scaler*.pkl` 运行期产物忽略，仅 `logs/KEEP/baseline/` 入库；冒烟 `run_*` 需留存手动归位。
