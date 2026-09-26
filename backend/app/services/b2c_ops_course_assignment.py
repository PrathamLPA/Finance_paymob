"""Map Sales course → Handling Department, assign from B2C - Student Support.

Flow:
1. Course product name (from inventory on the deal) → Handling Department enum
2. Load active users in Bitrix dept "B2C - Student Support" (id 108)
3. Keep only those whose Handiling Department matches the course
4. Assign that user (pool of one SPOC per dept in normal ops)

Enum IDs on UF_USR_1790154777183 (existing):
  19712 Finance & Accounting
  19714 People, Compliance & Business Services (was HR & Business Support)
  19716 Supply Chain, Risk & Technical Services
  19718 Technology, Analytics & Management
  19720 Procurement & Supply Chain

CIPD → "Human Resources & People Development" uses
BITRIX_HANDLING_DEPT_HR_PEOPLE_DEVELOPMENT_ENUM (create list value in Bitrix first).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.models.assignment_cursor import claim_round_robin_ids

logger = logging.getLogger(__name__)

HANDLING_DEPT_FINANCE = 19712
HANDLING_DEPT_HR = 19714  # People, Compliance & Business Services
HANDLING_DEPT_PROCUREMENT_COMPLIANCE = 19716  # Supply Chain, Risk & Technical Services
HANDLING_DEPT_TECH = 19718  # Technology, Analytics & Management
HANDLING_DEPT_PROCUREMENT_SC = 19720

HANDLING_DEPT_LABELS: dict[int, str] = {
    HANDLING_DEPT_FINANCE: "Finance & Accounting",
    HANDLING_DEPT_HR: "People, Compliance & Business Services",
    HANDLING_DEPT_PROCUREMENT_COMPLIANCE: "Supply Chain, Risk & Technical Services",
    HANDLING_DEPT_TECH: "Technology, Analytics & Management",
    HANDLING_DEPT_PROCUREMENT_SC: "Procurement & Supply Chain",
}

# Inventory-verified aliases (ACTIVE crm.product names, 2026-09-24).
# Longer aliases first. Word-boundary matching avoids VAT⊂Innovation, pd⊂cipd.
_COURSE_ALIAS_TO_DEPT: list[tuple[str, int]] = [
    # --- Technology (Yaseen) ---
    ("ev engineering", HANDLING_DEPT_TECH),
    ("certification in artificial intelligence and applied gen ai", HANDLING_DEPT_TECH),
    ("advanced certification in applied gen ai", HANDLING_DEPT_TECH),
    ("applied gen ai", HANDLING_DEPT_TECH),
    ("data analytics and data science", HANDLING_DEPT_TECH),
    ("data science and machine learning", HANDLING_DEPT_TECH),
    ("business analyst", HANDLING_DEPT_TECH),
    ("data analyst", HANDLING_DEPT_TECH),
    ("ai & gen ai", HANDLING_DEPT_TECH),
    ("ai and gen ai", HANDLING_DEPT_TECH),
    ("gen ai", HANDLING_DEPT_TECH),
    ("da & ds", HANDLING_DEPT_TECH),
    ("da and ds", HANDLING_DEPT_TECH),
    ("power bi", HANDLING_DEPT_TECH),
    ("talent management", HANDLING_DEPT_TECH),
    ("certified facility manager", HANDLING_DEPT_TECH),
    ("facility management", HANDLING_DEPT_TECH),
    ("microsoft excel", HANDLING_DEPT_TECH),
    ("advanced excel", HANDLING_DEPT_TECH),
    ("dsml", HANDLING_DEPT_TECH),
    ("python", HANDLING_DEPT_TECH),
    ("sphri", HANDLING_DEPT_TECH),
    ("ctm", HANDLING_DEPT_TECH),
    ("cfm", HANDLING_DEPT_TECH),
    ("pmp", HANDLING_DEPT_TECH),
    ("itil", HANDLING_DEPT_TECH),
    ("excel", HANDLING_DEPT_TECH),
    # --- Supply Chain / Risk / Technical (Jaswanth) ---
    ("comptia security+", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("comptia security", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("lean six sigma green belt", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("lean six sigma", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("train the trainer", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("document controller", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("document control", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("certified supply chain professional", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("clscmp", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("cscp", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("cipp", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("cipm", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("cpcm", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("lssgb", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("ttt", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("aml", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("ifrs", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("cdm", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("ev business", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    ("ev", HANDLING_DEPT_PROCUREMENT_COMPLIANCE),
    # --- People / Compliance / Business Services (Ramya) ---
    ("uae labour laws", HANDLING_DEPT_HR),
    ("uae labour", HANDLING_DEPT_HR),
    ("uae ll", HANDLING_DEPT_HR),
    ("vat (value added tax)", HANDLING_DEPT_HR),
    ("saudi vat", HANDLING_DEPT_HR),
    ("executive secretarial management", HANDLING_DEPT_HR),
    ("chrp", HANDLING_DEPT_HR),
    ("chrm", HANDLING_DEPT_HR),
    ("psps", HANDLING_DEPT_HR),
    ("shrm", HANDLING_DEPT_HR),
    ("esm", HANDLING_DEPT_HR),
    ("vat", HANDLING_DEPT_HR),
    ("pd", HANDLING_DEPT_HR),
    ("ct", HANDLING_DEPT_HR),
    # --- Finance (Ziya) ---
    ("e-invoicing", HANDLING_DEPT_FINANCE),
    ("e invoicing", HANDLING_DEPT_FINANCE),
    ("einvoicing", HANDLING_DEPT_FINANCE),
    ("cma", HANDLING_DEPT_FINANCE),
    # --- Procurement & Supply Chain (Ayisha) ---
    ("cips", HANDLING_DEPT_PROCUREMENT_SC),
]

# CIPD inventory names verified in Bitrix crm.product.list (2026-09-24):
#   CIPD Courses, CIPD Level 3/5/7, Level 5 Associate Diploma…, Level 7 Advanced Diploma…
# Bare product name "CIPD" is NOT in inventory (only in some BP conditions).
_CIPD_ALIASES: tuple[str, ...] = (
    "cipd level 7 - advanced diploma in strategic learning & development course",
    "cipd level 5 - associate diploma in organisational learning and development course",
    "cipd courses",
    "cipd level 3",
    "cipd level 5",
    "cipd level 7",
    "cipd",
)


def _normalize_course_label(name: str) -> str:
    text = re.sub(r"[\s_\-]+", " ", str(name or "").strip())
    return text.casefold()


def _alias_matches(alias: str, label: str) -> bool:
    """True when alias appears as whole token(s) in label (not inside another word).

    Prevents ``pd`` matching inside ``cipd``, ``ct`` inside unrelated tokens, etc.
    """
    pattern = r"(?<![\w])" + re.escape(alias) + r"(?![\w])"
    return re.search(pattern, label) is not None


def hr_people_development_enum_id(settings: Any | None = None) -> int | None:
    """Bitrix list ID for Handiling Department = Human Resources & People Development."""
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    raw = (getattr(settings, "bitrix_handling_dept_hr_people_development_enum", "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "Invalid BITRIX_HANDLING_DEPT_HR_PEOPLE_DEVELOPMENT_ENUM=%r", raw
        )
        return None


def _alias_table(settings: Any | None = None) -> list[tuple[str, int]]:
    rows = list(_COURSE_ALIAS_TO_DEPT)
    cipd_dept = hr_people_development_enum_id(settings)
    if cipd_dept is not None:
        for alias in reversed(_CIPD_ALIASES):
            rows.insert(0, (alias, cipd_dept))
    return rows


def handling_department_for_course(
    course_name: str, *, settings: Any | None = None
) -> int | None:
    """Return Handling Department enum ID for a course product title, or None."""
    label = _normalize_course_label(course_name)
    if not label:
        return None
    # CIPD is its own Handiling Department — never fall through to other aliases.
    if _alias_matches("cipd", label):
        cipd_dept = hr_people_development_enum_id(settings)
        if cipd_dept is None:
            logger.warning(
                "CIPD course %r needs BITRIX_HANDLING_DEPT_HR_PEOPLE_DEVELOPMENT_ENUM "
                "(Handiling Department list value for 'Human Resources & People Development')",
                course_name,
            )
            return None
        return cipd_dept
    for alias, dept_id in _alias_table(settings):
        if _alias_matches(alias, label):
            return dept_id
    return None


def handling_department_label(dept_id: int | None, settings: Any | None = None) -> str | None:
    if dept_id is None:
        return None
    dept_id = int(dept_id)
    if dept_id == hr_people_development_enum_id(settings):
        return "Human Resources & People Development"
    return HANDLING_DEPT_LABELS.get(dept_id)


def _employee_handling_enum(employee: dict[str, Any]) -> int | None:
    raw = employee.get("handling_department")
    if raw in (None, "", [], {}):
        return None
    if isinstance(raw, list) and raw:
        raw = raw[0]
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def pool_for_handling_department(
    employees: list[dict[str, Any]], handling_dept_enum_id: int
) -> list[int]:
    """User ids in B2C - Student Support whose Handiling Department matches."""
    target = int(handling_dept_enum_id)
    pool: list[int] = []
    for emp in employees:
        if _employee_handling_enum(emp) != target:
            continue
        try:
            uid = int(emp["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if uid > 0:
            pool.append(uid)
    return sorted(set(pool))


async def assignees_for_course_units(
    bitrix: Any,
    course_names: list[str],
    *,
    db: Any | None = None,
    settings: Any | None = None,
) -> list[int | None]:
    """Assign each course unit from B2C - Student Support by Handling Department."""
    if settings is None:
        settings = getattr(bitrix, "settings", None)

    try:
        employees = await bitrix.list_b2c_ops_employees()
    except Exception:
        logger.exception("Failed to load B2C - Student Support employees")
        employees = []

    if not employees:
        logger.warning(
            "B2C Ops course assign: no employees in B2C - Student Support department"
        )

    pending_by_dept: dict[int, list[str]] = {}
    for name in course_names:
        dept = handling_department_for_course(name, settings=settings)
        if dept is None:
            continue
        pending_by_dept.setdefault(dept, []).append(name)

    claimed_by_dept: dict[int, list[int]] = {}
    for dept, names in pending_by_dept.items():
        pool = pool_for_handling_department(employees, dept)
        if not pool:
            logger.warning(
                "No B2C - Student Support user with Handling Department %s (%s) "
                "for courses %s",
                dept,
                handling_department_label(dept, settings=settings),
                names,
            )
            claimed_by_dept[dept] = []
            continue
        if db is not None and len(pool) > 1:
            claimed_by_dept[dept] = claim_round_robin_ids(
                db,
                key=f"b2c_ops_handling_{dept}",
                pool=pool,
                count=len(names),
            )
        else:
            # Single SPOC (normal): always that user. Multi without DB: first match.
            claimed_by_dept[dept] = [pool[0] for _ in names]
        logger.info(
            "B2C Ops Handling Department pool | dept=%s (%s) pool=%s claimed=%s",
            dept,
            handling_department_label(dept, settings=settings),
            pool,
            claimed_by_dept[dept],
        )

    cursor_by_dept: dict[int, int] = {d: 0 for d in claimed_by_dept}
    out: list[int | None] = []
    for name in course_names:
        dept = handling_department_for_course(name, settings=settings)
        if dept is None:
            logger.warning("No Handling Department map for course %r", name)
            out.append(None)
            continue
        claimed = claimed_by_dept.get(dept) or []
        idx = cursor_by_dept.get(dept, 0)
        user_id = claimed[idx] if idx < len(claimed) else None
        cursor_by_dept[dept] = idx + 1
        logger.info(
            "B2C Ops course assign | course=%r dept=%s (%s) user=%s "
            "(from B2C - Student Support)",
            name,
            dept,
            handling_department_label(dept, settings=settings),
            user_id,
        )
        out.append(user_id)
    return out
