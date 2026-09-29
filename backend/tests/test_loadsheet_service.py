"""载重平衡状态流和汇总口径的回归测试。"""
from __future__ import annotations

import unittest

from app.services.loadsheet import MODULE, LoadsheetService
from app.store import store


class LoadsheetServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        store._tables[MODULE] = []
        self.service = LoadsheetService()
        entry, messages = self.service.create_entry(
            {
                "配载单号": "LOAD-T1",
                "关联航班": "CA1001",
                "计算重量": "100 kg",
                "重心位置": "25% MAC",
                "配载人员": "配载员甲",
            }
        )
        self.assertIsNotNone(entry)
        self.assertEqual(messages, [])
        self.entry_id = entry["id"]

    def test_return_clears_pending_queue_review_signature_and_confirmed_aggregates(self) -> None:
        self.assertEqual(self.service.get_summary()["待复核配载"], 0)

        entry, message = self.service.run_action(
            self.entry_id, "提交复核", operator="配载员甲", role="配载人员"
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["status"], "待复核")
        self.assertTrue(entry["pending"])
        self.assertEqual(self.service.get_summary()["待复核配载"], 1)

        duplicate, _ = self.service.run_action(
            self.entry_id, "提交复核", operator="配载员甲", role="配载人员"
        )
        self.assertIsNone(duplicate)
        self.assertEqual(len(entry["复核记录"]), 1)

        returned, message = self.service.run_action(
            self.entry_id, "退回重算", operator="复核员甲", role="复核人员", opinion="请核对油量"
        )
        self.assertIsNotNone(returned)
        self.assertEqual(message, "配载单已退回重算")
        self.assertEqual(returned["status"], "已退回")
        self.assertFalse(returned["pending"])
        self.assertIsNone(returned["复核人员"])
        self.assertIsNone(returned["复核签字"])
        self.assertEqual(len(returned["复核记录"]), 1)
        self.assertEqual(returned["复核记录"][0]["复核人员"], "复核员甲")
        self.assertEqual(returned["结论复核人员"], "复核员甲")

        pending_rows, pending_total = self.service.list_entries(status="待复核")
        self.assertEqual(pending_rows, [])
        self.assertEqual(pending_total, 0)
        all_rows, all_total = self.service.list_entries()
        self.assertEqual(len(all_rows), all_total)
        summary = self.service.get_summary()
        self.assertEqual(summary["配载单总数"], all_total)
        self.assertEqual(summary["待复核配载"], 0)
        self.assertEqual(summary["退回重算数"], 1)
        self.assertEqual(summary["已确认计算重量"], 0)
        self.assertEqual(summary["已确认重心配载数"], 0)

    def test_returned_sheet_is_read_only_and_conclusion_cannot_be_changed(self) -> None:
        self.service.run_action(self.entry_id, "提交复核", operator="配载员甲", role="配载人员")
        self.service.run_action(
            self.entry_id, "退回重算", operator="复核员甲", role="复核人员", opinion="请核对油量"
        )

        planner_edit, planner_message = self.service.update_entry(
            self.entry_id, {"计算重量": "90 kg"}, operator="配载员甲", role="配载人员"
        )
        self.assertIsNone(planner_edit)
        self.assertIn("只读", planner_message)

        reviewer_edit, reviewer_message = self.service.update_entry(
            self.entry_id, {"复核结论": "已确认"}, operator="复核员甲", role="复核人员"
        )
        self.assertIsNone(reviewer_edit)
        self.assertIn("接收退回的账号不能改动复核结论", reviewer_message)

        resubmit, _ = self.service.run_action(
            self.entry_id, "提交复核", operator="配载员甲", role="配载人员"
        )
        self.assertIsNone(resubmit)

    def test_confirm_attributes_opinion_and_signature_to_reviewer_and_aggregates_only_confirmed(self) -> None:
        self.service.run_action(self.entry_id, "提交复核", operator="配载员甲", role="配载人员")
        confirmed, message = self.service.run_action(
            self.entry_id, "确认配载", operator="复核员甲", role="复核人员", opinion="复核无误"
        )
        self.assertIsNotNone(confirmed)
        self.assertEqual(message, "配载单已确认配载")
        self.assertEqual(confirmed["复核人员"], "复核员甲")
        self.assertEqual(confirmed["结论复核人员"], "复核员甲")
        self.assertTrue(confirmed["复核签字"].startswith("复核员甲 "))
        self.assertFalse(confirmed["pending"])
        self.assertTrue(confirmed["只读"])

        summary = self.service.get_summary()
        self.assertEqual(summary["待复核配载"], 0)
        self.assertEqual(summary["已确认配载数"], 1)
        self.assertEqual(summary["已确认计算重量"], 100.0)
        self.assertEqual(summary["已确认重心配载数"], 1)

    def test_duplicate_loadsheet_order_is_rejected(self) -> None:
        duplicate, messages = self.service.create_entry(
            {"配载单号": "LOAD-T1", "关联航班": "CA1002", "计算重量": "200 kg"}
        )
        self.assertIsNone(duplicate)
        self.assertTrue(messages[0].endswith("已存在，不能重复建单"))


if __name__ == "__main__":
    unittest.main()
