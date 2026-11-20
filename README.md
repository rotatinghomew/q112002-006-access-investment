# 课程机会和设备投放

申请单分 `request`、`declined`、`wait`；`declined` 表示拒绝已经提出的可行选择，`wait` 是申请本轮后选择暂等。资格以本轮审核为准。申请 `accepted_groups` 是这名申请者同意的方案编号，不代表已占有席位。
同一设备同一时段只能支撑一个班；时间按业务日及分钟记，半开区间。`stock` 是该设备在时段的总件数，班开课按 `units` 占设备。候选 `opens` 表示新增可开班，不重复计算既有班，批准时先按覆盖人数、再按成本比较同等保障的可行方案。基线与方案共享同一冻结申请底册。
接受状态来自教务回执，设备停用有到达时刻和停用时段。覆盖的对象是具备可履行席位并可由本人接受的人，拒绝和暂等不转化为发放承诺。条件时间组合仅可用于情景；各 `closures` 是独立的可能情景，同行的受影响班会同时关闭。`confirmation` 回传后，只计同一学生对相应班的当前决定。

## 资料格式

资料是匿名合成登记，不包含真实学生、真实成绩或外部访问地址。UTF-8 JSON，每张表是对象数组；`null` 表示该字段无已知值。`records/catalog.json` 记录每张表的字段。

- `applications`：申请者资格、保障组及允许的课表组合。 字段：`student`、`eligible`、`population`、`state`、`accepted_groups`。
- `groups`：可选班和开班条件。 字段：`group`、`day`、`start`、`end`、`seats`、`equipment`、`units`、`open`。
- `stock`：设备可投入数量。 字段：`equipment`、`day`、`units`。
- `plans`：同一底册上提交的可选追加投入。 字段：`plan`、`opens`、`extra_equipment`、`extra_day`、`extra_units`、`cost`。
- `floors`：拨款最低覆盖人数；各保障组分别达成。 字段：`population`、`min_covered`。
- `offers`：既有接受或被拒绝的席位。 字段：`offer`、`student`、`group`、`state`、`minute`。
- `outages`：停用件数与到达分钟。 字段：`equipment`、`day`、`start`、`end`、`units`、`received`。
- `possibilities`：待回访组和本人留下的可能班次。 字段：`student`、`visit`、`groups`。
- `closures`：共同变动时同时关闭的班。 字段：`scenario`、`groups`。
- `confirmations`：回访实际收到的回复。 字段：`student`、`group`、`response`、`received`。

## 本地查看

使用 Python 3.11 标准库，无需安装包。用 `python3 record_reader.py` 检查并列出收到的表行数；也可传入同格式资料目录。用 `python3 -m unittest discover -s tests -v` 检查资料契约。读取入口不会计算分析结果。

## 覆盖分析

`coverage.py` 只读登记资料，输出可用于实际投放决定的结论。默认停在“本轮已收到的最后一条决定”（最晚的承诺分钟或回执到达分钟），不预支此后才到达的设备停用；`outage-blast` 另看停用到货之后。所有方案共用同一冻结申请底册。

```bash
python3 coverage.py baseline          # 分母、覆盖率、保障组、承诺、未覆盖原因
python3 coverage.py plans             # 同一底册比较各投入方案；--confirm-plan 方案名 确认本轮发放
python3 coverage.py outage-blast      # 设备停用后哪些承诺需协商、剩余资源覆盖
python3 coverage.py scenarios         # 各共同变动情景下的保底/条件/需挪用比较
python3 coverage.py visits            # 相比盲目多开一班，先回访哪一组可能改变投放选择
python3 coverage.py rosters           # 调度用实名替代编号名单；--plan 方案名
python3 coverage.py group             # 无个人记录的联席分组结果
python3 coverage.py validate          # 资料引用一致性
```

各命令支持 `--as-of N`（只采用 `received`/承诺分钟不晚于 N 的记录）和 `--json`。

关键口径：

- **分母**是 `eligible` 且本轮存在申请记录的学生，不是“可分配学生”，也不是已收到邀请的人。`declined`、`wait` 留在分母，但不转化为新发放承诺。
- **承诺先保留**：`accepted` 的既有席位在批准时先占座，其班次视为已存在。设备停用或共同变动使承诺不能履行时，列入“需协商”，不改派、不悄悄换班。
- **资源**按业务日、半开区间计算：同时段所有已开班的 `units` 之和不得超过 `stock` + 方案追加 − 已到达停用件数。仅“两个新增时段覆盖同一批人”不够，还要看共享设备是否真能同时释放另一组席位。
- **回执**按学生对相应班的当前决定更新：接受加入该班、拒绝移除该班；同一人最多计一次覆盖。`confirmations` 中已回复的学生不再视为待回访，其 `possibilities` 不再重复计入。
- **条件时间只用于情景**：保底方案已占用的席位继续占用；只有假定已取得确认的那部分学生可以重排。保底资源不能同时算成条件方案已可发放。
- **方案排序**：先保住确认席位并守住各保障组最低覆盖，再比覆盖人数，最后比成本；无法全部达标时先减少总缺口。未达标的方案不会交给教务，并列出需松动的限制。
- **差距归因**：分母冻结，投放前后或停用前后的覆盖率变化只来自覆盖人数，不归因于分母变化。

`python3 -m unittest discover -s tests -v` 同时检查资料契约和分析口径。
