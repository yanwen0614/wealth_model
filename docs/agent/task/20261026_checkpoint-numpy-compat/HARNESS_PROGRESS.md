# Harness 进度：checkpoint NumPy scalar 兼容

## 状态

实现与验证完成；独立Luna安全/语义审查PASS，主会话实际复验25目标测试、58最小CI、Ruff及真实W1/W2权重，待主会话提交合入。未重训、未生成完整信号。

## 任务

- [x] 核实分支/状态及根目录、`training/AGENTS.md`。
- [x] 读取 quant-model harness 与 systematic-debugging/root-cause-tracing 约束。
- [x] 私有环境完整复现 W2 报错；payload 路径为 `optimizer.param_groups[0].lr`，对象类型为 `numpy.float64`。
- [x] 根因为 `CosineWarmup` 的 `np.cos` 回调产生 `numpy.float64`，保存在 optimizer lr 与 scheduler `_last_lr`。
- [x] TDD RED/GREEN；真实旧格式 NumPy lr 加载、未知类对象拒绝、新保存原生化、裸 state_dict 与 dict strict 加载均有测试。
- [x] 目标 checkpoint 与 walk-forward writer 25 项通过；CI 门 58 项通过；全仓 Ruff 通过。
- [x] 核心文件 Pyright 0 errors；全仓 Pyright 879 errors（既有测试/训练类型错误，未在本任务范围修复）。
- [x] 真实 W2 权重只读验收，hash/401 参数键与值/epoch/config 全部固定。
- [x] 交付 `C:/Users/yanwen/AppData/Local/Temp/opencode/checkpoint_compat_delivery_20261026.md`，等待主会话独立 QA。

## 已知证据与阻塞

- 分支 `openchamber/checkpoint-numpy-compat-20261026`；初始 `git status --short --branch` 干净。
- W2 权重 SHA256 为 `03625b7d85e31c6982c04471a7243d4cd701d1edc55b643e97f0abf4391ef4a4`；早期记录少末位4是抄录截断，原文件未变。
- 只读 pickle 结构显示 W2 有 NumPy scalar/dtype 与 `_codecs.encode` GLOBAL；三个 KEEP baseline checkpoint hash 相同且不含 NumPy GLOBAL。尚无证据可将其中任何一个认定为 W1。
- 已按授权从 W2 `.venv` 使用 `robocopy /E /XJ` 独立复制到本 worktree `.venv`（3.285GB，0 失败）；确认 `sys.prefix`、`torch.__file__` 均指向本 worktree，torch 2.12.0+cu130、NumPy 2.5.2、CUDA 13.0 且可用。
- 原始 loader 在 W2 checkpoint 上稳定抛出完整 `_pickle.UnpicklingError`，拒绝 `GLOBAL numpy._core.multiarray.scalar`；受限临时 `safe_globals` 读取后确认该值为 `numpy.float64`。完整SHA见上方记录。
- W1 正确文件 `D:/code/cnn_full_20260905/cnn/logs/relative/run_20261026_100509/best_model.pth` 已只读核对：给定 SHA 一致、epoch=1、401 参数键 strict 装入，optimizer lr 是 Python float，pickle 无 NumPy GLOBAL；与 W2 相同配置和 checkpoint 外层结构。
- W2 配置确认 scheduler=`CosineWarmup`；`training/factory.py` 的 `np.cos` 正是 optimizer lr 变为 numpy.float64 的来源。
- allowlist 最小项为 NumPy scalar、`numpy.dtype`、`numpy.dtypes.Float64DType`；去掉 dtype 后拒绝，去掉 codecs.encode 仍能加载，故不放行 codecs。对未知自定义类仍由 weights_only 拒绝。
- project 运行范围 PyTorch>=2.6（使用 safe_globals，验证版本 2.12.0+cu130），NumPy>=2.4（验证版本 2.5.2）；NumPy 1.x import 兼容分支不属于项目依赖支持范围。
- W1 文件 SHA 加载前后均为 `a1e35967234aeaf8463bebe6ec823cbd3a2ac240e9b55a778808588c90a56cde`；未读取 W1 training.log 或信号产物。KEEP baseline 仅作为额外裸 state_dict 对照。
- 主会话脚本核验各401个张量的dtype及torch.equal，不进行float转换；safe_globals前后完全相同。独立报告：临时根 `checkpoint_compat_final_qa_v2_20261027/独立安全语义审查.md`。
- writer测试Pyright在同解释器的主区/修复树基线均24项既有告警；checkpoint模块与其测试为零错误，不声称全仓或全部改动文件零告警。
