from fastapi import APIRouter, HTTPException, Request

from app.harness.model_settings import ModelConfigurationUpdate, SettingsConflict


router = APIRouter(prefix="/api/model-settings")


@router.get("")
async def model_settings(request: Request, refresh: bool = False) -> dict:
    settings = request.app.state.model_settings
    if refresh:
        await settings.refresh()
    return settings.snapshot()


@router.post("")
async def save_model_settings(payload: ModelConfigurationUpdate, request: Request) -> dict:
    try:
        return {"state": request.app.state.model_settings.save(payload)}
    except SettingsConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
