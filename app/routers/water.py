import json
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2.utils import markupsafe
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.db import get_db
from app.models import User, WaterCert, Workshop
from app.services.water_certs import (
    DUPLICATE_MSG,
    WaterCertError,
    is_valid_cert,
    latest_valid_by_workshop,
    parse_hardness,
    parse_sample_date,
    today_local,
    validate_unique,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["tojson"] = lambda v: markupsafe.Markup(
    json.dumps(v, ensure_ascii=False)
)


def render(request: Request, name: str, context: dict, status_code: int = 200):
    ctx = {k: v for k, v in context.items() if k != "request"}
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _cert_payload(cert: WaterCert, today: date, latest_id: Optional[int]) -> dict:
    return {
        "id": cert.id,
        "workshopId": cert.workshop_id,
        "workshopName": cert.workshop.name if cert.workshop else "",
        "sampledOn": cert.sampled_on.isoformat(),
        "hardness": float(cert.hardness),
        "passed": bool(cert.passed),
        "chemist": cert.chemist,
        "voided": bool(cert.voided),
        "validNow": is_valid_cert(cert, today),
        "isLatestValid": latest_id == cert.id,
    }


def _page_context(
    request: Request,
    db: Session,
    user: User,
    error: Optional[str] = None,
    form: Optional[dict] = None,
):
    today = today_local()
    workshops = db.query(Workshop).order_by(Workshop.name).all()
    certs = (
        db.query(WaterCert)
        .options(joinedload(WaterCert.workshop))
        .order_by(WaterCert.sampled_on.desc(), WaterCert.id.desc())
        .all()
    )
    latest = latest_valid_by_workshop(db, today)
    cert_rows = []
    for c in certs:
        latest_cert = latest.get(c.workshop_id)
        cert_rows.append(
            _cert_payload(c, today, latest_cert.id if latest_cert else None)
        )
    return {
        "request": request,
        "user": user,
        "workshops": [{"id": w.id, "name": w.name} for w in workshops],
        "certs": cert_rows,
        "today": today.isoformat(),
        "valid_days": WaterCert.VALID_DAYS,
        "error": error,
        "form": form or {},
        "active": "water",
    }


@router.get("/water-certs", response_class=HTMLResponse)
async def water_certs_page(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return render(request, "water.html", _page_context(request, db, user))


def _parse_cert_form(
    db: Session,
    workshop_id_raw: str,
    sampled_on_raw: str,
    hardness_raw: str,
    passed_raw: str,
    chemist: str,
    exclude_id: Optional[int] = None,
) -> tuple[int, date, Decimal, bool, str]:
    workshop_id = int(workshop_id_raw)
    if not db.get(Workshop, workshop_id):
        raise WaterCertError("所选工坊不存在。")
    sampled_on = parse_sample_date(sampled_on_raw)
    hardness = parse_hardness(hardness_raw)
    chemist = chemist.strip()
    if not chemist:
        raise WaterCertError("化验人不可为空。")
    validate_unique(db, workshop_id, sampled_on, exclude_id)
    return workshop_id, sampled_on, hardness, passed_raw == "1", chemist


@router.post("/water-certs", response_class=HTMLResponse)
async def water_cert_create(
    request: Request,
    workshop_id: str = Form(...),
    sampled_on: str = Form(...),
    hardness: str = Form(...),
    passed: str = Form("0"),
    chemist: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = {
        "workshop_id": workshop_id,
        "sampled_on": sampled_on,
        "hardness": hardness,
        "passed": passed,
        "chemist": chemist,
    }
    try:
        ws_id, day, hard, ok, who = _parse_cert_form(
            db, workshop_id, sampled_on, hardness, passed, chemist
        )
        db.add(
            WaterCert(
                workshop_id=ws_id,
                sampled_on=day,
                hardness=hard,
                passed=ok,
                chemist=who,
            )
        )
        # 两人几乎同时交同坊同日证：唯一约束保证至多一笔入库
        db.commit()
        return RedirectResponse("/water-certs", status_code=303)
    except WaterCertError as exc:
        db.rollback()
        error = exc.message
    except (IntegrityError, ValueError) as exc:
        db.rollback()
        error = DUPLICATE_MSG if isinstance(exc, IntegrityError) else f"水质证无效：{exc}"
    return render(
        request,
        "water.html",
        _page_context(request, db, user, error, form),
        status_code=400,
    )


@router.post("/water-certs/{pk}/update", response_class=HTMLResponse)
async def water_cert_update(
    pk: int,
    request: Request,
    workshop_id: str = Form(...),
    sampled_on: str = Form(...),
    hardness: str = Form(...),
    passed: str = Form("0"),
    chemist: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    cert = db.get(WaterCert, pk)
    if not cert:
        return RedirectResponse("/water-certs", status_code=303)
    if cert.voided:
        return render(
            request,
            "water.html",
            _page_context(request, db, user, "已作废的水质证不可再编辑。"),
            status_code=400,
        )
    try:
        ws_id, day, hard, ok, who = _parse_cert_form(
            db, workshop_id, sampled_on, hardness, passed, chemist, exclude_id=pk
        )
        cert.workshop_id = ws_id
        cert.sampled_on = day
        cert.hardness = hard
        cert.passed = ok
        cert.chemist = who
        db.commit()
        return RedirectResponse("/water-certs", status_code=303)
    except WaterCertError as exc:
        db.rollback()
        error = exc.message
    except (IntegrityError, ValueError) as exc:
        db.rollback()
        error = DUPLICATE_MSG if isinstance(exc, IntegrityError) else f"水质证无效：{exc}"
    return render(
        request,
        "water.html",
        _page_context(request, db, user, error),
        status_code=400,
    )


@router.post("/water-certs/{pk}/void", response_class=HTMLResponse)
async def water_cert_void(
    pk: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.is_superuser:
        return render(
            request,
            "water.html",
            _page_context(request, db, user, "仅主管可作废水质证。"),
            status_code=403,
        )
    cert = db.get(WaterCert, pk)
    if cert and not cert.voided:
        cert.voided = True  # 作废后立即失效：有效性实时计算
        db.commit()
    return RedirectResponse("/water-certs", status_code=303)
