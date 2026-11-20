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
