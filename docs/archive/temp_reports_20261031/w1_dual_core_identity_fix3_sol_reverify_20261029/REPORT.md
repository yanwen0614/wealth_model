# Fix3 Sol 独立只读 re_verify

日期：2026-10-29。最终裁决：**Mini 合成门 PASS；可信 proof／真实绩效仍 BLOCKED。**
未发现本轮新增或未关闭的 P1/P2/P3；必须修正项：**无**。本次结论来自独立合成实测和当前冻结字节，不采用 owner 的既有 PASS 替代。
项目 HEAD=`ce7d1c6e0bd64136f10759412c55f6da410f128f`；承认项目已有 fix2 未提交改动，没有恢复、提交或切换分支。

## 分层裁决

| 项目 | 裁决与范围 |
|---|---|
| Mini 机制／独立质量门 | **PASS，限定合成**；独立166项通过，身份攻击及同句柄边界探针通过 |
| 合法与恶意生产 schema 身份 | **PASS**；合法生成UNPINNED，空身份及缺runtime SHA拒绝 |
| cutoff SHA／业务行边界 | **PASS**；同句柄分块SHA、原始摘要一致、未来业务行过滤；非物理零访问 |
| 固定源码与交付完整性 | **PASS**；15/15固定源码，用户清单452项审前审后全匹配 |
| trusted pins／可信proof | pins均None且硬阻断；**BLOCKED／未证明**，UNPINNED不是可信PASS |
| 真实12路径与绩效目标 | **BLOCKED／未证明**；真实输入/PIT/费用/税务/获配仍未闭合 |

## P1 身份重置修复：已独立复现关闭

- `prefix_attestor.py:129` 在schema分支前初始化experiment；生产分支`:136-144`保留内部构造身份并核验必需字段；循环后没有再次清空。
- `:172-182`要求branch完整等于内部experiment，audit controlled_run_identity必须是dict，且六项值与内部身份匹配。缺runtime SHA或空身份不能靠None==None通过。
- 按用户要求先将主交付 `production_schema_attestor_probe.py` 原样复制到本目录，再运行副本，label=`sol_reverify`。副本SHA=`01cd8166f0965aaf47ff40e87eeb15956eac2841ab29dcbed91384579198ca7b`，与主文件相同。
- 真实v12、官方PDF、实际双core身份与15项固定源码核验均执行。仅mock `_fixed_inputs`，跳过4812项完整输入文件检查；没有读取真实业务窗口。
- 合法结果：`UNPINNED_ATTESTATOR`，候选SHA=`9d731d6215bd820612d1971dac246f124061f30099ccac8fa094c08e97345b27`。
- 空identity/audit：实际ValueError拒绝；缺少runtime_core_sha256：实际ValueError拒绝。状态与错误来自实际attestor，不是预设返回。
- `PRODUCTION_SCHEMA.log`及其命令JSON记录实际结果，副本进程exit0；夹具全部位于 `production_probe_sol_reverify/`。
- 原主目录的RED产物和首次未冻结失败记录保持不动，不把历史empty_identity_attestation文件当作本轮攻击被接受的证据。

## P2 完整信号预载修复：已独立验证

- `staged_candidate_runner.py:108-127`只打开一次pa.OSFile；SHA循环每次read(1MiB)，seek(0)后同句柄进入schema/table读取。无cutoff仍验证原始字节SHA并读取完整业务表。
- 独立 `同句柄探针.py` 使用自建1,801,532字节parquet：超过1MiB，确保不是只验证极小文件；没有使用真实信号或训练源。
- 将Path.read_bytes替换成直接AssertionError；loader仍成功。观测器保留实际pa.OSFile返回的原生句柄，断言schema与read_table收到同一对象，单次OSFile构造且正常关闭。
- 截止文件的6/8 buy_eligible故意设为None；Arrow实际返回日期仅6/4、6/7，未来业务行不进入逐行业务验证。返回SHA与整文件原始字节SHA完全一致。
- 独立完整模式控制返回6/4、6/7、6/8全部正常行；错误SHA被拒。日志 `CUTOFF_HANDLE.log`，exit0。
- 报告与源码均如实声明：完整SHA仍读取截止后物理字节；Arrow也可能读取共用page/footer/元数据。此修复消除完整raw_bytes内存预载，限制Python业务表返回行，**不证明物理零访问**，更不构成PIT认证。

## 身份、pins与完整绩效硬门

- 双环境均实际inspect.getfile：生产为主区wheel，SHA=`aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`；隔离为固定core树，SHA=`4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`。
- 默认隔离runtime在artifact前被拒。原wheel默认入口及两种允许runtime的prefix入口均先通过真实身份/scope，再到首个artifact前主动截停，没有全量prepared artifact哈希。
- 两种显式PYTHONPATH、实际import、命令/退出码见 `IDENTITY_ISOLATED.log`、`IDENTITY_ORIGINAL.log`及命令JSON；原身份/allowlist测试也在166项内通过。
- proof、attestor、external attestation root三个pins保持None；实际调用proof gate与external attestation verifier，均因未pin而ValueError硬拒绝。没有用UNPINNED放行。
- 无cutoff的非mini fractional完整绩效仍有可信proof门；cutoff-only仍要求固定W1日期、受限输入和双身份，完整main_total_return不计算。信号读取变更未修改这些门，166项含相应回归。

## 独立回归与静态检查

- 固定主区解释器 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`；显式隔离core/src;CNN工作树PYTHONPATH；长任务均在tmux，不依赖前台工具存活。
- 独立九模块：**166 tests in 223.030s，OK，0 skip，exit0**，见 `UNITTEST_166.log:187-189`。与主交付最终日志的166项227.353秒分开记录，未复用其日志冒充实跑。
- 模块：dual_core_identity、staged_production_inputs、staged_candidate_runner、prefix_ledger_verifier、prefix_attestor、fractional_scenarios、staged_allocation、staged_order_strategy、staged_execution_bridge。
- 原wheel小型生产prepare/run另起子进程：**1 test in 3.589s，OK，exit0**。166项内部生产测试也会在隔离环境下委派到清除PYTHONPATH的原wheel子进程。
- 独立Ruff `python -B -m ruff check --no-cache .` exit0；Pyright五模块，0 errors/0 warnings/0 informations，exit0；git diff --check exit0。
- 已审阅主交付CA 33项、Ruff/Pyright/pins和最终回归记录；这些文件也在用户清单完整性核验内。CA 33项没有单独重跑，不把原记录作为本会话实跑。
- 每条实际argv、cwd、PYTHONPATH、UTC起止与退出码见各 `*_命令.json`；全部汇总于 `SUMMARY.json`，tmux状态见 `TMUX_STATUS.json`。
- 主交付首次FULL_REGRESSION.log中的SHA失败发生在其未冻结阶段；最终冻结日志与本次独立回归通过。本次没有观察到源码漂移。

## 审前／审后哈希与主交付保护

- 用户给定清单本身SHA=`bf85e46178bd5dc846f669bbeeb9e5b655072938210dd97faa1ff3e1ba3615a8`，审前审后均精确一致，未更新该文件。
- 主清单实际为**452项总记录**，包含15项固定源码、2项本轮源码/测试和交付证据。本次对清单全部452项实算，审前审后均与声明匹配；没有把清单内记录的prepared输入路径进一步展开成文件检查。
- 另外记录原wheel、真实v12 manifest/sidecar与清单自身；`HASHES_before.json`和`HASHES_after.json`共456项，**前后无差异**。两树HEAD/status清单也不变。
- 当前runner SHA=`37fcf150a0c3646b44afbfe1d3c9ae2bd1e0cac7067779e4c0e050c2081bf54b`；attestor SHA=`84366a3d7f564393cb3c0d022926f403f80bd8dcf1e8e39cdb883491ac9ca6dc`。
- 固定source映射15/15真实匹配；runner更新摘要已同步。attestor本身在清单另列而非15项固定source内，不把该本机清单当独立签名根。
- v12 manifest仍为`a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；sidecar精确固定字节语义由真实identity入口校验，前后摘要不变。
- 源码审后清单见 `SOURCE_AFTER.sha256`。主交付目录无新增探针夹具、日志、报告或权限改写；提供脚本仅从独立副本运行。

## 范围限制与停止状态

- 未运行真实8分支、真实W1业务、真实6/8业务数据、12路径比较或绩效。所有新业务夹具均为本目录合成数据。
- 未遍历/哈希4812个真实prepared artifact文件，未读完整4GB训练源。生产schema探针只构造manifest内的清单映射并mock全量输入校验；真实输入完整性、canonical基线五账及PIT来源仍未证明。
- 固定SHA证明当前文件身份，不证明数据在2021年已可得。实际费用/税务/分配资格不由过滤、静态参数或UNPINNED见证闭合。
- 未修改共享项目源码、core、wheel、真实输入、主fix3交付目录或FIX3_SHA256.txt；未安装、uv同步、提交或推送。所有新文件仅在用户指定独立目录，工具写入分批≤50行。
- 只读审查完成，未发现须修复的P1/P2/P3；**必须修正项：无**。mini PASS不授权或证明真实cutoff运行成功，不解除可信proof及实际目标BLOCKED状态。
