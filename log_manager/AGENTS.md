# log_manager/ — 日志目录创建

- `__init__.py:1` `LoggerManager(log_dir,config)` 创建 `logs/run_YYYYMMDD_HHMMSS/` 并写 `config.json`，返回 `run_log_dir` 供 `train.py:155` 注入 `Trainer`。
- `Trainer` 要求 `config["run_log_dir"]` 已存在且可 `os.makedirs`；改路径只改 `train LOG_DIR`，勿在 `Trainer` 内另建目录。
