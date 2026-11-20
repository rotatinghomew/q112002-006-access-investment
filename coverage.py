"""课程机会和设备投放的覆盖分析。

本工具只读登记资料，输出可用于实际投放决定的覆盖结论。核心口径：

* 分母是“有资格且本轮有申请记录”的学生（``eligible`` 且存在申请行），
  不是“可分配学生”，也不是已经收到邀请的人。
* 只有状态为 ``request`` 的学生可以接受新席位；``declined``（已收到可行选项
  但拒绝）与 ``wait``（申请后选择先等一轮）仍进入分母，但不转化为发放承诺。
* 已接受的席位（``offers`` 中 ``accepted``）是承诺，其班次视为已存在，批准时
  先保留。不能履行时列为“需协商”，不得悄悄改派，也不把该生改记到别的班。
* 设备按业务日、半开区间计算；一个实际开出的班按 ``units`` 占用设备，同时段
  所有开班占用之和不得超过 ``stock`` 加方案追加、减已到达的停用件数。
* ``confirmations`` 按“同一学生对相应班的当前决定”更新：接受加入该班，拒绝
  移除该班；同一人最多在一个可行组合中计为已覆盖。
* ``possibilities`` 是尚未回访的可能班次，只在条件情景中使用；保底席位在条件
  方案中继续占用，不能同时算成条件方案已可发放。
* 所有方案共用同一冻结申请底册；覆盖率变化不归因于分母变化。

时点：``baseline``/``plans``/``scenarios``/``visits``/``rosters``/``group`` 默认
停在最晚的承诺或回执（本轮已收到的最后一条决定），不预支此后到达的设备停用；
``outage-blast`` 默认看停用到达之后。可用 ``--as-of N`` 覆盖。

命令：

    python3 coverage.py baseline
    python3 coverage.py plans
    python3 coverage.py plans --confirm-plan 跨日补位
    python3 coverage.py outage-blast [--plan 跨日补位]
    python3 coverage.py scenarios
    python3 coverage.py visits
    python3 coverage.py rosters [--plan 跨日补位]
    python3 coverage.py group
    python3 coverage.py validate

所有命令都可加 ``--json`` 输出机器可读结构。
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent / "records"
MAX_CUTOFF = math.inf


# ---------------------------------------------------------------------------
# 登记类型


@dataclass(frozen=True)
class Group:
    group: str
    day: int
    start: int
    end: int
    seats: int
    equipment: str
    units: int
    open: bool


@dataclass(frozen=True)
class Application:
    student: str
    eligible: bool
    population: str
    state: str
    accepted_groups: tuple[str, ...]


@dataclass(frozen=True)
class Offer:
    offer: str
    student: str
    group: str
    state: str
    minute: int


@dataclass(frozen=True)
class Outage:
    equipment: str
    day: int
    start: int
    end: int
    units: int
    received: int

    def hits(self, group: Group) -> bool:
        return (
            self.equipment == group.equipment
            and self.day == group.day
            and group.start < self.end
            and self.start < group.end
        )


@dataclass(frozen=True)
class Confirmation:
    student: str
    group: str
    response: str
    received: int


@dataclass(frozen=True)
class Possibility:
    student: str
    visit: str
    groups: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    plan: str
    opens: tuple[str, ...]
    extra_equipment: str | None
    extra_day: int | None
    extra_units: int
    cost: int


@dataclass
class Records:
    applications: dict[str, Application]
    groups: dict[str, Group]
    stock: dict[tuple[str, int], int]
    plans: dict[str, Plan]
    floors: dict[str, int]
    offers: list[Offer]
    outages: list[Outage]
    possibilities: list[Possibility]
    closures: dict[str, tuple[str, ...]]
    confirmations: list[Confirmation]

    @classmethod
    def load(cls, folder: Path = ROOT) -> "Records":
        schema = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
        tables: dict[str, list[dict]] = {}
        for table, columns in schema.items():
            rows = json.loads((folder / f"{table}.json").read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError(f"{table} 不是行数组")
            for index, row in enumerate(rows, 1):
                if not isinstance(row, dict) or set(row) != set(columns):
                    raise ValueError(f"{table} 第 {index} 行字段与目录不符")
            tables[table] = rows
        return cls.from_tables(tables)

    @classmethod
    def from_tables(cls, tables: Mapping[str, Sequence[Mapping]]) -> "Records":
        groups = {
            row["group"]: Group(
                group=row["group"],
                day=row["day"],
                start=row["start"],
                end=row["end"],
                seats=row["seats"],
                equipment=row["equipment"],
                units=row["units"],
                open=row["open"],
            )
            for row in tables["groups"]
        }
        applications = {
            row["student"]: Application(
                student=row["student"],
                eligible=row["eligible"],
                population=row["population"],
                state=row["state"],
                accepted_groups=tuple(row["accepted_groups"]),
            )
            for row in tables["applications"]
        }
        return cls(
            applications=applications,
            groups=groups,
            stock={(row["equipment"], row["day"]): row["units"] for row in tables["stock"]},
            plans={
                row["plan"]: Plan(
                    plan=row["plan"],
                    opens=tuple(row["opens"]),
                    extra_equipment=row["extra_equipment"],
                    extra_day=row["extra_day"],
                    extra_units=row["extra_units"],
                    cost=row["cost"],
                )
                for row in tables["plans"]
            },
            floors={row["population"]: row["min_covered"] for row in tables["floors"]},
            offers=[
                Offer(
                    offer=row["offer"],
                    student=row["student"],
                    group=row["group"],
                    state=row["state"],
                    minute=row["minute"],
                )
                for row in tables["offers"]
            ],
            outages=[
                Outage(
                    equipment=row["equipment"],
                    day=row["day"],
                    start=row["start"],
                    end=row["end"],
                    units=row["units"],
                    received=row["received"],
                )
                for row in tables["outages"]
            ],
            possibilities=[
                Possibility(
                    student=row["student"],
                    visit=row["visit"],
                    groups=tuple(row["groups"]),
                )
                for row in tables["possibilities"]
            ],
            closures={row["scenario"]: tuple(row["groups"]) for row in tables["closures"]},
            confirmations=[
                Confirmation(
                    student=row["student"],
                    group=row["group"],
                    response=row["response"],
                    received=row["received"],
                )
                for row in tables["confirmations"]
            ],
        )

    # -- 派生口径 -----------------------------------------------------------
    def eligible_applicants(self) -> list[Application]:
        """覆盖率分母：本轮有资格且有申请记录的人。"""
        return [a for a in self.applications.values() if a.eligible]

    def candidates(self) -> list[Application]:
        """可以接受新发放的人。"""
        return [a for a in self.eligible_applicants() if a.state == "request"]

    def denominator(self) -> list[str]:
        return sorted(a.student for a in self.eligible_applicants())

    def baseline_plan(self) -> Plan | None:
        return next(
            (p for p in self.plans.values() if not p.opens and not p.extra_units), None
        )

    def snapshot_cutoff(self) -> float:
        """本轮已收到的最后一条决定；此后才到达的停用不提前计入。"""
        minutes = [o.minute for o in self.offers] + [c.received for c in self.confirmations]
        return max(minutes, default=0)

    def outage_cutoff(self) -> float:
        latest = [o.received for o in self.outages]
        return max([self.snapshot_cutoff(), *latest], default=MAX_CUTOFF)


# ---------------------------------------------------------------------------
# 资源状态


@dataclass(frozen=True)
class World:
    records: Records
    active: frozenset[str]
    stock: Mapping[tuple[str, int], int]
    cutoff: float = MAX_CUTOFF
    outages: bool = True
    label: str = ""
    # 仅因既有承诺而继续运行、本轮不再招新的班。
    held_only: frozenset[str] = frozenset()

    def capacity(self, equipment: str, day: int, minute: int) -> int:
        cap = self.stock.get((equipment, day), 0)
        if self.outages:
            for outage in self.records.outages:
                if (
                    outage.equipment == equipment
                    and outage.day == day
                    and outage.received <= self.cutoff
                    and outage.start <= minute < outage.end
                ):
                    cap -= outage.units
        return cap



def build_world(
    records: Records,
    plan: Plan | None = None,
    *,
    cutoff: float = MAX_CUTOFF,
    outages: bool = True,
    closed: Iterable[str] = (),
    label: str = "",
) -> World:
    open_groups = {g.group for g in records.groups.values() if g.open}
    active = set(open_groups)
    stock = dict(records.stock)
    if plan is not None:
        active |= set(plan.opens)
        if plan.extra_equipment is not None and plan.extra_day is not None:
            key = (plan.extra_equipment, plan.extra_day)
            stock[key] = stock.get(key, 0) + plan.extra_units
    # 已接受的席位是承诺：其班次即使未开放也要继续运行给本人，
    # 但这种“因承诺而运行”的班不再接收新学生。
    promised = {
        offer.group
        for offer in records.offers
        if offer.state == "accepted" and offer.minute <= cutoff
    }
    held_only = promised - active
    active |= promised
    active -= set(closed)
    return World(
        records=records,
        active=frozenset(active),
        stock=stock,
        cutoff=cutoff,
        outages=outages,
        label=label or (plan.plan if plan else "基准"),
        held_only=frozenset(held_only - set(closed)),
    )


# ---------------------------------------------------------------------------
# 承诺与回执


def accepted_commitments(
    records: Records, cutoff: float
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """已接受席位；同一人只保留一条，冲突交协商，不静默改派。"""
    fixed: dict[str, tuple[str, str]] = {}
    notes: dict[str, str] = {}
    for offer in sorted(records.offers, key=lambda o: (o.minute, o.offer)):
        if offer.state != "accepted" or offer.minute > cutoff:
            continue
        app = records.applications.get(offer.student)
        if app is None or not app.eligible:
            notes[offer.student] = f"承诺 {offer.offer} 的对象当前不具资格，需协商"
            continue
        if offer.student in fixed:
            notes[offer.student] = (
                f"同一人另有承诺 {fixed[offer.student][1]}（{fixed[offer.student][0]}），"
                f"不能再占 {offer.group}，需协商"
            )
            continue
        fixed[offer.student] = (offer.group, offer.offer)
    return fixed, notes


def confirmation_updates(
    records: Records, cutoff: float
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """按学生对相应班的当前决定：接受加入，拒绝移除。"""
    accepted: dict[str, set[str]] = {}
    declined: dict[str, set[str]] = {}
    for row in records.confirmations:
        if row.received > cutoff:
            continue
        if row.response == "accept":
            accepted.setdefault(row.student, set()).add(row.group)
        else:
            declined.setdefault(row.student, set()).add(row.group)
    return accepted, declined


def choices_for(
    records: Records,
    cutoff: float,
    *,
    include_possibilities: bool = False,
    possibility_students: set[str] | None = None,
    fixed: Iterable[str] = (),
) -> dict[str, tuple[str, ...]]:
    accepted, declined = confirmation_updates(records, cutoff)
    fixed_set = set(fixed)
    choices: dict[str, tuple[str, ...]] = {}
    for app in records.candidates():
        if app.student in fixed_set:
            continue
        groups = set(app.accepted_groups)
        groups |= accepted.get(app.student, set())
        groups -= declined.get(app.student, set())
        if include_possibilities and (
            possibility_students is None or app.student in possibility_students
        ):
            for p in records.possibilities:
                if p.student == app.student:
                    groups |= set(p.groups)
            groups -= declined.get(app.student, set())
        choices[app.student] = tuple(sorted(groups))
    return choices


# ---------------------------------------------------------------------------
# 精确求解


def resource_ok(world: World, group: Group, running: Sequence[Group]) -> tuple[bool, str]:
    """把 group 放进同时段已开出的班后，共享设备是否仍够用。"""
    peers = [g for g in running if g.group != group.group]
    classes = [g for g in peers if g.equipment == group.equipment and g.day == group.day]
    classes.append(group)
    points: set[int] = set()
    for cls in classes:
        points.add(cls.start)
        points.add(cls.end)
        for outage in world.records.outages:
            if (
                world.outages
                and outage.equipment == cls.equipment
                and outage.day == cls.day
                and outage.received <= world.cutoff
                and cls.start < outage.end
                and outage.start < cls.end
            ):
                points.add(max(cls.start, outage.start))
    for minute in sorted(points):
        load = sum(cls.units for cls in classes if cls.start <= minute < cls.end)
        cap = max(world.capacity(group.equipment, group.day, minute), 0)
        if load > cap:
            return False, (
                f"{group.equipment} 第 {group.day} 天 {minute} 分需 {load} 件，可用 {cap} 件"
            )
    return True, ""


@dataclass
class Solution:
    assignments: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    covered: set[str] = field(default_factory=set)
    population_counts: dict[str, int] = field(default_factory=dict)
    floors_met: dict[str, bool] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    negotiated: dict[str, str] = field(default_factory=dict)
    floors: dict[str, int] = field(default_factory=dict)

    @property
    def all_floors_met(self) -> bool:
        return all(self.floors_met.values())

    @property
    def shortfall(self) -> int:
        """各保障组最低覆盖缺口之和；用于在无法全部达标时减少总缺口。"""
        return sum(
            max(minimum - self.population_counts.get(pop, 0), 0)
            for pop, minimum in self.floors.items()
        )

    @property
    def issuable(self) -> bool:
        """可交给教务：守住保障，且没有未履行的确认席位。"""
        return self.all_floors_met and not self.negotiated

    def copy(self) -> "Solution":
        return Solution(
            assignments=dict(self.assignments),
            sources=dict(self.sources),
            covered=set(self.covered),
            population_counts=dict(self.population_counts),
            floors_met=dict(self.floors_met),
            reasons=dict(self.reasons),
            negotiated=dict(self.negotiated),
            floors=dict(self.floors),
        )


class Solver:
    """人数少，用带记忆的精确回溯；目标先守保障组，再比覆盖人数。

    同等覆盖下用字典序最小安排作确定性取舍，避免把等价解之间的换座误报为
    “挪用”。
    """

    def __init__(
        self,
        world: World,
        choices: Mapping[str, Sequence[str]],
        fixed: Mapping[str, tuple[str, str]] | None = None,
        prefer: Iterable[str] = (),
        keep: Mapping[str, str] | None = None,
    ) -> None:
        self.world = world
        self.records = world.records
        self.prefer = set(prefer)
        self.keep = dict(keep or {})
        self.choices = {
            student: tuple(
                g for g in groups if g in world.active and g not in world.held_only
            )
            for student, groups in choices.items()
        }
        self.fixed = dict(fixed or {})
        self._memo: dict[tuple, Solution | None] = {}
        self._order = sorted(
            (s for s in self.choices if s not in self.fixed),
            key=lambda s: (len(self.choices[s]), s),
        )

    def _can_add(self, group_id: str, assignment: Mapping[str, str]) -> tuple[bool, str]:
        group = self.records.groups[group_id]
        if sum(1 for g in assignment.values() if g == group_id) >= group.seats:
            return False, f"{group_id} 席位已满（{group.seats}）"
        running = [self.records.groups[g] for g in set(assignment.values())]
        return resource_ok(self.world, group, running)

    def _evaluate(self, assignment: Mapping[str, str], sources: Mapping[str, str]) -> Solution:
        covered = {
            s
            for s in assignment
            if s in self.records.applications and self.records.applications[s].eligible
        }
        counts: dict[str, int] = {}
        for student in covered:
            pop = self.records.applications[student].population
            counts[pop] = counts.get(pop, 0) + 1
        floors_met = {p: counts.get(p, 0) >= m for p, m in self.records.floors.items()}
        return Solution(
            assignments=dict(assignment),
            sources=dict(sources),
            covered=covered,
            population_counts=counts,
            floors_met=floors_met,
            floors=dict(self.records.floors),
        )

    def _better(self, candidate: Solution, current: Solution | None) -> bool:
        if current is None:
            return True
        def rank(sol: Solution) -> tuple:
            return (
                sum(1 for ok in sol.floors_met.values() if ok),
                -sol.shortfall,
                len(sol.covered),
                len(sol.covered & self.prefer),
                sum(1 for s, g in self.keep.items() if sol.assignments.get(s) == g),
            )

        new_rank, old_rank = rank(candidate), rank(current)
        if new_rank != old_rank:
            return new_rank > old_rank
        return tuple(sorted(candidate.assignments.items())) < tuple(
            sorted(current.assignments.items())
        )

    def _key(self, index: int, assignment: Mapping[str, str]) -> tuple:
        return (index, tuple(sorted(assignment.items())))

    def solve(self) -> Solution:
        assignment: dict[str, str] = {}
        sources: dict[str, str] = {}
        negotiated: dict[str, str] = {}
        for student, (group_id, source) in self.fixed.items():
            if group_id not in self.world.active:
                negotiated[student] = f"固定安排 {group_id} 本轮不能开设，需协商"
                continue
            ok, why = self._can_add(group_id, assignment)
            if not ok:
                negotiated[student] = f"固定安排 {group_id} 无法履行（{why}），需协商"
                continue
            assignment[student] = group_id
            sources[student] = source
        best = self._search(0, assignment, sources)
        result = best.copy() if best is not None else self._evaluate(assignment, sources)
        result.negotiated.update(negotiated)
        self._explain(result)
        return result

    def _search(
        self, index: int, assignment: dict[str, str], sources: dict[str, str]
    ) -> Solution | None:
        if index == len(self._order):
            return self._evaluate(assignment, sources)
        key = self._key(index, assignment)
        if key in self._memo:
            cached = self._memo[key]
            return cached.copy() if cached else None
        student = self._order[index]
        best: Solution | None = None
        for group_id in self.choices[student]:
            ok, _ = self._can_add(group_id, assignment)
            if not ok:
                continue
            assignment[student] = group_id
            sources[student] = "new"
            candidate = self._search(index + 1, assignment, sources)
            del assignment[student]
            del sources[student]
            if candidate is not None and self._better(candidate, best):
                best = candidate
        skipped = self._search(index + 1, assignment, sources)
        if skipped is not None and self._better(skipped, best):
            best = skipped
        self._memo[key] = best.copy() if best else None
        return best

    def _explain(self, sol: Solution) -> None:
        for student, app in self.records.applications.items():
            if student in sol.assignments or student in sol.negotiated:
                continue
            if not app.eligible:
                sol.reasons[student] = "不具备本轮资格，不计入分母"
                continue
            if app.state == "wait":
                sol.reasons[student] = "本人选择先等一轮，留在分母但不转为发放承诺"
                continue
            if app.state == "declined":
                sol.reasons[student] = "已有可行选项但本人拒绝，留在分母但不转为发放承诺"
                continue
            options = self.choices.get(student, ())
            if not options:
                sol.reasons[student] = self._no_option_reason(student)
                continue
            details: list[str] = []
            for group_id in options:
                if group_id not in self.world.active:
                    details.append(f"{group_id} 本轮未开设")
                    continue
                ok, why = self._can_add(group_id, sol.assignments)
                details.append(f"{group_id} 单独看可排入但未进最优解" if ok else why)
            sol.reasons[student] = "；".join(dict.fromkeys(details))

    def _no_option_reason(self, student: str) -> str:
        app = self.records.applications[student]
        accepted, declined = confirmation_updates(self.records, self.world.cutoff)
        groups = set(app.accepted_groups) | accepted.get(student, set())
        groups -= declined.get(student, set())
        if not groups:
            if app.accepted_groups:
                return "接受的班均被本人拒绝或缺席"
            return "未提交任何接受的时间组合"
        closed = [g for g in groups if g not in self.world.active]
        if len(closed) == len(groups):
            return f"接受的班均未开设（{', '.join(sorted(closed))}）"
        if closed:
            return f"部分接受的班未开设（{', '.join(sorted(closed))}）"
        held = [g for g in groups if g in self.world.held_only]
        if len(held) == len(groups):
            return (
                f"接受的班仅因原承诺继续运行、本轮不再招新"
                f"（{', '.join(sorted(held))}）"
            )
        if held:
            return f"部分接受的班本轮不再招新（{', '.join(sorted(held))}）"
        return "接受的组合未获可行资源"


# ---------------------------------------------------------------------------
# 分析入口


def analyse_conditional(
    records: Records,
    world: World,
    *,
    base: Solution,
    possibility_students: set[str],
    release: Iterable[str] = (),
    prefer: Iterable[str] = (),
) -> Solution:
    """保底方案已占用的席位继续保留，只评估条件成立后能否新增。

    ``release`` 是本次情景中假定已取得确认的学生；只有他们的保底席位可以
    重排，其余保底席位继续占用。这样既不会把保底协议的席位悄悄释放，也不会
    把同一份保底资源同时算成条件方案已可发放。
    """
    released = set(release)
    held = {
        s: (g, "held")
        for s, g in base.assignments.items()
        if s not in base.negotiated and s not in released
    }
    return analyse(
        records,
        world,
        include_possibilities=True,
        possibility_students=possibility_students,
        fixed_extra=held,
        prefer=prefer,
        keep=base.assignments,
        skip_offers=True,
    )


def analyse(
    records: Records,
    world: World,
    *,
    include_possibilities: bool = False,
    possibility_students: set[str] | None = None,
    fixed_extra: Mapping[str, tuple[str, str]] | None = None,
    prefer: Iterable[str] = (),
    keep: Mapping[str, str] | None = None,
    skip_offers: bool = False,
) -> Solution:
    if skip_offers:
        fixed, notes = {}, {}
    else:
        fixed, notes = accepted_commitments(records, world.cutoff)
    merged: dict[str, tuple[str, str]] = {
        s: (g, f"offer:{oid}") for s, (g, oid) in fixed.items()
    }
    if fixed_extra:
        merged.update(fixed_extra)
    choices = choices_for(
        records,
        world.cutoff,
        include_possibilities=include_possibilities,
        possibility_students=possibility_students,
        fixed=merged,
    )
    sol = Solver(world, choices, fixed=merged, prefer=prefer, keep=keep).solve()
    for student, note in notes.items():
        sol.negotiated.setdefault(student, note)
    for student in sol.negotiated:
        app = records.applications.get(student)
        if app and app.eligible:
            sol.reasons.setdefault(student, sol.negotiated[student])
    return sol


def floor_rows(records: Records, sol: Solution) -> list[dict]:
    rows = []
    for pop, minimum in records.floors.items():
        actual = sol.population_counts.get(pop, 0)
        rows.append(
            {
                "保障组": pop,
                "最低覆盖": minimum,
                "实际覆盖": actual,
                "是否达标": actual >= minimum,
                "缺口": max(minimum - actual, 0),
            }
        )
    return rows


def rate(covered: Iterable[str], denominator: Sequence[str]) -> str:
    return f"{len(set(covered) & set(denominator))}/{len(denominator)}"


def uncovered_rows(records: Records, sol: Solution) -> dict[str, str]:
    return {
        student: sol.reasons.get(student, "未获可行组合")
        for student in records.denominator()
        if student not in sol.covered
    }


def plan_world(
    records: Records,
    plan: Plan | None,
    cutoff: float,
    *,
    outages: bool = True,
    closed: Iterable[str] = (),
) -> World:
    return build_world(
        records,
        plan,
        cutoff=cutoff,
        outages=outages,
        closed=closed,
        label=plan.plan if plan else "基准",
    )


def ranked_plans(records: Records, cutoff: float) -> list[tuple[Plan, World, Solution]]:
    rows = []
    for plan in records.plans.values():
        world = plan_world(records, plan, cutoff)
        rows.append((plan, world, analyse(records, world)))
    return rows


def plan_rank(plan: Plan, sol: Solution) -> tuple:
    """先保住确认席位，再守保障组最低覆盖，再比覆盖人数，最后比成本。"""
    return (
        not sol.negotiated,
        sum(1 for ok in sol.floors_met.values() if ok),
        -sol.shortfall,
        len(sol.covered),
        -plan.cost,
    )


def best_plan_row(
    records: Records,
    cutoff: float,
    *,
    include_possibilities: bool = False,
    possibility_students: set[str] | None = None,
    closed: Iterable[str] = (),
) -> tuple[Plan | None, World, Solution]:
    """按“守住确认席位与保障 → 覆盖人数 → 成本低”选方案。"""
    best: tuple[Plan | None, World, Solution] | None = None
    best_key: tuple | None = None
    prefer = sorted(
        {
            s
            for students in _visit_groups(records, cutoff).values()
            for s in students
            if possibility_students is None or s in possibility_students
        }
    )
    for plan, _world, _sol in ranked_plans(records, cutoff):
        world = plan_world(records, plan, cutoff, closed=closed)
        sol = analyse(
            records,
            world,
            include_possibilities=include_possibilities,
            possibility_students=possibility_students,
            prefer=prefer,
        )
        key = plan_rank(plan, sol)
        if best_key is None or key > best_key:
            best, best_key = (plan, world, sol), key
    if best is None:
        world = build_world(records, cutoff=cutoff)
        return None, world, analyse(records, world)
    return best


def commitment_status(records: Records, world: World) -> list[dict]:
    fixed, notes = accepted_commitments(records, world.cutoff)
    running = [records.groups[g] for g, _ in fixed.values()]
    rows = []
    for offer in sorted(records.offers, key=lambda o: (o.minute, o.offer)):
        if offer.state != "accepted" or offer.minute > world.cutoff:
            continue
        row = {
            "承诺": offer.offer,
            "学生": offer.student,
            "班": offer.group,
            "发放分钟": offer.minute,
        }
        if offer.student in notes:
            row["结论"] = "需协商"
            row["说明"] = notes[offer.student]
        elif offer.group not in world.active:
            row["结论"] = "需协商"
            row["说明"] = f"{offer.group} 本轮不能开设"
        else:
            peers = [
                g for g in running
                if not (g.group == offer.group and g is not records.groups[offer.group])
            ]
            ok, why = resource_ok(
                world, records.groups[offer.group], peers + [records.groups[offer.group]]
            )
            row["结论"] = "可履行，保留原席位" if ok else "需协商"
            row["说明"] = "资源可履行" if ok else why
        rows.append(row)
    return rows


def gap(before: Solution, after: Solution, denominator: Sequence[str]) -> dict:
    return {
        "分母": len(denominator),
        "分母是否变化": False,
        "前覆盖": len(before.covered),
        "后覆盖": len(after.covered),
        "前覆盖率": rate(before.covered, denominator),
        "后覆盖率": rate(after.covered, denominator),
        "新增覆盖": sorted(after.covered - before.covered),
        "失去覆盖": sorted(before.covered - after.covered),
        "说明": "底册冻结，覆盖率变化来自覆盖人数，不是分母变化。",
    }


# ---------------------------------------------------------------------------
# 命令


def command_baseline(records: Records, as_of: int | None, as_json: bool) -> None:
    cutoff = records.snapshot_cutoff() if as_of is None else as_of
    plan = records.baseline_plan()
    world = plan_world(records, plan, cutoff)
    sol = analyse(records, world)
    denom = records.denominator()
    old_report = sorted({o.student for o in records.offers if o.state == "accepted"})
    payload = {
        "分母": len(denom),
        "分母学生": denom,
        "状态分布": {
            state: sorted(a.student for a in records.eligible_applicants() if a.state == state)
            for state in ("request", "declined", "wait")
        },
        "覆盖人数": len(sol.covered),
        "覆盖率": rate(sol.covered, denom),
        "保障组": floor_rows(records, sol),
        "承诺": commitment_status(records, world),
        "未覆盖及原因": uncovered_rows(records, sol),
        "需协商": sol.negotiated,
        "旧报告口径": {
            "口径": "只统计已有已接受席位的人",
            "人数": len(old_report),
            "学生": old_report,
            "说明": (
                f"旧报告为 {len(old_report)}/{len(old_report)}，现口径为 "
                f"{len(sol.covered)}/{len(denom)}；覆盖率差距来自分母，"
                "旧报告没有纳入未获可行选项、选择先等和拒绝的申请者。"
            ),
        },
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"分母（有资格且本轮有申请）: {payload['分母']} 人")
    for state, students in payload["状态分布"].items():
        print(f"  {state}: {', '.join(students) or '无'}")
    print(f"基准覆盖: {payload['覆盖人数']} 人（{payload['覆盖率']}）")
    print("保障组:")
    for row in payload["保障组"]:
        tail = "" if row["是否达标"] else f"（缺口 {row['缺口']}）"
        print(f"  {row['保障组']}: {row['实际覆盖']}/{row['最低覆盖']}{tail}")
    print("承诺:")
    for row in payload["承诺"]:
        print(f"  {row['承诺']} {row['学生']}→{row['班']}: {row['结论']}（{row['说明']}）")
    print("未覆盖及原因:")
    for student, reason in payload["未覆盖及原因"].items():
        print(f"  {student}: {reason}")
    old = payload["旧报告口径"]
    print(f"旧报告口径: {old['人数']} 人；{old['说明']}")


def _blocking_constraints(records: Records, world: World, sol: Solution) -> list[str]:
    notes: list[str] = []
    # 承诺不能履行时，先说明需与本人协商，而不是把它当作可用资源。
    for student, note in sol.negotiated.items():
        notes.append(f"承诺需协商: {student}（{note}）")
    for pop, minimum in records.floors.items():
        if sol.population_counts.get(pop, 0) >= minimum:
            continue
        for app in records.candidates():
            if app.population != pop or app.student in sol.covered:
                continue
            if app.student in sol.negotiated:
                notes.append(f"{pop}: {app.student} 的原有承诺需先协商处理")
                continue
            accepted, declined = confirmation_updates(records, world.cutoff)
            groups = set(app.accepted_groups) | accepted.get(app.student, set())
            groups -= declined.get(app.student, set())
            if not groups:
                notes.append(f"{pop}: {app.student} 未提交可行组合，需要本人补交时段")
                continue
            closed = [g for g in groups if g not in world.active]
            if closed:
                notes.append(f"{pop}: 需开设 {', '.join(sorted(closed))} 才能覆盖 {app.student}")
                continue
            running = [records.groups[g] for g in set(sol.assignments.values())]
            for g in sorted(groups):
                ok, why = resource_ok(world, records.groups[g], running + [records.groups[g]])
                if not ok:
                    notes.append(f"{pop}: {app.student} 受 {g} 资源限制（{why}）")
                    break
            else:
                notes.append(
                    f"{pop}: {app.student} 的可行班与已守住的保障席位争用同一时段，需增开或放宽"
                )
    return list(dict.fromkeys(notes)) or ["保障组缺口来自席位或设备总量，需增加投入或调整组合"]


def command_plans(records: Records, as_of: int | None, as_json: bool, confirm: str | None) -> None:
    cutoff = records.snapshot_cutoff() if as_of is None else as_of
    rows = ranked_plans(records, cutoff)
    baseline_covered: set[str] = set()
    for plan, _, sol in rows:
        if not plan.opens and not plan.extra_units:
            baseline_covered = set(sol.covered)
    ranked = sorted(rows, key=lambda r: plan_rank(r[0], r[2]), reverse=True)
    payload = {
        "口径": {
            "分母": len(records.denominator()),
            "排序": "先保住确认席位，再守保障组最低覆盖，再比覆盖人数，最后比成本",
        },
        "方案": [
            {
                "方案": plan.plan,
                "成本": plan.cost,
                "开设": sorted(world.active),
                "覆盖人数": len(sol.covered),
                "相对基准新增": len(sol.covered) - len(baseline_covered),
                "保障组": floor_rows(records, sol),
                "确认席位": commitment_status(records, world),
                "守住保障": sol.all_floors_met,
                "可交给教务": sol.issuable,
                "需协商": sol.negotiated,
                "未覆盖及原因": uncovered_rows(records, sol),
            }
            for plan, world, sol in rows
        ],
        "建议顺序": [plan.plan for plan, _, _ in ranked],
        "可发放方案": [plan.plan for plan, _, sol in ranked if sol.issuable],
    }
    if not payload["可发放方案"]:
        top_plan, top_world, top_sol = ranked[0]
        payload["若无方案可交给教务"] = {
            "最佳方案": top_plan.plan,
            "需松动的限制": _blocking_constraints(records, top_world, top_sol),
        }
    chosen = None
    if confirm:
        chosen = next((r for r in rows if r[0].plan == confirm), None)
        if chosen is None:
            raise SystemExit(f"没有方案 {confirm}")
        plan, world, sol = chosen
        entry = {
            "方案": plan.plan,
            "可交给教务": sol.issuable,
            "覆盖人数": len(sol.covered),
            "成本": plan.cost,
            "确认席位": commitment_status(records, world),
            "需协商": sol.negotiated,
            "名单": sorted(sol.assignments),
        }
        if sol.issuable:
            entry["结论"] = "满足确认席位与保障组最低覆盖，可确认本轮发放"
        else:
            entry["结论"] = "不能交给教务：未满足确认席位或保障组最低覆盖"
            entry["需松动的限制"] = _blocking_constraints(records, world, sol)
        payload["确认发放"] = entry
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"口径分母: {payload['口径']['分母']} 人")
    for row in payload["方案"]:
        mark = "可发放" if row["可交给教务"] else "不可发放"
        print(
            f"{row['方案']}: 覆盖 {row['覆盖人数']} 人（较基准 {row['相对基准新增']:+d}），"
            f"成本 {row['成本']}，{mark}"
        )
        for floor in row["保障组"]:
            tail = "" if floor["是否达标"] else f"（缺 {floor['缺口']}）"
            print(f"    {floor['保障组']}: {floor['实际覆盖']}/{floor['最低覆盖']}{tail}")
        for student, note in row["需协商"].items():
            print(f"    需协商 {student}: {note}")
    print("建议顺序:", " → ".join(payload["建议顺序"]))
    if "若无方案可交给教务" in payload:
        block = payload["若无方案可交给教务"]
        print(f"若无方案能守住保障（最佳为 {block['最佳方案']}），需松动:")
        for note in block["需松动的限制"]:
            print("  -", note)
    if chosen:
        entry = payload["确认发放"]
        print("确认发放:", json.dumps(entry, ensure_ascii=False, indent=2))


def _confirmed_students(records: Records, cutoff: float) -> set[str]:
    """回访已实际收到回复的学生；其余可能性只作情景。"""
    return {row.student for row in records.confirmations if row.received <= cutoff}


def _visit_groups(records: Records, cutoff: float) -> dict[str, list[str]]:
    visits: dict[str, list[str]] = {}
    confirmed = _confirmed_students(records, cutoff)
    for p in records.possibilities:
        if p.student in confirmed:
            continue
        visits.setdefault(p.visit, []).append(p.student)
    return visits


def command_outage(
    records: Records, as_of: int | None, as_json: bool, plan_name: str | None
) -> None:
    # 先看停用到达前的已确认方案，再看停用到达后的可履行情况。
    snapshot = records.snapshot_cutoff()
    cutoff = records.outage_cutoff() if as_of is None else as_of
    if plan_name:
        plan = records.plans.get(plan_name)
        if plan is None:
            raise SystemExit(f"没有方案 {plan_name}")
        confirmed_plan = plan
    else:
        confirmed_plan, _, _ = best_plan_row(records, snapshot)
        plan = confirmed_plan
    before_world = plan_world(records, plan, snapshot, outages=False)
    after_world = plan_world(records, plan, cutoff, outages=True)
    before = analyse(records, before_world)
    after = analyse(records, after_world)
    payload = {
        "方案": plan.plan if plan else "基准",
        "停用": [
            {
                "设备": o.equipment,
                "日": o.day,
                "时段": f"{o.start}-{o.end}",
                "件数": o.units,
                "到达分钟": o.received,
            }
            for o in records.outages
            if o.received <= cutoff
        ],
        "承诺处理": commitment_status(records, after_world),
        "前后差距": gap(before, after, records.denominator()),
        "停用前覆盖": sorted(before.covered),
        "停用后覆盖": sorted(after.covered),
        "停用后未覆盖及原因": uncovered_rows(records, after),
        "剩余资源下的保障组": floor_rows(records, after),
        "需协商": after.negotiated,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"方案: {payload['方案']}")
    print("停用:", payload["停用"])
    print("承诺处理:")
    for row in payload["承诺处理"]:
        print(f"  {row['承诺']} {row['学生']}→{row['班']}: {row['结论']}（{row['说明']}）")
    g = payload["前后差距"]
    print(f"覆盖: {g['前覆盖']} → {g['后覆盖']} 人（{g['前覆盖率']} → {g['后覆盖率']}）")
    print("失去覆盖:", ", ".join(g["失去覆盖"]) or "无")
    print("说明:", g["说明"])
    print("停用后未覆盖及原因:")
    for student, reason in payload["停用后未覆盖及原因"].items():
        print(f"  {student}: {reason}")
    print("剩余资源下的保障组:")
    for row in payload["剩余资源下的保障组"]:
        tail = "" if row["是否达标"] else f"（缺 {row['缺口']}）"
        print(f"  {row['保障组']}: {row['实际覆盖']}/{row['最低覆盖']}{tail}")


def _scenario_row(
    records: Records, plan: Plan, cutoff: float, closed: Sequence[str]
) -> dict:
    world = plan_world(records, plan, cutoff, closed=closed)
    definite = analyse(records, world)
    conditional_world = plan_world(records, plan, cutoff, closed=closed)
    pending = [
        s for students in _visit_groups(records, cutoff).values() for s in students
    ]
    # 条件方案：保底席位继续占用（held），只在此基础上评估可新增。
    held = analyse_conditional(
        records,
        conditional_world,
        base=definite,
        possibility_students=set(pending),
        prefer=pending,
    )
    free_world = plan_world(records, plan, cutoff, closed=closed)
    free = analyse(
        records,
        free_world,
        include_possibilities=True,
        possibility_students=set(pending),
        prefer=pending,
    )
    # 逐回访组：
    #   * 保守口径只动本组学生自己的保底席位，其余保底资源继续占用；
    #   * 若允许为这组确认重排，则看会把哪些原定覆盖挪出去。
    visits = []
    for visit, students in _visit_groups(records, cutoff).items():
        visit_world = plan_world(records, plan, cutoff, closed=closed)
        held_solo = analyse_conditional(
            records,
            visit_world,
            base=definite,
            possibility_students=set(students),
            release=students,
            prefer=students,
        )
        free_world = plan_world(records, plan, cutoff, closed=closed)
        free_solo = analyse(
            records,
            free_world,
            include_possibilities=True,
            possibility_students=set(students),
            prefer=students,
        )
        visits.append(
            {
                "回访组": visit,
                "可能学生": sorted(students),
                "确认后新增": sorted(held_solo.covered - definite.covered),
                "若确认需挪出的保底学生": sorted(definite.covered - held_solo.covered),
                "须先取得确认才可释放": sorted(
                    s
                    for s, g in definite.assignments.items()
                    if s in held_solo.covered
                    and held_solo.assignments.get(s) == g
                    and s in students
                ),
                "全面重排后覆盖人数（仅诊断）": len(free_solo.covered),
            }
        )
    return {
        "方案": plan.plan,
        "成本": plan.cost,
        "保底覆盖": sorted(definite.covered),
        "保底人数": len(definite.covered),
        "保底保障组": floor_rows(records, definite),
        "确认取得后覆盖人数": len(held.covered),
        "确认取得后新增": sorted(held.covered - definite.covered),
        "为确认需挪出的保底学生": sorted(definite.covered - held.covered),
        "条件保障组": floor_rows(records, held),
        "全面重排覆盖人数（仅诊断）": len(free.covered),
        "回访组": visits,
        "需协商": {**definite.negotiated, **held.negotiated},
    }


def command_scenarios(records: Records, as_of: int | None, as_json: bool) -> None:
    cutoff = records.snapshot_cutoff() if as_of is None else as_of
    scenarios = []
    for name, members in records.closures.items():
        rows = [_scenario_row(records, plan, cutoff, members) for plan in records.plans.values()]
        definite_best = sorted(
            rows,
            key=lambda r: (
                all(f["是否达标"] for f in r["保底保障组"]),
                r["保底人数"],
                -r["成本"],
            ),
            reverse=True,
        )[0]
        conditional_pool = [
            r
            for r in rows
            if r["确认取得后新增"] or r["为确认需挪出的保底学生"]
        ]
        conditional_best = (
            sorted(
                conditional_pool,
                key=lambda r: (
                    all(f["是否达标"] for f in r["条件保障组"]),
                    r["确认取得后覆盖人数"],
                    -r["成本"],
                ),
                reverse=True,
            )[0]
            if conditional_pool
            else None
        )
        scenarios.append(
            {
                "情景": name,
                "关闭班": list(members),
                "保底方案": definite_best["方案"],
                # 可交给教务：保障达标且没有未履行的承诺；关闭班导致的
                # 承诺冲突必须先由教务协商，不能随情景方案一起发出。
                "可交给教务的方案": [
                    r["方案"]
                    for r in rows
                    if all(f["是否达标"] for f in r["保底保障组"])
                    and not r["需协商"]
                ],
                "条件成立后最佳方案": conditional_best["方案"] if conditional_best else None,
                "条件成立后最佳方案的说明": (
                    "保底方案仍先保留；条件方案只计算新取得的确认，"
                    "并为这些确认挪出必要的保底学生。"
                ),
                "方案比较": rows,
            }
        )
    payload = {
        "说明": (
            "各情景独立，不能跨情景相加；同一情景内保底席位在条件方案中继续占用。"
            "条件分析只用于情景，不代表已取得确认。"
        ),
        "情景": scenarios,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(payload["说明"])
    for scenario in scenarios:
        print(f"\n情景「{scenario['情景']}」关闭 {', '.join(scenario['关闭班']) or '无'}")
        for row in scenario["方案比较"]:
            ok = all(f["是否达标"] for f in row["保底保障组"])
            if not ok:
                mark = "保障不足"
            elif row["需协商"]:
                mark = "保障达标但有承诺需协商"
            else:
                mark = "可交给教务"
            print(
                f"  {row['方案']}: 保底 {row['保底人数']} 人，{mark}，成本 {row['成本']}"
            )
            for floor in row["保底保障组"]:
                tail = "" if floor["是否达标"] else f"（缺 {floor['缺口']}）"
                print(f"      {floor['保障组']}: {floor['实际覆盖']}/{floor['最低覆盖']}{tail}")
            print(
                f"      确认取得后新增: "
                f"{', '.join(row['确认取得后新增']) or '无'}"
                f"；为确认需挪出保底: "
                f"{', '.join(row['为确认需挪出的保底学生']) or '无'}"
            )
            print(
                f"      确认取得后覆盖 {row['确认取得后覆盖人数']} 人"
                f"（全面重排仅诊断: {row['全面重排覆盖人数（仅诊断）']} 人）"
            )
            for visit in row["回访组"]:
                print(
                    f"      {visit['回访组']}（{', '.join(visit['可能学生'])}）: "
                    f"确认后新增 {', '.join(visit['确认后新增']) or '无'}"
                    f"；若确认需挪出 {', '.join(visit['若确认需挪出的保底学生']) or '无'}"
                )
            for student, note in row["需协商"].items():
                print(f"      需协商 {student}: {note}")
        print(f"  保底方案: {scenario['保底方案']}")
        print(f"  条件成立后最佳方案: {scenario['条件成立后最佳方案'] or '无变化'}")


def command_visits(records: Records, as_of: int | None, as_json: bool) -> None:
    cutoff = records.snapshot_cutoff() if as_of is None else as_of
    base_plan, _, base = best_plan_row(records, cutoff)
    blind = next(
        (
            p for p in records.plans.values()
            if p.opens and not p.extra_units
        ),
        None,
    )
    blind_sol = (
        analyse(records, plan_world(records, blind, cutoff)) if blind else None
    )
    results = []
    for visit, students in _visit_groups(records, cutoff).items():
        plan, _, sol = best_plan_row(
            records, cutoff, include_possibilities=True, possibility_students=set(students)
        )
        results.append(
            {
                "回访组": visit,
                "可能学生": sorted(students),
                "相对当前新增": sorted(sol.covered - base.covered),
                "相对当前失去": sorted(base.covered - sol.covered),
                "最佳方案": plan.plan if plan else "基准",
                "投放选择是否改变": (plan.plan if plan else "基准")
                != (base_plan.plan if base_plan else "基准"),
                "成本变化": (plan.cost if plan else 0)
                - (base_plan.cost if base_plan else 0),
            }
        )
    results.sort(
        key=lambda r: (
            len(r["相对当前新增"]) > 0,
            r["投放选择是否改变"],
            len(r["相对当前新增"]),
            -abs(r["成本变化"]),
        ),
        reverse=True,
    )
    all_plan, _, all_sol = best_plan_row(records, cutoff, include_possibilities=True)
    payload = {
        "当前方案": base_plan.plan if base_plan else "基准",
        "当前覆盖": sorted(base.covered),
        "盲目多开一班的覆盖": (
            sorted(blind_sol.covered) if blind_sol else None
        ),
        "盲目多开一班方案": blind.plan if blind else None,
        "优先回访": results,
        "全部同时确认后": {
            "最佳方案": all_plan.plan if all_plan else "基准",
            "覆盖": len(all_sol.covered),
        },
        "注意": "逐组新增不能相加；多人可能争用同一班次与设备，只用于比较先回访谁。",
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"当前方案 {payload['当前方案']}，覆盖 {len(base.covered)} 人")
    if blind_sol is not None:
        print(
            f"盲目多开一班（{blind.plan}）覆盖 {len(blind_sol.covered)} 人，"
            f"较当前 {len(blind_sol.covered) - len(base.covered):+d}"
        )
    print("优先回访:")
    for row in results:
        print(
            f"  {row['回访组']}（{', '.join(row['可能学生'])}）: "
            f"新增 {', '.join(row['相对当前新增']) or '无'}；"
            f"最佳方案 {row['最佳方案']}"
            f"{'（投放选择改变）' if row['投放选择是否改变'] else ''}，"
            f"成本变化 {row['成本变化']:+d}"
        )
    final = payload["全部同时确认后"]
    print(f"全部同时确认后最佳方案 {final['最佳方案']}，覆盖 {final['覆盖']} 人")
    print("注意:", payload["注意"])


def command_rosters(
    records: Records, as_of: int | None, as_json: bool, plan_name: str | None
) -> None:
    cutoff = records.snapshot_cutoff() if as_of is None else as_of
    if plan_name:
        plan = records.plans.get(plan_name)
        if plan is None:
            raise SystemExit(f"没有方案 {plan_name}")
        world = plan_world(records, plan, cutoff)
        sol = analyse(records, world)
    else:
        plan, world, sol = best_plan_row(records, cutoff)
    roster = []
    for student in sorted(sol.assignments, key=lambda s: (sol.assignments[s], s)):
        app = records.applications[student]
        roster.append(
            {
                "替代编号": f"R-{student.upper()}",
                "班": sol.assignments[student],
                "保障组": app.population,
                "来源": sol.sources.get(student, "new"),
            }
        )
    payload = {
        "方案": plan.plan if plan else "基准",
        "可承诺": sol.issuable,
        "名单": roster,
        "需协商": sol.negotiated,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not sol.issuable:
        print("该方案未守住保障或存在未履行的确认席位，不生成可发放名单。")
        for row in floor_rows(records, sol):
            tail = "" if row["是否达标"] else f"（缺 {row['缺口']}）"
            print(f"  {row['保障组']}: {row['实际覆盖']}/{row['最低覆盖']}{tail}")
        for student, note in sol.negotiated.items():
            print(f"  需协商 {student}: {note}")
        return
    print(f"方案: {payload['方案']}")
    for row in roster:
        print(f"  {row['替代编号']} {row['班']} {row['保障组']} ({row['来源']})")


def command_group(records: Records, as_of: int | None, as_json: bool) -> None:
    cutoff = records.snapshot_cutoff() if as_of is None else as_of
    plan, _, sol = best_plan_row(records, cutoff)
    by_pop: dict[str, dict] = {}
    for app in records.eligible_applicants():
        row = by_pop.setdefault(
            app.population, {"保障组": app.population, "分母": 0, "覆盖": 0, "未覆盖": 0}
        )
        row["分母"] += 1
        if app.student in sol.covered:
            row["覆盖"] += 1
        else:
            row["未覆盖"] += 1
    payload = {
        "使用方案": plan.plan if plan else "基准",
        "分母": len(records.denominator()),
        "分组": list(by_pop.values()),
        "保障组": floor_rows(records, sol),
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"方案 {payload['使用方案']}，分母 {payload['分母']} 人（只列分组结果）")
    for row in payload["分组"]:
        print(f"  {row['保障组']}: 覆盖 {row['覆盖']}/{row['分母']}")


def command_validate(records: Records, as_of: int | None, as_json: bool) -> None:
    problems: list[str] = []
    notices: list[str] = []
    groups = set(records.groups)
    for app in records.applications.values():
        unknown = set(app.accepted_groups) - groups
        if unknown:
            problems.append(f"{app.student} 接受未知班 {sorted(unknown)}")
        if not app.eligible and app.state == "request":
            notices.append(f"{app.student} 不具资格但状态为 request：进分母但不发放")
    for offer in records.offers:
        if offer.group not in groups:
            problems.append(f"承诺 {offer.offer} 指向未知班 {offer.group}")
        if offer.student not in records.applications:
            problems.append(f"承诺 {offer.offer} 指向未知学生 {offer.student}")
    for p in records.possibilities:
        if p.student not in records.applications:
            problems.append(f"可能班次指向未知学生 {p.student}")
        if set(p.groups) - groups:
            problems.append(f"{p.student} 的可能班次含未知班 {sorted(set(p.groups) - groups)}")
    for scenario, members in records.closures.items():
        if set(members) - groups:
            problems.append(f"情景 {scenario} 含未知班 {sorted(set(members) - groups)}")
    payload = {
        "问题": problems,
        "提示": notices,
        "结论": "通过" if not problems else "需人工核对",
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(payload["结论"])
    for problem in problems:
        print(" - 问题:", problem)
    for notice in notices:
        print(" - 提示:", notice)


# ---------------------------------------------------------------------------
# 入口


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="课程机会和设备投放的覆盖分析")
    parser.add_argument(
        "command",
        choices=[
            "baseline",
            "plans",
            "outage-blast",
            "scenarios",
            "visits",
            "rosters",
            "group",
            "validate",
        ],
    )
    parser.add_argument("--records", type=Path, default=ROOT, help="资料目录")
    parser.add_argument("--as-of", type=int, default=None, help="只采用 received/minutes <= N 的记录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--confirm-plan", default=None, help="对指定方案确认本轮发放")
    parser.add_argument("--plan", default=None, help="指定方案（默认按规则选最佳）")
    args = parser.parse_args(argv)
    records = Records.load(args.records)
    handlers = {
        "baseline": lambda: command_baseline(records, args.as_of, args.json),
        "plans": lambda: command_plans(records, args.as_of, args.json, args.confirm_plan),
        "outage-blast": lambda: command_outage(records, args.as_of, args.json, args.plan),
        "scenarios": lambda: command_scenarios(records, args.as_of, args.json),
        "visits": lambda: command_visits(records, args.as_of, args.json),
        "rosters": lambda: command_rosters(records, args.as_of, args.json, args.plan),
        "group": lambda: command_group(records, args.as_of, args.json),
        "validate": lambda: command_validate(records, args.as_of, args.json),
    }
    handlers[args.command]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
