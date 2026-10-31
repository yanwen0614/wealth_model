# 2025 状态采集预检停止报告

日期：2026-10-29
状态：未发出任何 SDK 请求；未启动全量任务。

## 停止原因

用户要求仅在确认现有授权免费额度可用且无实际付费风险时调用 SDK；费用或额度不清楚必须停止。既有材料只记录 2026-10-27 的小批调用成功和用户限定“仅使用现有权限和配额”，没有当前账户的免费额度余额、请求计费规则或零费用回执。SDK 请求函数本身没有费用上限保护，因此无法证明新请求免费。

本次没有调用 SDK、登录、读取凭据、连接数据服务，也没有启动 tmux。没有发生费用。

## 已核实的既有 API 证据

- 冻结探针：`C:/Users/yanwen/AppData/Local/Temp/opencode/state_acquisition_20261027/preflight_v1/sdk_probe_worker.py`，SHA256 `2b28f54e37a98c989744b13bdb99dfaaad24d8d7ad8562ab384bdbb66fe902c1`。
- 实际 API：`AmazingData.InfoData().get_history_stock_status(codes, is_local=False, local_path=..., begin_date=..., end_date=...)`。
- 已观察字段：`MARKET_CODE`、`TRADE_DATE`、`PRECLOSE`、`HIGH_LIMITED`、`LOW_LIMITED`、`PRICE_HIGH_LMT_RATE`、`PRICE_LOW_LMT_RATE`、`IS_ST_SEC`、`IS_SUSP_SEC`、`IS_WD_SEC`、`IS_XR_SEC`。历史样本保留字符串 flag，不代表字段语义全部核验。
- 旧小样本：2 码、两次串行请求，返回每码各 3 行；不属于本次 2025 覆盖证据，也没有证明 PIT `known_at`。
- 旧完整采集共 4,252 个 SDK 代码、86 批、1,007,108 行；审计统计缺日期 60,144、空表 239、缺字段 2,629。不能据此推断 2025 全量质量或剩余额度。

## 环境与边界

- `D:/code/quant/.venv/Scripts/python.exe` 存在；未启动该解释器。未访问或输出任何凭据。
- 旧执行器引用已清理 worktree 的临时 `.venv`，本次未复用；未安装依赖、未改共享环境。
- 没有读取或写入 Z 源库、共享 HDF、训练源；没有创建 SDK 缓存或原始数据文件。
- 本报告是本次唯一输出，位于用户指定的 `C:/Users/yanwen/AppData/Local/Temp/opencode/state_2025_probe_20261029/`。

## 可执行下一步

在服务端控制台或既有授权凭证中取得可留档的免费额度/计费证据（至少说明此次历史状态接口调用计入免费额度、当前可用量足够样本且无超额自动扣费），再继续固定 seed 的 20 码探测。随后再核对 2025 行情合并覆盖与缺口；只有样本无异常、全量额度有依据时才建立全量清单并启动独立 tmux 分批采集。
