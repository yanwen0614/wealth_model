# training/ — Trainer 为唯一编排

- `trainer.py:24` `Trainer(model,config,train_loader,val_loader,criterion,optimizer,scheduler)` 依赖 `config["run_log_dir"]`（由 `log_manager` 预建），`early_stopping.py:27` 用 `np.inf`。
- `metrics.py` 仅 `calculate_latter_half_metrics` 被 `trainer.py:14,327` 调用，其余已不入训；`custom_loss.py` 已删除，损失由 `criterion/emd_loss.py` 提供。
- 改调度器沿用 `train.py:227` `ReduceLROnPlateau` 范式，`np.inf`/`verbose` 已为 numpy2/torch2.13 兼容。
