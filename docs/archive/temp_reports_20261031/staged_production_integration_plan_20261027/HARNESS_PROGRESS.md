# 最小整合进度台账

- status：PLANNED（仅分析与三件套已完成）。
- task_dir：C:/Users/yanwen/AppData/Local/Temp/opencode/staged_production_integration_plan_20261027
- requirement：四固定候选×两独立reset窗口，复用数量/runner/CA三模块，生成真实机械审计并严格保留原目标门槛。
- mistakes_md_path：用户未提供；以PLAN中的接口边界及REVIEW_CHECKLIST跟踪本轮风险，不推定其他文件。
- 当前修复轮次：0；源码修改0、测试执行0、训练0、绩效运行0、Git提交0、会话派发0。
- 三件套之外的配置、工作树、准备数据与八窗结果尚未生成；PLAN里的CLI是实施完成后的指定调用。

|task_id|name|状态|依赖|验收与交付|修复轮次|
|---|---|---|---|---|---|
|T01|冻结移植与依赖身份|待执行|主会话创建独立整合树|A四/B两/C四文件hash匹配；core import身份；冻结来源清单|0|
|T02|冻结输入与状态适配|待执行|T01|integration_inputs.json、prepared manifest、两窗日历、共享缓存、临时mapping/evidence|0|
|T03|费用与历史数量来源|待执行|T02|执行日费用表、规则配置/使用证据；anchor无2020误查；规则边界反例|0|
|T04|CA与observer闭环|待执行|T02、T03|core→ctx→recorder→bridge；hook；finally证据；严格/探索状态分层|0|
|T05|CLI与八窗调度|待执行|T04|prepare-only与run-prepared入口，四候选共享只读输入、八账户独立、逐窗错误隔离|0|
|T06|审计闭环与独立验收|待执行|T05|八次真实尝试、完整机会/持仓/订单/CA账、主/buffer基准、分层资格与六关卡|0|

## 已完成的只读核查

- [x] 读取项目AGENTS与writing-plans技能；使用用户指定目录与约束。
- [x] 核对B runner源码、真实CLI和87项定向复验记录；原生产门仍BLOCKED。
- [x] 核对A API与策略调用位置、历史费用接口、raw加载/转换、旧runner和用户WIP审计脚本。
- [x] 核对C修复树两个冻结源码和INTEGRATION/SOURCE_SHA256；未读取被禁止的旧CA树。
- [x] 实测B runner、C两源码、预注册、日历CSV、CA根manifest摘要均匹配冻结值。
- [x] 两信号与canonical仅读schema/footer和2行；Z盘仅一个代码footer/2行，无目录扫描、SQL或绩效读取。
- [x] 三件套列明路径、接口增量、CLI设计、读取规模、未知分层和原目标不能放行的门槛。

## 待解决依赖与状态传播

- C独立QA最终结论尚未在本轮确认；整合前核对应冻结文件，不能把owner自测当独立PASS。
- 新整合树与其私有产物目录由主会话创建；活跃源树只读，不stash/reset/切分支/清理。
- 实际税始终unknown；exploration允许机械账，actual_after_tax_target_eligible=false。
- 输入hash/身份冲突：共享输入BLOCKED；单窗CA不支持或真实账不变量失败：该窗INCOMPLETE并保存部分证据，其余独立窗继续。
- 全宇宙未暴露缺口仅披露；实际机会、订单、持仓或登记权益遇未知则窗口INCOMPLETE，不按零交易宣告达标。
- 后续更新本台账必须引用真实产物/日志与新冻结hash，失败修复逐轮递增；本轮没有编造执行证据。
