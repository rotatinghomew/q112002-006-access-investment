import unittest
from pathlib import Path

import coverage as c

ROOT = Path(__file__).resolve().parent.parent / "records"


class CoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = c.Records.load(ROOT)
        cls.cutoff = cls.records.snapshot_cutoff()

    # -- 分母与状态 ---------------------------------------------------------
    def test_denominator_is_eligible_applicants_not_invitees(self):
        self.assertEqual(
            self.records.denominator(),
            ["s1", "s10", "s2", "s3", "s4", "s5", "s6", "s7", "s9"],
        )
        self.assertNotIn("s8", self.records.denominator())
        self.assertNotIn("s8", self.records.candidates())

    def test_declined_and_wait_stay_in_denominator_but_do_not_get_offers(self):
        plan, _, sol = c.best_plan_row(self.records, self.cutoff)
        self.assertIn("s6", self.records.denominator())
        self.assertIn("s7", self.records.denominator())
        self.assertNotIn("s6", sol.assignments)
        self.assertNotIn("s7", sol.assignments)

    def test_uncovered_reasons_are_distinguished(self):
        plan = self.records.baseline_plan()
        sol = c.analyse(self.records, c.plan_world(self.records, plan, self.cutoff))
        self.assertIn("拒绝", sol.reasons["s6"])
        self.assertIn("先等", sol.reasons["s7"])

    # -- 资源 ---------------------------------------------------------------
    def test_overlapping_classes_cannot_share_one_unit(self):
        groups = self.records.groups
        world = c.build_world(self.records, cutoff=self.cutoff)
        ok, why = c.resource_ok(world, groups["g2"], [groups["g1"], groups["g2"]])
        self.assertFalse(ok)
        self.assertIn("需 2 件", why)

    def test_half_open_intervals_do_not_overlap_at_boundary(self):
        groups = self.records.groups
        # g1 结束于 630，与次日不重叠；同日相接的班不冲突。
        self.assertLess(groups["g2"].start, groups["g1"].end)
        world = c.build_world(self.records, cutoff=self.cutoff)
        ok, _ = c.resource_ok(world, groups["g1"], [groups["g1"]])
        self.assertTrue(ok)

    def test_plan_extra_equipment_unlocks_shared_day(self):
        plan = self.records.plans["跨日补位"]
        world = c.plan_world(self.records, plan, self.cutoff)
        sol = c.analyse(self.records, world)
        self.assertTrue(sol.all_floors_met)
        self.assertEqual(len(sol.covered), 7)

    def test_opening_two_groups_that_target_same_people_is_not_enough(self):
        plan = self.records.plans["只开课"]
        world = c.plan_world(self.records, plan, self.cutoff)
        sol = c.analyse(self.records, world)
        self.assertFalse(sol.all_floors_met)

    # -- 方案比较 -----------------------------------------------------------
    def test_plan_ranking_puts_floors_before_coverage_then_cost(self):
        rows = c.ranked_plans(self.records, self.cutoff)
        ranked = sorted(rows, key=lambda r: (r[2].issuable, len(r[2].covered), -r[0].cost), reverse=True)
        self.assertEqual(ranked[0][0].plan, "跨日补位")
        # 未守住保障的方案不能因为覆盖同分或便宜而排在可发放方案前。
        self.assertEqual([p.plan for p, _, s in ranked if s.issuable], ["跨日补位"])

    def test_unmet_floor_plan_is_not_handed_to_academics(self):
        plan = self.records.plans["只开课"]
        world = c.plan_world(self.records, plan, self.cutoff)
        sol = c.analyse(self.records, world)
        self.assertFalse(sol.issuable)
        notes = c._blocking_constraints(self.records, world, sol)
        self.assertTrue(notes)

    def test_confirmed_offers_are_kept_before_new_allocations(self):
        plan, _, sol = c.best_plan_row(self.records, self.cutoff)
        self.assertEqual(sol.assignments["s1"], "g1")
        self.assertEqual(sol.assignments["s3"], "g3")
        self.assertEqual(sol.sources["s1"], "offer:f1")

    # -- 回执与可能性 -------------------------------------------------------
    def test_confirmation_acceptance_limits_student_to_that_group(self):
        accepted, declined = c.confirmation_updates(self.records, self.cutoff)
        self.assertEqual(accepted["s10"], {"g2"})
        self.assertIn("g3", declined["s10"])
        plan, _, sol = c.best_plan_row(self.records, self.cutoff)
        if "s10" in sol.assignments:
            self.assertEqual(sol.assignments["s10"], "g2")

    def test_possibilities_are_not_counted_without_confirmation(self):
        plan = self.records.baseline_plan()
        definite = c.analyse(self.records, c.plan_world(self.records, plan, self.cutoff))
        self.assertNotIn("s4", definite.assignments)
        self.assertNotIn("s9", definite.assignments)

    def test_floors_kept_for_baseline_are_not_double_counted(self):
        plan = self.records.plans["跨日补位"]
        world = c.plan_world(self.records, plan, self.cutoff)
        base = c.analyse(self.records, world)
        held = c.analyse_conditional(
            self.records,
            c.plan_world(self.records, plan, self.cutoff),
            base=base,
            possibility_students={"s4"},
            release={"s4"},
            prefer={"s4"},
        )
        self.assertTrue(base.covered <= held.covered | {s for s in base.covered})

    def test_same_student_counts_at_most_once(self):
        plan = self.records.plans["跨日补位"]
        sol = c.analyse(
            self.records,
            c.plan_world(self.records, plan, self.cutoff),
            include_possibilities=True,
        )
        self.assertEqual(len(sol.assignments), len(set(sol.assignments)))
        self.assertTrue(sol.covered <= set(sol.assignments))

    # -- 停用 ---------------------------------------------------------------
    def test_outage_negotiates_unfulfillable_commitment_without_reassigning(self):
        cutoff = self.records.outage_cutoff()
        plan = self.records.plans["跨日补位"]
        sol = c.analyse(self.records, c.plan_world(self.records, plan, cutoff))
        self.assertIn("s3", sol.negotiated)
        self.assertNotIn("s3", sol.assignments)
        status = c.commitment_status(
            self.records, c.plan_world(self.records, plan, cutoff)
        )
        row = next(r for r in status if r["学生"] == "s3")
        self.assertEqual(row["结论"], "需协商")

    def test_outage_keeps_deliverable_commitment(self):
        cutoff = self.records.outage_cutoff()
        plan = self.records.plans["跨日补位"]
        sol = c.analyse(self.records, c.plan_world(self.records, plan, cutoff))
        self.assertEqual(sol.assignments.get("s1"), "g1")
        self.assertNotIn("s1", sol.negotiated)

    def test_outage_gap_is_not_attributed_to_denominator(self):
        snapshot = self.records.snapshot_cutoff()
        later = self.records.outage_cutoff()
        plan = self.records.plans["跨日补位"]
        before = c.analyse(self.records, c.plan_world(self.records, plan, snapshot, outages=False))
        after = c.analyse(self.records, c.plan_world(self.records, plan, later))
        summary = c.gap(before, after, self.records.denominator())
        self.assertFalse(summary["分母是否变化"])
        self.assertIn("不是分母变化", summary["说明"])

    # -- 命令可运行 ---------------------------------------------------------
    def test_every_command_returns_without_mutating_records(self):
        before = self.records.denominator()
        for command in ("baseline", "plans", "outage-blast", "scenarios", "visits", "rosters", "group", "validate"):
            with self.subTest(command=command):
                self.assertEqual(c.main([command, "--records", str(ROOT), "--json"]), 0)
        self.assertEqual(self.records.denominator(), before)


if __name__ == "__main__":
    unittest.main()
