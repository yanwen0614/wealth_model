# 审查清单

适用范围：PLAN.md 的 T01～T04；T01～T03已由Generator实现，不代表独立质量门通过。

## 需求与影响
- [x] 已读根及适用模块 AGENTS、训练链路 README、归一化规范；未找到 MISTAKES.md。
- [x] 找到两个主评估入口的 LABEL_MODE 漏传及主训练 helper 的已有实现。
- [x] 找到 no_val 清空训练日期的直接证据及工厂缺少切分检查的调用链。
- [x] 明确 inclusive 日期区间与 context 输入的区别，避免将 warmup 误判为泄露。
- [x] 记录已有修改及用户限制，任务产物仅在指定临时根。
- [x] Generator 改动限制在4个生产文件、3个测试文件；扩展范围交主代理处理。
- [x] 保存旧 checkpoint/预测产物，不用修复后的代码替旧训练历史背书。

## 重复检测
- [x] train.build_parquet_data_config 已正确透传，保留现有实现。
- [x] Dataset 已校验标签模式、excess 算法和缓存隔离已有测试，不另建算法/resolver。
- [x] test_eval_preprocessing.py 的 TestBuildValLoader 可扩展，pipeline 需要补构造行为覆盖。
- [x] 未找到 create_dataloaders、no_val、训练/验证日期交叠的已有回归测试。
- [x] docs/agent 未找到三项同目标修复计划；冻结脚本与 research 不作为生产复用来源。

## 六关卡
1. 规范一致性：中文新增注释/报错，沿用现有命名；每次文件写入<=50行；不引入过时模块路径。
2. 模块边界：日期校验在数据工厂入口；评估脚本不反向 import train 配置；保留模型接口与数据实测维度。
3. 数据安全与时序：label_mode 与 checkpoint 一致；train_end<val_start；读数/fit 前拒绝；context 可入窗但不作标签。
4. 导入合规：标准库→第三方→项目内，禁止通配导入与生产依赖 frozen；优先复用已有 pandas。
5. 错误处理：使用 ValueError，消息含字段和值；非法日期/NaT、逆序、同日相接和缺必要边界不静默通过。
6. 过度防御与性能：仅常数级边界检查，不扫描 parquet，不建新配置框架，不额外 fit，不为本修复引入 GPU。
注：本机全局 quality-gate 定义另列第7项性能风险；上面第6项合并覆盖，完整保留技能所需性能审查。

## Generator 验收矩阵
- [x] T01：absolute/excess/crash_conditioned/缺键四类；捕获两个入口传入真实 ParquetDataConfig 的 label_mode。
- [x] T01：保持 scaler 对象和 role；非法模式原样透传给既有 Dataset 校验，不新增静默回退。
- [x] T02：no_val+自定义日期、no_val+默认日期、普通验证；mock main 下游并证明 main 接入。
- [x] T03：合法分离/同日/部分交叠/包含/倒序；两区间内部 start>end、非法日期及 NaT。
- [x] T03：验证有值但 train_end 缺失或 val_start 缺失拒绝；纯训练无验证可无界；单日合法区间可通过。
- [x] T03：失败路径 Dataset 构造及 scaler fit 调用次数为0；合法验证复用训练 scaler。
- [x] 回归：excess 标签算法/缓存隔离/context 窗口通过41项；不硬删 horizon+1 自然日。
- [x] 每个 bug 的单文件 RED/GREEN、定向回归及 ruff 已记录在 TDD_VERIFICATION.md。
- [x] unittest的TEMP/TMP指向任务根；无长训练、GPU推理、W4扫描、引擎/运行器改造。
- [x] 保留两个指定源码/测试文件及 memory 的已有修改，不提交推送删除，不修改记忆。
- [ ] 零售包装定向回归9项中1失败2错误，交主代理处理；独立质量门未派遣。

## 收口风险
H5硬编码、cs/mkt遗漏、零售返回训练loader、多种子漏传各自另排；不得将本计划称为完整评估/收益验收。
2026-01～08仍属探索样本，旧 no_val 模型训练边界由主代理审计；本次不恢复独立样本资格。
