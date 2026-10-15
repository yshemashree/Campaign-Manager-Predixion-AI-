from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import SessionDep, SettingsDep, TenantDep, load_workspace_ids
from app.core.errors import Unauthorized
from app.core.security import create_access_token, verify_password
from app.models import User
from app.schemas.tenancy import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    # Same message whether the email or the password is wrong, so emails can't be probed.
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise Unauthorized("Wrong email or password")
    out = UserOut.model_validate(user)
    out.workspace_ids = sorted(await load_workspace_ids(session, user))
    return TokenResponse(access_token=create_access_token(settings, user.id, user.role), user=out)


@router.get("/me", response_model=UserOut)
async def me(ctx: TenantDep) -> UserOut:
    out = UserOut.model_validate(ctx.user)
    out.workspace_ids = sorted(ctx.workspace_ids)
    return out
