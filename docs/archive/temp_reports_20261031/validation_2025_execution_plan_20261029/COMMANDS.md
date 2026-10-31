# 后续命令（未执行）

## 仅作受限汇总探索

下面两条可尝试直接跑现有CLI。它们共享100万元、目标规模10、费用和benchmark，但只使用后复权训练parquet，且不导出逐日审计账本；成功也不能证明用户目标。

```powershell
uv run --project . python -m scripts.run_backtest --parquet "data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet" --preds "logs/preds_fullA_2025.npz" --mode target --target_size 10 --sell_buffer 0 --capital 1000000 --buy_rate 0.0002 --sell_rate 0.0002 --min_commission 5 --stamp_rate 0.0005 --transfer_rate 0.0001 --index_dir "Z:/dev/kline_index/day" --benchmark_index 000300.SH --checkpoint "logs/relative/run_20260929_162734/best_model.pth" --out_dir "C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_execution_plan_20261029/exploratory_A"
uv run --project . python -m scripts.run_backtest --parquet "data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet" --preds "logs/preds_fullB_2025.npz" --mode target --target_size 10 --sell_buffer 0 --capital 1000000 --buy_rate 0.0002 --sell_rate 0.0002 --min_commission 5 --stamp_rate 0.0005 --transfer_rate 0.0001 --index_dir "Z:/dev/kline_index/day" --benchmark_index 000300.SH --checkpoint "logs/relative/run_20260929_174047/best_model.pth" --out_dir "C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_execution_plan_20261029/exploratory_B"
```

执行前须确认两条checkpoint路径真实存在。CLI将全部NPZ日期作为信号期，不能通过命令行设定期末buffer；summary benchmark也不提供所需逐日日末账户持仓。故只作为接口冒烟/粗略探索，不得拿两份metrics.json验收目标。

## 完整审计版未来命令

当前不存在已验证的CLI命令可以把原始日线、历史状态/板别/ST、CA、历史费率、terminal buffer与逐日审计全部接好；不要拼接普通CLI参数假装具备这些能力。完成PLAN中的隔离桥接后，应先在专用worktree记录其实际脚本名与help输出，再冻结唯一命令，连续运行A/B并保存退出码。示例性质量门（路径按隔离树实际位置替换）：

```powershell
uv run --project . python -m unittest tests.unit.backtest.test_execution_audit tests.unit.backtest.test_market tests.unit.backtest.test_corporate_actions
uv run ruff check scripts/run_backtest.py backtest/cnn_adapter
uv run --project . python -m <隔离桥接模块> --help
```

以上质量门是建议验证范围，不代表本轮运行过；测试模块名须先对照隔离树现有文件确认。长时间运行须遵守项目规则用tmux/psmux、显式切换隔离树目录并短轮询，不在前台工具调用中运行整段回测。
