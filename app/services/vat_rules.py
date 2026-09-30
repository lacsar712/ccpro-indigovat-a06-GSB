"""染缸状态业务规则。"""

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models import DipLot, Vat
from app.services.water_rules import VALID_WINDOW_DAYS, latest_valid_cert


class VatRuleError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def assert_can_mark_ready(latest: Optional[DipLot]) -> None:
    """不能将染缸标为 ready，除非最新浸染批次 redoxMv 已填且 <= -500。"""
    if latest is None or latest.redoxMv is None or Decimal(latest.redoxMv) > Decimal("-500"):
        raise VatRuleError(
            "无法设为可染色：最新浸染批次的氧化还原电位为空或高于 -500 mV。"
        )


def assert_has_valid_water_cert(db: Session, vat: Vat) -> None:
    """闲置缸进还原中前，所属工坊须持有有效水质证（与 chip、专页同源）。"""
    cert = latest_valid_cert(db, vat.workshop_id)
    if cert is None:
        name = vat.workshop.name if vat.workshop else "该工坊"
        raise VatRuleError(
            f"无法设为还原中：{name}当前没有有效水质证"
            f"（须合格、取样日在最近 {VALID_WINDOW_DAYS} 个自然日内且未作废），"
            "请先在「水质证」页登记。"
        )


def validate_vat_status_change(
    vat: Vat, new_status: str, latest: Optional[DipLot], db: Session
) -> None:
    if new_status == Vat.STATUS_READY:
        assert_can_mark_ready(latest)
    if vat.status == Vat.STATUS_IDLE and new_status == Vat.STATUS_REDUCING:
        assert_has_valid_water_cert(db, vat)
