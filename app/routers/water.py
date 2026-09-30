"""水质证专页：台账查看、登记/更新、作废。"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.db import get_db
from app.models import WaterCert, Workshop
from app.services.water_rules import (
    VALID_WINDOW_DAYS,
    WaterCertError,
    cert_status_label,
    latest_valid_cert,
    validate_cert_fields,
)
from app.templating import render

router = APIRouter()


def _certs_context(
    request: Request,
    db: Session,
    user,
    error: Optional[str] = None,
):
    today = date.today()
    workshops = db.query(Workshop).order_by(Workshop.name).all()
    certs = (
        db.query(WaterCert)
        .options(joinedload(WaterCert.workshop))
        .order_by(WaterCert.sampled_on.desc(), WaterCert.id.desc())
        .all()
    )
    # 「最新有效」与还原台 chip、闲置改还原中校验同源（latest_valid_cert）
    latest_valid_ids = {}
    for w in workshops:
        cert = latest_valid_cert(db, w.id, today)
        latest_valid_ids[w.id] = cert.id if cert else None

    ws_summaries = [
        {
            "id": w.id,
            "name": w.name,
            "region": w.region,
            "has_valid": latest_valid_ids[w.id] is not None,
        }
        for w in workshops
    ]
    rows = [
        {
            "id": c.id,
            "workshop_id": c.workshop_id,
            "workshop_name": c.workshop.name if c.workshop else "",
            "sampled_on": c.sampled_on.isoformat(),
            "hardness": float(c.hardness),
            "qualified": c.qualified,
            "tester": c.tester,
            "voided": c.voided,
            "status_label": cert_status_label(c, today),
            "is_latest_valid": latest_valid_ids.get(c.workshop_id) == c.id,
        }
        for c in certs
    ]
    return {
        "request": request,
        "user": user,
        "workshops": ws_summaries,
        "certs": rows,
        "certs_json": rows,
        "valid_window_days": VALID_WINDOW_DAYS,
        "today": today.isoformat(),
        "error": error,
        "active": "water",
    }


@router.get("/water-certs", response_class=HTMLResponse)
async def water_certs_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return render(request, "water_certs.html", _certs_context(request, db, user))


@router.post("/water-certs/save", response_class=HTMLResponse)
async def water_cert_save(
    request: Request,
    cert_id: str = Form(""),
    workshop_id: str = Form(...),
    sampled_on: str = Form(...),
    hardness: str = Form(...),
    qualified: str = Form("1"),
    tester: str = Form(""),
    db: Session = Depends(get_db),
):
    """新建与更新共用入口：同坊同日唯一 + 硬度区间校验一致。"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    error = None
    try:
        try:
            ws_id = int(workshop_id.strip())
        except ValueError:
            raise WaterCertError("请选择所属工坊。")
        workshop = db.get(Workshop, ws_id)
        if not workshop:
            raise WaterCertError("所选工坊不存在。")
        try:
            sampled = date.fromisoformat(sampled_on.strip())
        except ValueError:
            raise WaterCertError("取样日格式不正确。")
        try:
            hard = Decimal(hardness.strip())
        except InvalidOperation:
            raise WaterCertError("硬度值格式不正确。")
        validate_cert_fields(hard)
        tester_name = tester.strip()
        if not tester_name:
            raise WaterCertError("请填写化验人。")
        is_qualified = qualified == "1"

        target = None
        if cert_id.strip():
            try:
                target = db.get(WaterCert, int(cert_id.strip()))
            except ValueError:
                target = None
            if not target:
                raise WaterCertError("要更新的水质证不存在。")
            if target.voided:
                raise WaterCertError("已作废的水质证不能再编辑。")

        # 同坊同日唯一（新建与更新共用）；数据库唯一约束兜底并发提交
        clash = (
            db.query(WaterCert)
            .filter(
                WaterCert.workshop_id == ws_id,
                WaterCert.sampled_on == sampled,
                WaterCert.id != (target.id if target else 0),
            )
            .first()
        )
        if clash:
            raise WaterCertError(
                f"{workshop.name}在 {sampled.isoformat()} 已有水质证，同坊同日只能登记一张。"
            )

        if target is None:
            target = WaterCert(workshop_id=ws_id)
            db.add(target)
        target.workshop_id = ws_id
        target.sampled_on = sampled
        target.hardness = hard
        target.qualified = is_qualified
        target.tester = tester_name
        try:
            db.commit()
        except IntegrityError:
            # 两人几乎同时提交同坊同日：唯一约束只放行一笔，其余在此被拒
            db.rollback()
            raise WaterCertError(
                f"{workshop.name}在 {sampled.isoformat()} 已有水质证，"
                "本次登记被拒绝，请刷新台账后核对。"
            )
        return RedirectResponse("/water-certs", status_code=303)
    except WaterCertError as exc:
        error = exc.message
        db.rollback()
    return render(
        request,
        "water_certs.html",
        _certs_context(request, db, user, error),
        status_code=400,
    )


@router.post("/water-certs/{pk}/void", response_class=HTMLResponse)
async def water_cert_void(
    pk: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """作废仅主管可操作；作废后立即失效（三处判定同源，无需额外刷新）。"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.is_superuser:
        return render(
            request,
            "water_certs.html",
            _certs_context(request, db, user, "仅主管可作废水质证。"),
            status_code=403,
        )
    cert = db.get(WaterCert, pk)
    if not cert:
        return RedirectResponse("/water-certs", status_code=303)
    cert.voided = True
    db.commit()
    return RedirectResponse("/water-certs", status_code=303)
