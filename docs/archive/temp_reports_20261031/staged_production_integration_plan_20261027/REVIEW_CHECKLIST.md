# 最小整合审查清单

状态：规划审查完成；下列实施验收项均待执行，不表示已有测试或绩效通过。

## 需求与影响

- [x] 保留原目标、四固定候选、八独立研究窗、100万/20万/5槽/实际持仓10上限。
- [x] 明确禁止调参、重训、重生信号、改活跃树、执行用户WIP入口、4GB源hash。
- [x] 核对A/B/C真实接口，区分模块既有QA与新整合验收；C独立QA不虚报PASS。
- [x] 修改范围限定一个新增输入模块、runner、raw reader/provider；复用A/C，core不改。
- [x] 检测已有raw、historical_costs、旧runner、audit输出、C loader/context；无须另造大架构。
- [x] 记录CLI当前NotImplemented、日历格式差异、anchor历史费用边界、20/21历史样本边界。
- [x] 记录CA强制中断可能性，八个尝试不能冒充八个完整净值；不得以猜测消除真实未知。

## 六关卡（执行阶段签收）

### G1 来源与需求契约

- [ ] A/B/C移入前后hash、base HEAD、实际core import路径/版本/hash、冻结QA报告全部绑定。
- [ ] 预注册、日历、两信号、canonical、CA三JSON与外部manifest摘要实测匹配；manifest无自身循环认证。
- [ ] 权重实际文件SHA与metadata/现有严格加载物证一致；无文件不能只用CLI声明hash过关。
- [ ] 每窗日期/信号完整集/空仓reset/资金/候选集合与预注册一致，E-1在E执行合法。
### G2 数据与未知传播

- [ ] canonical单文件加载，gap单独；11字段row_hash算法不变，source_sha追probe/manifest。
- [ ] known仅在临时mapping与evidence；缺字段不默认0/False，原始canonical/JSON未写回。
- [ ] SDK原始ST/停牌/前收/绝对限价逐字段来源绑定；WD/XR不当退市或CA生成证据。
- [ ] limit基于开盘与来源绝对价格，特殊日0/未知界局部拒单；完整榜不按可交易性重排。
- [ ] 生命周期/暂停缺口与实际暴露区分；完整Top5、退出需求、被拒机会均入覆盖分母。
- [ ] 单位÷100/÷100000、至少21根所需历史、未来截止隔离、缺行不伪造OHLC。
### G3 账户、费用、数量、权益语义

- [ ] 真实core→ctx→recorder→bridge每条事件一次；ctx hook唯一，公司行动不用旧provider旁路。
- [ ] 佣金双边.0002/min5、卖印花.001、双边过户.00002按实际执行日；anchor不查2020费用。
- [ ] 数量来源与适用期明确；科创200/1/100000、主板100倍/百万、创业限价30万；零股整卖合法。
- [ ] 已提交订单校验与部分成交审计区分，不能误把科创小额部分成交视为新申报。
- [ ] CA未知税探索不阻断无关事件；正权益缺阶段、同日record/ex、非整数等按C真实中断。
- [ ] finally保存CA证据/最后事件/部分账；失败窗状态不是PASS，八窗不共享record权益或账户。
### G4 静态质量

- [ ] 仅整合改动及对应测试Ruff/类型检查；基线遗留问题单列，不能拿旧门报告代替。
- [ ] 无生产代码import frozen研究脚本，无共享虚拟环境更新、源码路径偷换或活跃树写入。
### G5 行为验证

- [ ] 先跑微型接线用例及既有A/B/C相关测试：anchor、日历、21根、局部未知、observer、finally、reset、E边界。
- [ ] 记录实际命令、输出、退出码、用例数量和skip；引用历史307/18/87不充当本轮执行记录。
### G6 真实审计与目标声明

- [ ] 八次尝试均有独占目录、manifest/错误证据、输入SHA与费用/规则/CA来源；未完成窗明确列出。
- [ ] 账户与registry逐回调/逐日对账，正持股<=10、槽<=5；锁仓、应收、未上市权益与buffer残留可追溯。
- [ ] 主区间收益与同时间沪深300比较，buffer另报；四候选共同输入hash相同，固定差分不挑优调参。
- [ ] mechanical_status、coverage、production_acceptance、actual_after_tax_target_eligible分别输出。
- [ ] 税务/实施/PIT/舍入/权利/执行覆盖未闭合时维持INCOMPLETE；不把2021探索写成实际税后或前瞻成功。
