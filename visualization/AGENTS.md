# visualization/ — 训练后出图

- `visualizer.py` 仅 `Visualizer.plot_training_curves(train_losses,val_losses,train_accs,val_accs)` 被 `train.py:254` 调用，落在 `config["run_log_dir"]/training_curve.png`。
- 依赖 `matplotlib`，无交互式入参；改图直接改 `visualizer.py`，勿在 `Trainer` 内重写绘图逻辑。
