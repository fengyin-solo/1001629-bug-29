"""载重平衡接口：维护配载单，覆盖提交复核、确认配载、退回重算等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.loadsheet import LoadsheetService

router = APIRouter(prefix="/api/loadsheet", tags=["载重平衡"])

service = LoadsheetService()

LIST_FIELDS = [
    "配载单号",
    "关联航班",
    "计算重量",
    "重心位置",
    "油量数据",
    "配载人员",
    "复核人员",
    "复核意见",
    "复核结论",
    "结论复核人员",
    "复核签字",
    "配载状态",
]
STATUSES = ["待计算", "待复核", "已确认", "已退回"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按配载单号检索"),
    status: str | None = Query(default=None, description="待计算、待复核、已确认、已退回"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按配载单号与状态过滤载重平衡列表；汇总口径与当前筛选一致。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    summary = service.get_summary(keyword=keyword, status=status)
    return PageResult(items=items, total=total, page=page, size=size, summary=summary)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出载重平衡清单：返回当前全量数据及同一口径的汇总。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "loadsheet", "total": total, "summary": service.get_summary(), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条配载单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"配载单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条配载单，缺字段时说明原因而不是静默丢弃。"""
    entry, messages = service.create_entry(payload.values)
    if messages:
        detail = "、".join(messages)
        if any("已存在" in message for message in messages):
            message = detail
        else:
            message = f"缺少必填字段：{detail}"
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="配载单已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """按账号角色限制可修改字段；提交后的配载数据和复核结论均保持锁定。"""
    values = payload.values
    entry, message = service.update_entry(
        entry_id,
        values,
        operator=str(values.get("operator") or values.get("配载人员") or "").strip() or None,
        role=str(values.get("role") or "").strip() or None,
    )
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条配载单执行提交复核、确认配载、退回重算；不允许的动作会被拦下并说明原因。"""
    values = payload.values
    action = str(values.get("action") or "").strip()
    opinion = values.get("复核意见") or values.get("opinion") or payload.remark
    entry, message = service.run_action(
        entry_id,
        action,
        operator=str(values.get("operator") or values.get("配载人员") or "").strip() or None,
        role=str(values.get("role") or "").strip() or None,
        opinion=str(opinion or "").strip() or None,
    )
    return ActionResult(ok=entry is not None, message=message, entry=entry)
