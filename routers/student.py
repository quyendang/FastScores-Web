from datetime import datetime, timezone
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.data_service import validate_token, fetch_student_report_data

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/student/{token}", response_class=HTMLResponse)
async def student_report(request: Request, token: str):
    token_row, error_template, status_code = validate_token(token, expected_scope="student_report")
    if error_template:
        return templates.TemplateResponse(
            error_template, {"request": request}, status_code=status_code
        )

    ctx = fetch_student_report_data(token_row)
    ctx["request"] = request
    ctx["generated_at"] = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    return templates.TemplateResponse("student.html", ctx)
