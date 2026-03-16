from datetime import datetime, timezone
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.templating import Jinja2Templates

from services.data_service import validate_token, fetch_class_report_data
from services.export_service import export_csv, export_excel

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/report/{token}", response_class=HTMLResponse)
async def class_report(request: Request, token: str):
    token_row, error_template, status_code = validate_token(token, expected_scope="class_report")
    if error_template:
        return templates.TemplateResponse(
            error_template, {"request": request}, status_code=status_code
        )

    ctx = fetch_class_report_data(token_row)
    ctx["request"] = request
    ctx["token"] = token
    ctx["generated_at"] = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    return templates.TemplateResponse("report.html", ctx)


@router.get("/export/{token}")
async def export_report(
    token: str,
    format: str = Query(default="csv", pattern="^(csv|excel)$"),
):
    token_row, error_template, status_code = validate_token(token, expected_scope="class_report")
    if error_template:
        return Response(content="Invalid or expired token", status_code=status_code)

    ctx = fetch_class_report_data(token_row)

    if format == "csv":
        output, filename = export_csv(ctx)
        return StreamingResponse(
            iter([output]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        output, filename = export_excel(ctx)
        return Response(
            content=output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
