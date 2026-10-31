# 2025桥接独立只读QA

日期：2026-10-29。审查树：`corporate-action-fix-20261027`，HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`。
结论：**审查版本身份FAIL；mini行为质量有条件PASS；真实A/B生产执行不可启动；目标资格INCOMPLETE。**

## 冻结身份

- 使用交付清单指定算法SHA-256、按其相对仓库路径读取。16个基线文件全部匹配；`SOURCE_HASHES_FINAL.json`自身SHA为`73aa08f4f0b075f2c311efc20d34f3a07fb952cefae4765e45341367cbf1998c`，与交付记录一致。
- 新增文件逐字节不匹配交付清单：
  - `backtest/cnn_adapter/validation_2025_bridge.py`：期望`4c637c46ebf73ca632619bdf7b0f292b0b50e472ac43a76239c29fcaa1e4ed7d`；实际`10dfcad8364fb3376ee37a542462b0011c0f9e2333a913a0c2e42fbfbbb788e9`。
  - `scripts/run_2025_ab_execution.py`：期望`af921b1f5a30575ccc6fccaa14b8cce815c2f47ca1d63f58d718f5e8b9c5363a`；实际`7f96da6cedf75da3bcf8e5358d5f88485b2c7085829d5dade4e7823109357093`。
  - `tests/unit/backtest/test_validation_2025_bridge.py`：期望`44f13ba56d66eabd00406dc4763811faf82ec143715b66d6888a68f21815d349`；实际`7388c38008c65262a84d8e10a76e41bf6a92d05e3c146b4abb683a7b3fe5ea13`。
- 路径解析与SHA算法均正确；不是查询目录错误。按当前字节审查，不能将交付哈希作为审查版本身份凭证。前后复核相同。

## 行为与输入核查

- 原始NPZ独立读取：A SHA `26bb7774808a417c99fcfc3c6b1722e357b8dd6a43dc67d0e1aa1dbc053ad79a`；B SHA `1403a48a655f2fd6bb4eaecb686387940d02928098df3405ab0cd74d374aa2ae`。两者恰有四键，均各1,180,872行；日期/代码/收益类型符合记录、有限值、232日、5,135码；dates/codes/true_ret逐元素严格一致。哈希确认文件字节身份，不能证明预测生成来源。
- 已确认配置H10检查要求唯一值10；但交付的旧本地评估JSON没有NPZ、checkpoint、config及生成时间绑定。桥接拒绝未绑定字段；目前没有独立可信报告/manifest及其外部SHA证据，故source-known未成立。
- 交付新增16项测试通过，覆盖合成真实core小账本、NAV守恒、持仓≤10、buffer无买入、日期边界、NPZ schema/hash、状态缺项与协议漂移。额外对抗测试3项通过：unknown保留原名次不补位、错误首日拒绝；报告SHA接口接受调用方自给的哈希，来源可信度仍取决于外部可信manifest。
- 实际入口只有manifest预检与桥接输出参数；帮助文本称“输入预检”，执行结果固定`NOT_STARTED`。脚本不调用`run_staged_window`，也无A/B账户配置/调用。真实core mini由单测直接调用runner通过；生产A/B全窗入口没有接通。
- 新数据准备门缺raw行情、verified states、CA、calendar、benchmark、历史费率、数量规则时返回`INCOMPLETE`，未创建输出目录。缺失真实状态/CA证据不得补造或宣称绩效。

## 验证结果

- 指定解释器`D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`，cwd为审查树。
- 新测试16项通过；staged/桥接相关116项通过；CA回归37项通过；raw行情/费用/数量/审计41项通过。合计194项；交付报告声称192项，计数已过时。
- `python -B -m ruff check --no-cache .`通过。CLI `--help`通过；空manifest门禁返回2且不建输出目录。
- 定向Pyright失败：`scripts/run_2025_ab_execution.py:188`返回`Mapping`与声明`dict`不符；`tests/unit/backtest/test_validation_2025_bridge.py:441`传入的动态Signal类型与`NpzSignal`不符。0 warnings，2 errors。
- 最初误用全局Python导致pyarrow导入错误；已按用户指定解释器复跑成功。未安装依赖、未运行训练或全年A/B。

## Verdict与问题

- **P1 身份FAIL：** 3个新增冻结文件哈希漂移，需交付方重新冻结/解释版本后才能对交付快照判PASS。
- **P1 范围缺口：** 此入口仅准备桥接文件，不是A/B生产执行器。还需接入真实输入准备、构造staged配置/provider/resolver，并分别调用真实core、保存完整账户审计和返回码，再做小型端到端验证。
- **P2 静态检查：** 修正上述两个Pyright类型错误后重验。
- **数据阻塞：** 状态PIT、公司行动/税务、行情、费用及外部可信来源材料未齐；即使mini PASS也不能判定2025绩效或目标资格。
- 此工作只评估2025已观察验证期回放探索，不构成前瞻、独立通过或干净样本验证。
- 源码审前/审后16基线哈希相同；三个新增哈希审前/审后相同。`git status --porcelain`审前后未变化；保留了原有任务脏状态，未提交、push或写真实数据。
