from pydantic import BaseModel, Field


class Observation(BaseModel):
    tag_id: str
    rssi: int
    count: int
    last_seen: int


class Payload(BaseModel):
    reader_id: str
    ts: int
    observations: list[Observation]


class LoginRequest(BaseModel):
    username: str
    password: str
    role: str


class RegisterRequest(BaseModel):
    username: str
    display_name: str
    password: str
    email: str
    position: str | None = None
    role: str = "staff"
    department: str | None = None
    is_active: bool = True


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: str


class FindIdRequest(BaseModel):
    email: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


class SessionExchangeRequest(BaseModel):
    code: str


class GoogleCompleteRequest(BaseModel):
    pending_token: str
    username: str
    display_name: str | None = None
    role: str = "staff"
    department: str | None = None
    position: str | None = None
    password: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChangeEmailRequest(BaseModel):
    new_email: str
    current_password: str


class WithdrawRequest(BaseModel):
    current_password: str


class NfcMappingUpsertRequest(BaseModel):
    tag_id: str
    nfc_token: str


class NfcUsageActionRequest(BaseModel):
    nfc_token: str


class ReaderMapPositionRequest(BaseModel):
    floor: int = Field(ge=1, le=5)
    map_x: float = Field(ge=0, le=100)
    map_y: float = Field(ge=0, le=100)
    location_name: str | None = None
