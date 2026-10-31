# 命令与退出诊断

全部Python命令均用 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`，cwd为 `D:/code/cnn_full_20260905/cnn`。下列脚本路径统一位于本目录。

| 次序 | 实际操作/脚本 | 退出与证据 |
|---|---|---|
| 1 | `-c` 导入sys/importlib.util，输出sys.executable/version、core/contracts/account_actions spec与sys.path | 0；account_actions spec位于主区site-packages |
| 2 | `Test-Path -LiteralPath C:/Users/yanwen/AppData/Local/Temp/opencode` | True；写前核实允许的父目录 |
| 3 | `diagnose.py` 初始只读观察版 | 0；import、manifest与12行状态观察追加diagnostic.jsonl |
| 4 | `rtk rg -n` 查四个明确源码路径的data_snapshot/core调用 | 1；rg不在PATH；随后用专用Read/Grep/Glob核对，不安装工具 |
| 5 | `diagnose.py` 加入builder/provider/反例/v12复核后 | 0；local_hdf通过、两码缺失、状态缺键反例、ST反例、五manifest观察区间稳定 |
| 6 | `core_sample.py` 第一次 | 1；正常core调用及断言已运行，写诊断快照时dataclasses.asdict遇mappingproxy无法deepcopy；未改变core |
| 7 | `core_sample.py` 修正本目录序列化后 | 0；正常、执行日缺状态、限价、分红夹具四项断言通过 |
| 8 | `verify_small.py` 第一次 | 1；NumPy未公开_read_array_header；只读失败，未写结果 |
| 9 | `verify_small.py` 改用公开read_array_header_1_0/2_0后 | 0；NPZ头部/前六项、config/eval哈希、状态及单码raw哈希、HDF清单绑定完成 |
| 10 | `(Get-Date).ToString('o')` | 2026-10-29T11:55:36.5829812+08:00 |
| 11 | `seal.py` | 核本目录脚本语法、JSON/JSONL、四项样本和文件哈希；结果见DIAGNOSTIC_MANIFEST.json |

本目录保留最终可复跑脚本；诊断日志不是owner冻结交付。工具产生的前台输出另有系统工具记录，本目录记录核心原始观察与测试账户JSON。没有运行SDK、训练、年度账户循环或生产CLI执行。

四项小样本成功输出：

```text
真实行情正常 通过 持仓峰值 1 成交事件 2
执行日状态缺失 通过 持仓峰值 0 成交事件 1
买入限价无法触及 通过 持仓峰值 0 成交事件 1
真实core分红夹具 通过 持仓峰值 1 成交事件 2
```

此处“成交事件”包括零股拒绝/跳过事件；零股事件绝不能统计为实际成交。分红操作及订单人为构造，四日行情为真实本地raw；这组结果没有策略收益结论。
